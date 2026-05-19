# core/risk_manager.py
from config import DEFAULT_CAPITAL, TRADE_FEE

class RiskManager:
    def __init__(self):
        self.max_risk_per_trade = 0.02  # أقصى مخاطرة 2% من رأس المال

    def calculate_kelly_position(self, capital: float, win_rate: float, risk_reward_ratio: float) -> float:
        """
        حساب حجم الصفقة باستخدام معيار كيلي (Kelly Criterion)
        win_rate: نسبة نجاح النظام (مثلاً 0.55 يعني 55%)
        risk_reward_ratio: نسبة العائد للمخاطرة (مثلاً 2.0)
        """
        if win_rate <= 0 or risk_reward_ratio <= 0:
            return 0.0

        # معادلة كيلي: Kelly % = W - [(1 - W) / R]
        kelly_percentage = win_rate - ((1 - win_rate) / risk_reward_ratio)
        
        # نستخدم "نصف كيلي" (Half-Kelly) لمزيد من الأمان وتقليل التذبذب
        safe_kelly = kelly_percentage / 2.0
        
        # نضمن أن لا نتجاوز الحد الأقصى للمخاطرة (2%)
        final_risk_pct = min(max(safe_kelly, 0.0), self.max_risk_per_trade)
        
        position_size = capital * final_risk_pct
        return round(position_size, 2)

    def calculate_sl_tp(self, entry_price: float, atr: float, side: str, atr_multiplier: float = 2.0):
        """
        حساب وقف الخسارة (SL) وجني الأرباح (TP) بناءً على التذبذب (ATR)
        """
        stop_loss_dist = atr * atr_multiplier
        take_profit_dist = stop_loss_dist * 1.5  # Risk/Reward = 1:1.5 كبداية

        if side == "BUY":
            sl = entry_price - stop_loss_dist
            tp = entry_price + take_profit_dist
        else: # SELL
            sl = entry_price + stop_loss_dist
            tp = entry_price - take_profit_dist

        return round(sl, 4), round(tp, 4)

    def check_fee_violation(self, entry_price: float, tp_price: float) -> bool:
        """التأكد من أن الصفقة تغطي عمولة المنصة وتترك ربحاً صافياً"""
        profit_margin = abs(tp_price - entry_price) / entry_price
        total_fee = TRADE_FEE * 2  # عمولة الدخول والخروج
        return profit_margin > total_fee
