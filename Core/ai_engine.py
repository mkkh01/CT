import pandas as pd
import xgboost as xgb
from database import AsyncSessionLocal, PaperTrade, UserConfig, TrackedCoin
from sqlalchemy import select
from Core.risk_manager import RiskManager
from macro_data import MacroAnalyzer
from strategies import SpotStrategies
import ccxt.async_support as ccxt
import asyncio

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.risk_manager = RiskManager()
        self.macro = MacroAnalyzer()
        self.strategies = SpotStrategies()
        self.model = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1)
        self.bot = bot
        self.chat_id = chat_id
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })

    async def get_coin_config(self, symbol: str):
        """جلب إعدادات العملة المخصصة (رأس المال والإطار الزمني)"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol))
            return result.scalars().first()

    async def get_candlestick_data(self, symbol: str, timeframe: str, limit: int = 100):
        """جلب بيانات الشموع (candlestick data) من Binance"""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"خطأ في جلب بيانات الشموع لـ {symbol}: {e}")
            return pd.DataFrame()

    async def analyze_and_trade(self, symbol: str, current_price: float, atr: float, whale_action: str = None):
        coin_config = await self.get_coin_config(symbol)
        capital = coin_config.allocated_capital if coin_config else 100.0
        timeframe = coin_config.timeframe if coin_config else "15m"
        
        # جلب بيانات الشموع للتحليل الفني
        ohlcv_df = await self.get_candlestick_data(symbol, timeframe)
        
        # تطبيق المؤشرات الفنية
        ohlcv_df = self.strategies.apply_technical_indicators(ohlcv_df)

        regime = self.macro.get_market_regime()
        fng = self.macro.get_fear_and_greed()
        confidence = 50.0  
        signal = "HOLD"

        # 1. تحليل الماكرو
        if regime == "RISK_OFF": confidence -= 20.0  
        elif regime == "RISK_ON": confidence += 20.0  

        if fng < 25: confidence += 15.0
        elif fng > 75: confidence -= 15.0

        # 2. تحليل الحيتان
        if whale_action == "BUY": confidence += 25.0
        elif whale_action == "SELL": confidence -= 25.0

        # 3. التحليل الفني (باستخدام الاستراتيجيات الجديدة)
        if not ohlcv_df.empty:
            if self.strategies.check_buy_signal(ohlcv_df):
                confidence += 20.0
            elif self.strategies.check_sell_signal(ohlcv_df):
                confidence -= 20.0
            
            # تحديث ATR بناءً على البيانات المحسوبة
            atr = self.strategies.get_atr(ohlcv_df)

        # تحديد الإشارة بناءً على الثقة
        if confidence >= 75.0: signal = "BUY"
        elif confidence <= 25.0: signal = "SELL"

        # هل الصفقة تظهر للمستخدم أم للتدريب فقط؟
        is_visible = confidence >= 85.0 or confidence <= 15.0

        if signal != "HOLD":
            trade = await self.execute_paper_trade(symbol, signal, current_price, atr, capital, confidence, is_visible)
            
            # إرسال إشعار إذا كانت الصفقة "ظاهرة"
            if is_visible and trade and self.bot and self.chat_id != 0:
                msg = (f"🤖 *قرار الذكاء الاصطناعي (صفقة حية)*\n\n"
                       f"العملة: {symbol}\n"
                       f"القرار: {signal}\n"
                       f"الإطار الزمني: {timeframe}\n"
                       f"السعر: ${current_price:,.{self.risk_manager.get_dynamic_precision(current_price)}f}\n"
                       f"الثقة: {confidence:.2f}%\n"
                       f"الهدف: ${trade.take_profit:,.{self.risk_manager.get_dynamic_precision(trade.take_profit)}f}\n"
                       f"الوقف: ${trade.stop_loss:,.{self.risk_manager.get_dynamic_precision(trade.stop_loss)}f}\n"
                       f"--- النظام يراقب الصفقة الآن وسيرسل تقريراً عند الإغلاق ---")
                try:
                    await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')
                except Exception as e:
                    print(f"خطأ في إرسال رسالة التليجرام: {e}")
                    
        return signal, confidence

    async def execute_paper_trade(self, symbol: str, side: str, entry_price: float, atr: float, capital: float, confidence: float, is_visible: bool):
        # استخدام win_rate و risk_reward_ratio من التعلم الذاتي أو قيم افتراضية
        # TODO: يجب جلب هذه القيم من قاعدة البيانات بناءً على أداء AI السابق
        win_rate = 0.55 # قيمة افتراضية
        risk_reward_ratio = 1.5 # قيمة افتراضية

        pos_size = self.risk_manager.calculate_kelly_position(capital, win_rate, risk_reward_ratio)
        
        # تحديد الدقة بناءً على سعر الدخول
        self.risk_manager.precision = self.risk_manager.get_dynamic_precision(entry_price)
        
        sl, tp = self.risk_manager.calculate_sl_tp(entry_price, atr, side)
        
        if not self.risk_manager.check_fee_violation(entry_price, tp): return None

        async with AsyncSessionLocal() as session:
            new_trade = PaperTrade(
                symbol=symbol, side=side, entry_price=entry_price,
                position_size=pos_size, stop_loss=sl, take_profit=tp, 
                confidence=confidence, is_visible=is_visible
            )
            session.add(new_trade)
            await session.commit()
            await session.refresh(new_trade)
        return new_trade

    async def close(self):
        await self.exchange.close()

