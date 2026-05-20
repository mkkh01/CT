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
        """جلب بيانات الشموع (candlestick data) من Binance بأمان"""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"❌ [AI ENGINE] خطأ في جلب بيانات الشموع لـ {symbol}: {e}")
            return pd.DataFrame()

    async def analyze_and_trade(self, symbol: str, current_price: float, atr: float, whale_action: str = None):
        coin_config = await self.get_coin_config(symbol)
        capital = coin_config.allocated_capital if coin_config else 100.0
        timeframe = coin_config.timeframe if coin_config else "15m"
        
        print(f"🔍 [AI ENGINE] ⚡ بدء جولة تحليل ذكية للعملة {symbol} | الإطار: {timeframe} | السعر: {current_price}")
        
        # 1. جلب بيانات الشموع وتأمين الحسابات الفنية
        ohlcv_df = await self.get_candlestick_data(symbol, timeframe)
        
        if ohlcv_df.empty:
            print(f"⚠️ [AI ENGINE] تم إلغاء التحليل لـ {symbol} بسبب فشل جلب الشموع من بينانس.")
            return "HOLD", 50.0

        # تطبيق المؤشرات الفنية وحساب الـ ATR فوراً لتأمين الـ Risk Manager
        ohlcv_df = self.strategies.apply_technical_indicators(ohlcv_df)
        atr = self.strategies.get_atr(ohlcv_df)

        regime = self.macro.get_market_regime()
        fng = self.macro.get_fear_and_greed()
        
        # نقطة الارتكاز لعداد الثقة
        confidence = 50.0  
        signal = "HOLD"

        # 2. تحليل معطيات الماكرو (أوزان مرنة وموزونة ديناميكياً)
        if regime == "RISK_OFF": 
            confidence -= 10.0  
            print("📉 [AI ENGINE] بيئة الماكرو RISK_OFF: خفض الثقة بمقدار -10")
        elif regime == "RISK_ON": 
            confidence += 10.0  
            print("📈 [AI ENGINE] بيئة الماكرو RISK_ON: رفع الثقة بمقدار +10")

        if fng < 25: 
            confidence += 10.0  # منطقة ارتداد تاريخية فرصة شراء
        elif fng > 75: 
            confidence -= 10.0  # منطقة تشبع طمع تاريخية مخاطرة عالية

        # 3. تحليل رادار الحيتان الفوري (وزن حاسم)
        if whale_action == "BUY": 
            confidence += 25.0
            print(f"🐳 [AI ENGINE] رصد تدفق حيتان إيجابي (BUY) لـ {symbol}: رفع الثقة بمقدار +25")
        elif whale_action == "SELL": 
            confidence -= 25.0
            print(f"🐳 [AI ENGINE] رصد تدفق حيتان سلبي (SELL) لـ {symbol}: خفض الثقة بمقدار -25")

        # 4. دمج إشارات التحليل الفني (الاستراتيجيات)
        if self.strategies.check_buy_signal(ohlcv_df):
            confidence += 20.0
            print(f"📊 [AI ENGINE] إشارة فنية صاعدة (BUY SIGNAL) نشطة لـ {symbol}: (+20 ثقة)")
        elif self.strategies.check_sell_signal(ohlcv_df):
            confidence -= 20.0
            print(f"📊 [AI ENGINE] إشارة فنية هابطة (SELL SIGNAL) نشطة لـ {symbol}: (-20 ثقة)")

        print(f"📊 [AI ENGINE] الحصيلة النهائية لعداد الثقة لـ {symbol} هي: ({confidence:.2f}%)")

        # اتخاذ القرار بناءً على عتبات رقمية منطقية وقابلة للتحقيق
        if confidence >= 65.0: 
            signal = "BUY"
        elif confidence <= 35.0: 
            signal = "SELL"

        # تحديد وضوح الصفقة (تظهر للمستخدم أم مخفية للتدريب الذاتي فقط)
        is_visible = confidence >= 80.0 or confidence <= 20.0

        if signal != "HOLD":
            print(f"🚀 [AI ENGINE] إشارة نشطة مكتشفة ({signal})! تمرير الأمر فوراً للتنفيذ والحفظ...")
            trade = await self.execute_paper_trade(symbol, signal, current_price, atr, capital, confidence, is_visible)
            
            if trade:
                print(f"✅ [AI ENGINE] تم بنجاح حفظ الصفقة في قاعدة البيانات المحدثة V2 برقم: {trade.id} | الحالة: {trade.status}")
                
                # إرسال إشعار فوري للتليجرام إذا كانت الصفقة تستحق الظهور للمستخدم
                if is_visible and self.bot and self.chat_id and self.chat_id != 0:
                    precision = self.risk_manager.get_dynamic_precision(current_price)
                    msg = (f"🤖 *قرار الذكاء الاصطناعي المتقدم (V3)*\n\n"
                           f"🪙 العملة: {symbol}\n"
                           f"🎯 القرار الإستراتيجي: {signal}\n"
                           f"⏱️ الإطار الزمني: {timeframe}\n"
                           f"💵 سعر الدخول الحالي: ${current_price:,.{precision}f}\n"
                           f"🧠 نسبة ثقة المحرك: {confidence:.2f}%\n"
                           f"🟢 الهدف (TP): ${trade.take_profit:,.{precision}f}\n"
                           f"🔴 الوقف (SL): ${trade.stop_loss:,.{precision}f}\n"
                           f"ℹ️ نوع الصفقة: {'شفافة/علنية' if is_visible else 'خفية/تدريبية'}\n\n"
                           f"--- النظام يراقب حركات الشموع الآن وسيقوم بتحديث سجلات التعلم عند الإغلاق ---")
                    try:
                        await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')
                        print(f"📱 [AI ENGINE] تم إرسال إشعار الصفقة بنجاح إلى التليجرام.")
                    except Exception as e:
                        print(f"❌ [AI ENGINE] فشل إرسال رسالة التليجرام: {e}")
            else:
                print(f"❌ [AI ENGINE] تم إلغاء الصفقة في مرحلة إدارة المخاطر (تأكد من إعدادات السيولة للعملة).")
        else:
            print(f"⏸️ [AI ENGINE] النتيجة تعادل (HOLD). تم صرف النظر عن الصفقة لعدم كفاية الزخم الاستراتيجي.")
                    
        return signal, confidence

    async def execute_paper_trade(self, symbol: str, side: str, entry_price: float, atr: float, capital: float, confidence: float, is_visible: bool):
        win_rate = 0.55 # قيمة افتراضية للتدريب الأول
        risk_reward_ratio = 1.5 

        # حساب حجم المركز مستنداً لمدير المخاطر المطور والمناسب للمبالغ الصغيرة
        pos_size = self.risk_manager.calculate_kelly_position(capital, win_rate, risk_reward_ratio)
        
        # حساب مستويات الوقف والهدف بدقة ديناميكية
        sl, tp = self.risk_manager.calculate_sl_tp(entry_price, atr, side)
        
        # التحقق من الرسوم بمرونة
        if not self.risk_manager.check_fee_violation(entry_price, tp): 
            return None

        try:
            async with AsyncSessionLocal() as session:
                new_trade = PaperTrade(
                    symbol=symbol, side=side, entry_price=entry_price,
                    position_size=pos_size, stop_loss=sl, take_profit=tp, 
                    confidence=confidence, is_visible=is_visible,
                    status="OPEN"
                )
                session.add(new_trade)
                await session.commit()
                await session.refresh(new_trade)
            return new_trade
        except Exception as db_err:
            print(f"🚨 [AI ENGINE] انهارت عملية حفظ الصفقة في قاعدة البيانات بسبب تعارض أو خطأ هيكلي: {db_err}")
            return None

    async def close(self):
        await self.exchange.close()
