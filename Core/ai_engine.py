# Core/ai_engine.py
import pandas as pd
import xgboost as xgb
from database import AsyncSessionLocal, PaperTrade, UserConfig
from sqlalchemy import select

# --- التعديل الدقيق للاستدعاءات ---
# risk_manager في الداخل (نستخدم Core.)
from Core.risk_manager import RiskManager

# macro_data و strategies في الخارج (بدون Core.)
from macro_data import MacroAnalyzer
from strategies import SpotStrategies
# -----------------------------------

class AIEngine:
    def __init__(self, bot=None, chat_id=None):
        self.risk_manager = RiskManager()
        self.macro = MacroAnalyzer()
        self.strategies = SpotStrategies()
        self.model = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1)
        self.bot = bot
        self.chat_id = chat_id

    async def get_user_capital(self):
        """جلب رأس المال من قاعدة البيانات"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(UserConfig).where(UserConfig.telegram_id == self.chat_id))
            config = result.scalars().first()
            return config.paper_capital if config else 1000.0

    async def analyze_and_trade(self, symbol: str, current_price: float, atr: float, whale_action: str = None):
        actual_capital = await self.get_user_capital()
        
        regime = self.macro.get_market_regime()
        fng = self.macro.get_fear_and_greed()
        confidence = 50.0  
        signal = "HOLD"

        if regime == "RISK_OFF": confidence -= 20.0  
        elif regime == "RISK_ON": confidence += 20.0  

        if fng < 25: confidence += 15.0
        elif fng > 75: confidence -= 15.0

        if whale_action == "BUY": confidence += 25.0
        elif whale_action == "SELL": confidence -= 25.0

        if confidence >= 80.0: signal = "BUY"
        elif confidence <= 20.0: signal = "SELL"

        if signal != "HOLD":
            trade = await self.execute_paper_trade(symbol, signal, current_price, atr, actual_capital, confidence)
            
            # إرسال إشعار بالصفقة للتليجرام
            if trade and self.bot and self.chat_id != 0:
                msg = f"🤖 *قرار الذكاء الاصطناعي*\nتم فتح صفقة وهمية للتعلم:\nالعملة: {symbol}\nالقرار: {signal}\nالسعر: ${current_price}\nالثقة: {confidence}%\nالهدف: ${trade.take_profit}\nالوقف: ${trade.stop_loss}"
                try:
                    await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')
                except Exception as e:
                    pass
                    
        return signal, confidence

    async def execute_paper_trade(self, symbol: str, side: str, entry_price: float, atr: float, capital: float, confidence: float):
        pos_size = self.risk_manager.calculate_kelly_position(capital, win_rate=0.55, risk_reward_ratio=1.5)
        sl, tp = self.risk_manager.calculate_sl_tp(entry_price, atr, side)
        
        if not self.risk_manager.check_fee_violation(entry_price, tp): return None

        async with AsyncSessionLocal() as session:
            new_trade = PaperTrade(
                symbol=symbol, side=side, entry_price=entry_price,
                position_size=pos_size, stop_loss=sl, take_profit=tp, confidence=confidence
            )
            session.add(new_trade)
            await session.commit()
        return new_trade
