from config import Config
from logger import setup_logger

logger = setup_logger("RiskManager")

class RiskManager:
    @staticmethod
    def calculate_position_size(capital: float, risk_level: str, entry: float, sl: float) -> float:
        """
        حساب حجم المركز الديناميكي (Lot Size / Position Sizing) بناءً على:
        1. حجم رأس المال الحالي للحساب.
        2. مستوى المخاطرة المحدد للمستخدم (CONSERVATIVE, MODERATE, AGGRESSIVE).
        3. المسافة السعرية الفعالة حتى أمر وقف الخسارة.
        """
        try:
            # 1. جلب النسبة المئوية للمخاطرة من الإعدادات الافتراضية
            risk_fraction = Config.RISK_LEVELS.get(risk_level, 0.01) # الافتراضي 1% في حال عدم التطابق
            
            # 2. حساب المبلغ المالي الفعلي المعرض للمخاطرة (Cash at Risk)
            cash_at_risk = capital * risk_fraction
            
            # 3. حساب المسافة السعرية المطلقة لوقف الخسارة (Price Risk)
            price_risk = abs(entry - sl)
            
            # حماية رياضية من الانقسام على صفر في حال حدوث خطأ في البيانات السعرية
            if price_risk == 0:
                logger.error("❌ [إدارة المخاطر] فشل حساب حجم المركز لأن المسافة لوقف الخسارة تساوي صفر!")
                return 0.0
                
            # 4. حساب الحجم النهائي للمركز (عدد الوحدات أو العملات المراد دخول الصفقة بها)
            position_size = cash_at_risk / price_risk
            
            logger.info(
                f"🛡️ [إدارة المخاطر] حسابات المخاطرة للزوج: رأس المال = {capital}$, "
                f"المستوى = {risk_level} ({risk_fraction*100}%), "
                f"المبلغ المعرض للمخاطرة = {cash_at_risk:.2f}$, "
                f"الحجم المقترح للمركز = {position_size:.6f}"
            )
            
            return float(position_size)
            
        except Exception as e:
            logger.error(f"خطأ غير متوقع داخل محرك إدارة المخاطر: {str(e)}")
            return 0.0

    @staticmethod
    def enforce_cooldown(last_signal_time, current_time) -> bool:
        """
        التحقق من انقضاء مدة التهدئة الإلزامية (Cooldown Logic) بين الإشارات المتتالية
        لمنع النظام من الدخول في صفقات متكررة مفرطة أثناء تذبذبات السوق الحادة (Overtrading Prevention).
        """
        if not last_signal_time:
            return True # لا توجد صفقات سابقة، مسموح بالتداول فوراً
            
        time_passed = (current_time - last_signal_time).total_seconds() / 60.0
        if time_passed < Config.RISK_FREE_COOLDOWN_MINUTES:
            logger.info(f"⏳ [إدارة المخاطر] تم تفعيل وضع التهدئة. الوقت المنقضي {time_passed:.1f} دقيقة أقل من الحد المطلوب {Config.RISK_FREE_COOLDOWN_MINUTES} دقيقة.")
            return False # حظر الصفقة بسبب وقوعها في فترة التهدئة
            
        return True # انقضت فترة التهدئة، مسموح بالتداول
