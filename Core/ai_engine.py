import pandas as pd
import ccxt.async_support as ccxt
from database import AsyncSessionLocal, PaperTrade, TrackedCoin, UserConfig
from sqlalchemy import select
from Core.risk_manager import RiskManager
from macro_data import MacroAnalyzer
from strategies import SpotStrategies
from datetime import datetime
import asyncio
import json

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.risk_manager = RiskManager()
        self.macro = MacroAnalyzer()
        self.strategies = SpotStrategies()
        self.bot = bot
        self.chat_id = chat_id
        self.exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

    async def get_coin_config(self, symbol: str):
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin).where(TrackedCoin.symbol == symbol))
            return result.scalars().first()

    async def analyze_and_trade(self, symbol: str, whale_action: str = None):
        coin_config = await self.get_coin_config(symbol)
        capital = coin_config.allocated_capital if coin_config else 20.0
        tf = coin_config.timeframe if coin_config else "15m"
        
        try:
            await asyncio.sleep(0.5) 
            
            ohlcv = await self.exchange.fetch_ohlcv(symbol, tf, limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_price = float(df['close'].iloc[-1])
            
            df = self.strategies.apply_technical_indicators(df)
            atr = self.strategies.get_atr(df)
            
            # حساب الثقة بناءً على الاستراتيجيات المطورة
            regime = self.macro.get_market_regime()
            confidence = self.strategies.calculate_confidence(df, whale_action, regime)
            
            # أخذ لقطة فنية للمؤشرات وقت الدخول للتقرير
            last_row = df.iloc[-1]
            snapshot = {
                "RSI": round(last_row.get("RSI", 0), 2),
                "MACD": "UP" if last_row.get("MACD", 0) > last_row.get("MACD_SIGNAL", 0) else "DOWN",
                "Regime": regime,
                "Whale": whale_action
            }

            print(f"📊 [ANALYSIS] {symbol} | Confidence: {confidence}%")

            # أي صفقة فوق 50% تفتح كـ "تدريب مخفي"
            # فوق 85% تعتبر "نخبة"
            if confidence >= 50.0:
                await self.execute_open_trade(symbol, "BUY", current_price, atr, capital, confidence, snapshot)
            
            return "BUY" if confidence >= 50.0 else "HOLD", confidence
        except Exception as e:
            print(f"❌ خطأ في تحليل {symbol}: {e}")
            return "HOLD", 0.0

    async def execute_open_trade(self, symbol, side, price, atr, capital, confidence, snapshot):
        async with AsyncSessionLocal() as session:
            # منع تكرار نفس العملة وهي مفتوحة
            check = await session.execute(select(PaperTrade).where((PaperTrade.symbol == symbol) & (PaperTrade.status == "OPEN")))
            if check.scalars().first(): return

            sl, tp = self.risk_manager.calculate_sl_tp(price, atr, side)
            amount = self.risk_manager.calculate_kelly_position(capital, 0.6, 1.5)
            
            # تصنيف الصفقة
            is_elite_trade = confidence >= 85.0

            try:
                new_trade = PaperTrade(
                    symbol=symbol,
                    type=side,
                    entry_price=price,
                    stop_loss=sl,
                    take_profit=tp,
                    amount=amount,
                    status="OPEN",
                    confidence=confidence,
                    is_elite=is_elite_trade,
                    technical_snapshot=json.dumps(snapshot),
                    timestamp=datetime.utcnow()
                )
                session.add(new_trade)
                await session.commit()
                
                # إشعار صفقات النخبة (فقط إذا كانت مفعلة والثقة عالية)
                if is_elite_trade:
                    user_cfg = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
                    cfg = user_cfg.scalars().first()
                    
                    if cfg and cfg.elite_enabled and self.bot:
                        msg = (f"🌟 *صفقة نخبة جديدة (Elite Trade)*\n\n"
                               f"🪙 العملة: #{symbol}\n"
                               f"🔥 الثقة: {confidence}%\n"
                               f"💰 السعر: `{price}`\n"
                               f"🎯 الهدف: `{tp}`\n"
                               f"🛡️ الوقف: `{sl}`\n\n"
                               f"📝 _تم تسجيل الحالة الفنية للتعلم المستقبلي._")
                        await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
                
                print(f"✅ [SUCCESS] تم تسجيل {'صفقة نخبة' if is_elite_trade else 'صفقة تدريب'} لـ {symbol}")
            
            except Exception as e:
                print(f"❌ [DB ERROR] فشل حفظ الصفقة: {e}")
                await session.rollback()
