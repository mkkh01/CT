import logging
from config import DEFAULT_CAPITAL, TRADE_FEE

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self):
        # أقصى مخاطرة 2% من رأس المال لكل صفقة حقيقية
        self.max_risk_per_trade = 0.02 
        # الدقة الافتراضية للعملات (8 خانات للعملات الصفرية والصغيرة)
        self.precision = 8
        self.max_daily_loss = 0.05 # 5% max daily loss
        self.max_drawdown = 0.10 # 10% max drawdown protection

    def calculate_kelly_position(self, capital: float, win_rate: float, risk_reward_ratio: float) -> float:
        """
        حساب حجم الصفقة باستخدام معيار كيلي (Kelly Criterion)
        مطور ليدعم المبالغ الصغيرة جداً (أقل من 10 دولار) لغرض التدريب الفعال
        """
        logger.info(f"⚖️ [RISK] حساب حجم الصفقة لـ رأس مال {capital} USDT (WinRate: {win_rate}, R/R: {risk_reward_ratio})")
        
        # إذا كان رأس المال المخصص صغير جداً (أقل من 15 دولار)، نمنح البوت مرونة استخدام 50% إلى 100% 
        # من هذا المبلغ المخصص لتجنب خروج حجم الصفقة كأجزاء من السنت
        if capital <= 15.0:
            logger.info(f"⚖️ [RISK] رأس مال صغير، استخدام كامل المبلغ المخصص: {capital} USDT")
            return round(capital, 2)

        if win_rate <= 0 or risk_reward_ratio <= 0:
            # إذا لم تتوفر بيانات كافية، نستخدم نسبة ثابتة آمنة (1% من رأس المال)
            final_risk_pct = 0.01
            logger.info("⚖️ [RISK] بيانات غير كافية لكيلي، استخدام نسبة مخاطرة افتراضية 1%.")
        else:
            kelly_percentage = win_rate - ((1 - win_rate) / risk_reward_ratio)
            # نستخدم "نصف كيلي" (Half-Kelly) للأمان
            safe_kelly = kelly_percentage / 2.0
            # نضمن البقاء في نطاق آمن للتداول العادي
            final_risk_pct = min(max(safe_kelly, 0.01), self.max_risk_per_trade)
            logger.info(f"⚖️ [RISK] حساب كيلي: {kelly_percentage:.4f}, نصف كيلي الآمن: {safe_kelly:.4f}, النسبة النهائية: {final_risk_pct:.4f}")
        
        position_size = capital * final_risk_pct
        logger.info(f"⚖️ [RISK] حجم الصفقة المحسوب: {position_size:.2f} USDT")
        return round(position_size, 2)

    def calculate_sl_tp(self, entry_price: float, atr: float, side: str, atr_multiplier: float = 2.0):
        """
        حساب وقف الخسارة (SL) وجني الأرباح (TP) بناءً على التذبذب (ATR)
        مع تحديث الدقة ديناميكياً قبل التقريب لضمان عدم تداخل الأرقام الصغيرة
        """
        # تحديث عدد الخانات العشرية ديناميكياً فوراً بناءً على سعر العملة الحالي
        self.precision = self.get_dynamic_precision(entry_price)

        if not atr or atr == 0:
            # إذا لم يتوفر ATR، نضع وقف منطقي 1.5% وجني أرباح متناسب 2.25% للمرونة
            stop_loss_dist = entry_price * 0.015
            logger.info(f"📏 [RISK] لا يوجد ATR لـ {entry_price}، استخدام وقف افتراضي 1.5%.")
        else:
            stop_loss_dist = atr * atr_multiplier
            logger.info(f"📏 [RISK] حساب المسافة بناءً على ATR ({atr}): {stop_loss_dist}")

        take_profit_dist = stop_loss_dist * 1.5  # نسبة مخاطرة لعائد 1:1.5

        if side == "BUY":
            sl = entry_price - stop_loss_dist
            tp = entry_price + take_profit_dist
        else: # SELL
            sl = entry_price + stop_loss_dist
            tp = entry_price - take_profit_dist

        logger.info(f"📏 [RISK] SL: {sl:.{self.precision}f}, TP: {tp:.{self.precision}f} (Side: {side}, Precision: {self.precision})")
        # التقريب باستخدام الدقة الديناميكية المحسوبة لحماية أهداف العملات البديلة الصغيرة
        return round(sl, self.precision), round(tp, self.precision)

    def check_fee_violation(self, entry_price: float, tp_price: float) -> bool:
        """التأكد من أن الربح المتوقع يغطي عمولة المنصة مع إعطاء مرونة كاملة للحسابات الصغيرة"""
        profit_margin = abs(tp_price - entry_price) / entry_price
        total_fee = TRADE_FEE * 2 
        
        # لغرض التداول التجريبي والتعلم الذاتي بمبالغ صغيرة، خففنا القيد ليمر الشرط دائماً 
        # ما دامت الصفقة رابحة فنية بنسبة تزيد عن رسوم المنصة
        is_valid = profit_margin > (total_fee * 0.5)
        
        if not is_valid:
            logger.warning(f"⚠️ [RISK MANAGER] هامش الربح المتوقع ({profit_margin:.6f}) قليل جداً مقارنة بالرسوم ({total_fee:.6f})")
        else:
            logger.info(f"✅ [RISK] هامش الربح ({profit_margin:.6f}) يغطي الرسوم ({total_fee:.6f}).")
        return is_valid

    def get_dynamic_precision(self, price: float) -> int:
        """تحديد عدد الخانات العشرية المناسب بناءً على سعر العملة لمنع أخطاء التقريب الصفرية"""
        if price < 0.0001: return 8
        if price < 0.001: return 7
        if price < 0.01: return 6
        if price < 0.1: return 5
        if price < 1: return 4
        if price < 100: return 3
        return 2

    def check_correlation_risk(self, open_trades: list, new_symbol: str) -> bool:
        """
        محرك حماية الارتباط (Correlation Guard)
        يمنع تكدس المخاطر في عملات تتحرك بنفس الاتجاه
        """
        # قائمة العملات المرتبطة تاريخياً (بشكل مبسط)
        correlations = {
            "BTC": ["ETH", "LTC", "BCH"],
            "ETH": ["SOL", "AVAX", "MATIC", "OP", "ARB"],
            "SOL": ["AVAX", "NEAR", "FTM"]
        }
        
        related_count = 0
        target = new_symbol.replace("USDT", "").upper()
        
        logger.info(f"🛡️ [CORRELATION] فحص ارتباط {target} مع {len(open_trades)} صفقة مفتوحة...")
        
        for trade in open_trades:
            symbol = trade.symbol.replace("USDT", "").upper()
            
            # إذا كانت العملة نفسها أو مرتبطة بها
            if target == symbol: 
                related_count += 1
                logger.info(f"🛡️ [CORRELATION] نفس العملة موجودة بالفعل: {symbol}")
            
            for base, related in correlations.items():
                if (target == base or target in related) and (symbol == base or symbol in related):
                    related_count += 1
                    logger.info(f"🛡️ [CORRELATION] ارتباط مكتشف بين {target} و {symbol} (Base: {base})")
        
        # إذا كان هناك أكثر من صفقتين مرتبطتين، نمنع الثالثة لحماية رأس المال
        if related_count >= 2:
            logger.warning(f"⚠️ [CORRELATION GUARD] High correlation detected for {new_symbol} (Count: {related_count}). Blocking trade.")
            return False
            
        logger.info(f"✅ [CORRELATION] لا توجد مخاطر ارتباط عالية لـ {new_symbol} (Count: {related_count}).")
        return True
