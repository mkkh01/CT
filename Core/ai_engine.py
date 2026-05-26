import pandas as pd
import ccxt.async_support as ccxt
from database import AsyncSessionLocal, PaperTrade, TrackedCoin
from sqlalchemy import select
from Core.risk_manager import RiskManager
from macro_data import MacroAnalyzer
from strategies import SpotStrategies
from datetime import datetime
import asyncio

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.risk_manager = RiskManager()
        self.macro = MacroAnalyzer()
        self.strategies = SpotStrategies()
        self.bot = bot
        self.chat_id = chat_id
        # تم تفعيل تمكين معدل الطلبات للمساعدة في تجنب الحظر
        self.exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

    async def get_coin_config(self, symbol: str):
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol))
            return result.scalars().first()

    async def analyze_and_trade(self, symbol: str, whale_action: str = None):
        coin_config = await self.get_coin_config(symbol)
        capital = coin_config.allocated_capital if coin_config else 20.0
        tf = coin_config.timeframe if coin_config else "5m"
        
        try:
            # إضافة تأخير بسيط قبل الطلب لتقليل الضغط على API بين العملات
            await asyncio.sleep(0.5) 
            
            ohlcv = await self.exchange.fetch_ohlcv(symbol, tf, limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_price = float(df['close'].iloc[-1])
            
            df = self.strategies.apply_technical_indicators(df)
            atr = self.strategies.get_atr(df)
            
            confidence = 50.0
            if self.macro.get_market_regime() == "RISK_ON": confidence += 10
            if self.strategies.check_buy_signal(df): confidence += 20
            if whale_action == "BUY": confidence += 25
            
            print(f"📊 [ANALYSIS] {symbol} | Confidence: {confidence}%")

            signal = "HOLD"
            # رفعنا حد الشراء قليلاً لزيادة الجودة
            if confidence >= 60.0: signal = "BUY" 
            elif confidence <= 40.0: signal = "SELL"

            if signal != "HOLD":
                await self.execute_open_trade(symbol, signal, current_price, atr, capital, confidence)
            
            return signal, confidence
        except Exception as e:
            print(f"❌ خطأ في تحليل {symbol}: {e}")
            return "HOLD", 50.0

    async def execute_open_trade(self, symbol, side, price, atr, capital, confidence):
        async with AsyncSessionLocal() as session:
            # منع التكرار في قاعدة البيانات
            check = await session.execute(select(PaperTrade).where((PaperTrade.symbol == symbol) & (PaperTrade.status == "OPEN")))
            if check.scalars().first(): return

            sl, tp = self.risk_manager.calculate_sl_tp(price, atr, side)
            amount = self.risk_manager.calculate_kelly_position(capital, 0.6, 1.5)

            try:
                new_trade = PaperTrade(
                    symbol=symbol,
                    type=side,
                    entry_price=price,
                    stop_loss=sl,
                    take_profit=tp,
                    amount=amount,
                    status="OPEN",
                    timestamp=datetime.utcnow()
                )
                session.add(new_trade)
                await session.commit()
                
                # --- نظام الإشعارات الذكي (التدريب الصامت) ---
                # سيتم إرسال إشعار للتيليجرام فقط إذا كانت الثقة >= 85% (الصفقات الخاصة)
                if confidence >= 85.0:
                    msg = (f"🌟 *فرصة تداول خاصة (ثقة عالية)!*\\n\\n"
                           f"العملة: {symbol}\\n"
                           f"النوع: {side}\\n"
                           f"الثقة: {confidence}%\\n"
                           f"السعر: {price}\\n"
                           f"الهدف: {tp}\\n"
                           f"الوقف: {sl}")
                    if self.bot: 
                        await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
                
                # الصفقات العادية تسجل فقط في السجلات للتقرير لاحقاً
                print(f"✅ [SUCCESS] تم تسجيل صفقة {symbol} (تدريب صامت) بنجاح.")
            
            except Exception as e:
                print(f"❌ [DB ERROR] فشل حفظ الصفقة: {e}")
                await session.rollback()
