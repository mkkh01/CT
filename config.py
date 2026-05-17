import os
from dotenv import load_dotenv

# تحميل ملف .env إن وجد محلياً (لا يؤثر في حال وجود المتغيرات مباشرة)
load_dotenv()

class Config:
    # ------------------------------------------------------------------
    # بيانات الاتصال المباشرة والحقيقية المقدمة من قبلك
    # ------------------------------------------------------------------
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8935169680:AAEo1yzskX1HQHchv_0mt9BvEc1bzZ9fdhU")
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://copilot_user:ynPu1qycw2CrfixLRjkxVG0333NfXPYl@dpg-d84te69kh4rs73denmg0-a.virginia-postgres.render.com/copilot_db_ec8p")
    
    # ⚙️ تم إرفاق الـ Admin ID الحقيقي الخاص بك مباشرة داخل الكود هنا ثابتاً
    ADMIN_ID = int(os.getenv("ADMIN_ID", 1503808643))
    
    # ------------------------------------------------------------------
    # التحقق الصارم من تشغيل النظام لمنع الأخطاء المفاجئة قبل البدء
    # ------------------------------------------------------------------
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN.strip() == "":
        raise ValueError("CRITICAL ERROR: يرجى وضع توكن التلغرام الحقيقي الخاص بك أولاً!")
        
    if not DATABASE_URL or DATABASE_URL.strip() == "":
        raise ValueError("CRITICAL ERROR: رابط قاعدة البيانات غير صحيح أو فارغ!")

    # تصحيح بادئة الرابط في حال كتبت بحروف كابيتال ليتوافق مع مكتبة SQLAlchemy
    if DATABASE_URL.startswith("Postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("Postgresql://", "postgresql://", 1)

    # ------------------------------------------------------------------
    # الإعدادات العالمية وفلاتر الحماية (Global Thresholds)
    # ------------------------------------------------------------------
    DEFAULT_WATCHLIST = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]

    RISK_LEVELS = {
        "CONSERVATIVE": 0.01,  # 1% مخاطرة من الحساب لكل صفقة
        "MODERATE": 0.02,      # 2% مخاطرة من الحساب لكل صفقة
        "AGGRESSIVE": 0.03     # 3% مخاطرة من الحساب لكل صفقة
    }
    
    TIMEFRAMES = {
        "SHORT": "5m",
        "MEDIUM": "15m",
        "LONG": "1h"
    }
    
    DEFAULT_EXCHANGE = "binance"

    MIN_CONFIDENCE_SCORE = 75.0        # الحد الأدنى لقبول قوة الإشارة وصلاحيتها
    RISK_FREE_COOLDOWN_MINUTES = 60    # مدة التهدئة الإلزامية بعد تقلبات السوق المفاجئة
    MIN_RR_RATIO = 1.5                # الحد الأدنى لمعدل العائد مقابل المخاطرة (Risk-to-Reward)
    MAX_OPEN_SHADOW_TRADES = 10        # الحد الأقصى لصفقات الظل الافتراضية المفتوحة في وقت واحد
