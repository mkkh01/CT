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
        # تم ضبط الإعدادات للتعامل مع Binance Spot بذكاء
        self.exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

    async def analyze_and_trade(self, symbol: str, whale_action: str = None):
        # 1. جلب حالة المحرك من قاعدة البيانات
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
            cfg = res.scalars().first()
            
            # إذا كان النظام بالكامل "متوقف" (التعلم الخفي متوقف)، نتوقف هنا
            if not cfg or not cfg.is_active:
                return "OFF", 0.0

        coin_config = await self.get_coin_config(symbol)
        capital = coin_config.allocated_capital if coin_config else 20.0
        tf = coin_config.timeframe if coin_config else "15m"
        
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, tf, limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_price = float(df['close'].iloc[-1])
            
            df = self.strategies.apply_technical_indicators(df)
            atr = self.strategies.get_atr(df)
            
            regime = self.macro.get_market_regime()
            confidence = self.strategies.calculate_confidence(df, whale_action, regime)
            
            # لقطة فنية دقيقة لتقارير "الساعة 1 و 5" التي طلبتها
            snapshot = {
                "RSI": round(df.iloc[-1].get("RSI", 0), 2),
                "Regime": regime,
                "Trend": "Bullish" if df['close'].iloc[-1] > df['close'].rolling(20).mean().iloc[-1] else "Bearish"
            }

            # تنفيذ الصفقة برمجياً (سواء للتدريب أو للتداول الحقيقي)
            # خفضنا حد "النخبة" لـ 75% كما اتفقنا لكي يعطيك صفقات أكثر للتداول
            if confidence >= 50.0:
                await self.execute_open_trade(symbol, "BUY", current_price, atr, capital, confidence, snapshot, cfg)
            
            return "BUY" if confidence >= 50.0 else "HOLD", confidence
            
        except Exception as e:
            print(f"❌ خطأ تحليل {symbol}: {e}")
            return "HOLD", 0.0

    async def execute_open_trade(self, symbol, side, price, atr, capital, confidence, snapshot, cfg):
        async with AsyncSessionLocal() as session:
            # منع التكرار
            check = await session.execute(select(PaperTrade).where((PaperTrade.symbol == symbol) & (PaperTrade.status == "OPEN")))
            if check.scalars().first(): return

            sl, tp = self.risk_manager.calculate_sl_tp(price, atr, side)
            amount = self.risk_manager.calculate_kelly_position(capital, 0.6, 1.5)
            
            # --- المنطق الجديد للفصل ---
            # تعتبر صفقة نخبة (مضمونة) إذا تجاوزت 75%
            is_elite_trade = confidence >= 75.0 

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
                
                # إرسال الإشعار فقط إذا كانت "إشارات النخبة" مفعلة وكانت الصفقة قوية
                if is_elite_trade and cfg.elite_enabled:
                    if self.bot:
                        msg = (f"🌟 *إشارة تداول مضمونة*\n"
                               f"━━━━━━━━━━━━━━\n"
                               f"🪙 العملة: #{symbol}\n"
                               f"📈 نوع الصفقة: {side}\n"
                               f"🔥 درجة الثقة: {confidence}%\n\n"
                               f"💰 الدخول: `{price}`\n"
                               f"🎯 الهدف: `{tp}`\n"
                               f"🛡️ الوقف: `{sl}`\n"
                               f"━━━━━━━━━━━━━━\n"
                               f"💡 _افتح الصفقة يدوياً الآن._")
                        await self.bot.send_message(self.chat_id, msg, parse_mode='Markdown')
                
                print(f"✅ تم تسجيل {'نخبة' if is_elite_trade else 'تدريب'} لـ {symbol}")
            
            except Exception as e:
                print(f"❌ خطأ حفظ: {e}")
                await session.rollback()
