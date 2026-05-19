# core/ai_engine.py
import pandas as pd
import xgboost as xgb
from database import AsyncSessionLocal, PaperTrade
from core.risk_manager import RiskManager

class AIEngine:
    def __init__(self):
        self.risk_manager = RiskManager()
        # تهيئة نموذج XGBoost خفيف للعمل على خوادم Render
        self.model = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1)
        self.is_trained = False

    def analyze_market(self, symbol: str, df: pd.DataFrame, whale_signal: bool = False):
        """
        تحليل بيانات السوق وإصدار إشارة تداول
        (هنا يتم دمج المؤشرات الفنية مع إشارات الحيتان)
        """
        # في بيئة العمل الحقيقية، سيقوم النموذج بتحليل الـ DataFrame
        # للتبسيط في هذه المرحلة الهيكلية، سنضع منطقاً يعتمد على الحيتان والزخم
        
        confidence = 0.0
        signal = "HOLD"

        # إذا كان هناك حوت يشتري، نرفع نسبة الثقة
        if whale_signal:
            confidence += 40.0
            
        # تحليل بسيط للزخم (كمثال هيكلي للذكاء الاصطناعي)
        if len(df) > 0:
            current_price = df['close'].iloc[-1]
            sma_20 = df['close'].rolling(window=20).mean().iloc[-1]
            
            if current_price > sma_20:
                signal = "BUY"
                confidence += 35.0
            elif current_price < sma_20:
                signal = "SELL"
                confidence += 35.0

        # إذا تجاوزت الثقة 70%، نعتمد الإشارة
        if confidence >= 70.0:
            return signal, confidence
        return "HOLD", confidence

    async def execute_paper_trade(self, symbol: str, side: str, entry_price: float, atr: float, capital: float):
        """تنفيذ صفقة وهمية وحفظها في قاعدة البيانات للتعلم"""
        # 1. حساب حجم الصفقة (بافتراض نسبة نجاح تاريخية 55%)
        pos_size = self.risk_manager.calculate_kelly_position(capital, win_rate=0.55, risk_reward_ratio=1.5)
        
        # 2. حساب الأهداف
        sl, tp = self.risk_manager.calculate_sl_tp(entry_price, atr, side)
        
        # 3. التأكد من تغطية العمولات
        if not self.risk_manager.check_fee_violation(entry_price, tp):
            print(f"⚠️ تم إلغاء صفقة {symbol} لأنها لا تغطي العمولات.")
            return None

        # 4. حفظ الصفقة في قاعدة البيانات (PostgreSQL)
        async with AsyncSessionLocal() as session:
            new_trade = PaperTrade(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                position_size=pos_size,
                stop_loss=sl,
                take_profit=tp,
                confidence=85.0 # مثال
            )
            session.add(new_trade)
            await session.commit()
            
        print(f"✅ تم فتح صفقة وهمية: {side} {symbol} | الحجم: ${pos_size} | الهدف: {tp}")
        return new_trade
