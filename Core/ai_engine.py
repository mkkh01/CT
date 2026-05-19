# core/ai_engine.py
import pandas as pd
import xgboost as xgb
from database import AsyncSessionLocal, PaperTrade
from core.risk_manager import RiskManager
from core.macro_data import MacroAnalyzer
from core.strategies import SpotStrategies

class AIEngine:
    def __init__(self):
        self.risk_manager = RiskManager()
        self.macro = MacroAnalyzer()
        self.strategies = SpotStrategies()
        # نموذج الذكاء الاصطناعي (جاهز للتدريب على البيانات التاريخية)
        self.model = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1)

    async def analyze_and_trade(self, symbol: str, current_price: float, atr: float, capital: float, whale_action: str = None):
        """
        تحليل شامل للسوق واتخاذ قرار التداول
        """
        # 1. جلب حالة الأسواق العالمية
        regime = self.macro.get_market_regime()
        fng = self.macro.get_fear_and_greed()
        
        confidence = 50.0  # نقطة البداية المحايدة
        signal = "HOLD"

        # 2. تأثير الماكرو (الدولار وناسداك)
        if regime == "RISK_OFF":
            confidence -= 20.0  # بيئة خطرة للكريبتو
        elif regime == "RISK_ON":
            confidence += 20.0  # بيئة ممتازة

        # 3. تأثير مؤشر الخوف والطمع (شراء الخوف وبيع الطمع)
        if fng < 25: # رعب شديد (فرصة تجميع)
            confidence += 15.0
        elif fng > 75: # طمع شديد (خطر تصحيح)
            confidence -= 15.0

        # 4. تأثير الحيتان (السيولة الذكية)
        if whale_action == "BUY":
            confidence += 25.0
        elif whale_action == "SELL":
            confidence -= 25.0

        # 5. اتخاذ القرار النهائي
        if confidence >= 80.0:
            signal = "BUY"
        elif confidence <= 20.0:
            signal = "SELL"

        # 6. التنفيذ إذا كانت هناك إشارة قوية
        if signal != "HOLD":
            await self.execute_paper_trade(symbol, signal, current_price, atr, capital, confidence)
            
        return signal, confidence

    async def execute_paper_trade(self, symbol: str, side: str, entry_price: float, atr: float, capital: float, confidence: float):
        """تنفيذ الصفقة الوهمية وحفظها للتعلم"""
        pos_size = self.risk_manager.calculate_kelly_position(capital, win_rate=0.55, risk_reward_ratio=1.5)
        sl, tp = self.risk_manager.calculate_sl_tp(entry_price, atr, side)
        
        if not self.risk_manager.check_fee_violation(entry_price, tp):
            print(f"⚠️ تجاهل صفقة {symbol}: الهدف لا يغطي عمولة المنصة.")
            return None

        async with AsyncSessionLocal() as session:
            new_trade = PaperTrade(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                position_size=pos_size,
                stop_loss=sl,
                take_profit=tp,
                confidence=confidence
            )
            session.add(new_trade)
            await session.commit()
            
        print(f"✅ [صفقة ذكية] {side} {symbol} | الثقة: {confidence}% | الحجم: ${pos_size} | الهدف: {tp}")
        return new_trade
