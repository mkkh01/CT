from config import DEFAULT_CAPITAL, TRADE_FEE

class RiskManager:
    def __init__(self):
        # أقصى مخاطرة 2% من رأس المال لكل صفقة
        self.max_risk_per_trade = 0.02 
        # الدقة الافتراضية للعملات (تتغير حسب العملة)
        self.precision = 8

    def calculate_kelly_position(self, capital: float, win_rate: float, risk_reward_ratio: float) -> float:
        """
        حساب حجم الصفقة باستخدام معيار كيلي (Kelly Criterion)
        المعادلة: Kelly % = W - [(1 - W) / R]
        """
        if win_rate <= 0 or risk_reward_ratio <= 0:
            # إذا لم تتوفر بيانات نجاح كافية، نستخدم نسبة ثابتة آمنة (0.5%)
            final_risk_pct = 0.005
        else:
            kelly_percentage = win_rate - ((1 - win_rate) / risk_reward_ratio)
            # نستخدم "نصف كيلي" (Half-Kelly) للأمان
            safe_kelly = kelly_percentage / 2.0
            # نضمن البقاء بين 0.1% و 2%
            final_risk_pct = min(max(safe_kelly, 0.001), self.max_risk_per_trade)
        
        position_size = capital * final_risk_pct
        return round(position_size, 2)

    def calculate_sl_tp(self, entry_price: float, atr: float, side: str, atr_multiplier: float = 2.0):
        """
        حساب وقف الخسارة (SL) وجني الأرباح (TP) بناءً على التذبذب (ATR)
        مع مراعاة الدقة العالية للعملات الصغيرة
        """
        # إذا لم يتوفر ATR نستخدم نسبة ثابتة (2% كوقف خسارة و 3% كجني أرباح)
        if not atr or atr == 0:
            stop_loss_dist = entry_price * 0.02
        else:
            stop_loss_dist = atr * atr_multiplier

        take_profit_dist = stop_loss_dist * 1.5  # نسبة مخاطرة لعائد 1:1.5

        if side == "BUY":
            sl = entry_price - stop_loss_dist
            tp = entry_price + take_profit_dist
        else: # SELL
            sl = entry_price + stop_loss_dist
            tp = entry_price - take_profit_dist

        # نستخدم 8 خانات عشرية لضمان الدقة في العملات الصفرية
        return round(sl, self.precision), round(tp, self.precision)

    def check_fee_violation(self, entry_price: float, tp_price: float) -> bool:
        """التأكد من أن الربح المتوقع يغطي عمولة المنصة (دخول + خروج)"""
        profit_margin = abs(tp_price - entry_price) / entry_price
        total_fee = TRADE_FEE * 2 
        return profit_margin > total_fee

    def get_dynamic_precision(self, price: float) -> int:
        """تحديد عدد الخانات العشرية المناسب بناءً على سعر العملة"""
        if price < 0.0001: return 8
        if price < 0.01: return 6
        if price < 1: return 4
        return 2
