from config import Config
from logger import setup_logger

logger = setup_logger("SignalFilter")

class SignalFilter:
    @staticmethod
    def filter(setup: dict, regime_data: dict) -> bool:
        """
        فحص الصفقة المقترحة عبر فلاتر صارمة متعددة المستويات.
        إرجاع True إذا كانت الصفقة ممتازة وتستحق المخاطرة.
        إرجاع False لإجبار النظام على اتخاذ قرار NO_TRADE.
        """
        try:
            # 1. التحقق الأولي: إذا كان محرك الاستراتيجيات قد رفضها مسبقاً
            if not setup or setup.get("decision") == "NO_TRADE":
                return False
                
            symbol = setup.get("symbol", "UNKNOWN")
            
            # 2. فلتر بيئة السوق الخطرة (Dangerous Regime Filter)
            # رفض التداول نهائياً أثناء الهلع البيعي أو التذبذب العشوائي الحاد (الفرم)
            if regime_data['regime'] in ["PANIC", "CHOPPY"]:
                logger.info(f"🛑 [تصفية] رفض صفقة {symbol} بسبب بيئة سوق خطرة أو غير مستقرة ({regime_data['regime']}).")
                return False
                
            # 3. فلتر التقلب المفرط المتفجر (Extreme Volatility Filter)
            # إذا كان معدل الحركة السعرية اللحظية (ATR%) أعلى من الحد الآمن، يُلغى الدخول
            if regime_data['volatility'] > 7.5:
                logger.info(f"🛑 [تصفية] رفض صفقة {symbol} بسبب تقلبات سعرية مفرطة وغير آمنة ({regime_data['volatility']:.2f}%).")
                return False
                
            # 4. فلتر العائد مقابل المخاطرة الأدنى (Risk-to-Reward Ratio Filter)
            # استبعاد الصفقات التي يكون فيها الهدف قريباً جداً مقارنة بحجم الوقف
            if setup.get("rr", 0) < Config.MIN_RR_RATIO:
                logger.info(f"🛑 [تصفية] رفض صفقة {symbol} لأن معدل العائد مقابل المخاطرة ({setup.get('rr', 0):.2f}) أقل من {Config.MIN_RR_RATIO}.")
                return False
                
            # 5. فلتر الحماية من الاندفاع والامتداد الزائد (Overextended Move Filter)
            # إذا دخل السعر في مناطق تشبع قصوى، يمنع النظام مطاردة السعر (Late Entry)
            rsi_val = regime_data.get("rsi", 50.0)
            if setup['decision'] == "BUY" and rsi_val > 78.0:
                logger.info(f"🛑 [تصفية] رفض الشراء على {symbol} لأن الحركة ممتدة ومفرطة فريالياً (RSI: {rsi_val:.1f}).")
                return False
            elif setup['decision'] == "SELL" and rsi_val < 22.0:
                logger.info(f"🛑 [تصفية] رفض البيع على {symbol} لأن الهبوط ممتد ومفرط فريالياً (RSI: {rsi_val:.1f}).")
                return False
                
            # إذا اجتازت الصفقة كل هذه الفلاتر المعقدة بنجاح، يتم قبولها
            logger.info(f"✅ [تصفية] الصفقة المقترحة على {symbol} اجتازت كافة الفلاتر الصارمة بنجاح.")
            return True
            
        except Exception as e:
            logger.error(f"خطأ غير متوقع داخل محرك الفلترة والتصفية: {str(e)}")
            return False
