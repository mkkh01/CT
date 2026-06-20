# config.py

import os
import logging
import sys

# 1. التوكن الخاص بك
TELEGRAM_TOKEN = "8935169680:AAEPcVnGY58CZUmggvNZuGJrvE-FE9IxrxA"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-proj-...") # سيتم جلبها من إعدادات Render

# 2. الرابط الجديد من خانة Transaction pooler (الذي يدعم IPv4)
# ملاحظة: تم استخدام المنفذ 6543 واسم المستخدم المدمج كما يظهر في صورتك
RAW_DATABASE_URL = "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"

# تحويل الرابط ليدعم asyncpg مع فرض SSL
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1) + "?ssl=require"

# 3. بقية الإعدادات
ADMIN_ID = 1503808643
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001
BINANCE_WS_URL = "wss://stream.binance.com:9443"

# 4. إعدادات Redis (من الصورة المزودة)
REDIS_HOST = "moon-close-reaction-79072.db.redis.io" # تم التأكد من العنوان الصحيح
REDIS_PORT = 10184
REDIS_PASS = "OsYazrMladbKz5s1W2p4bbzv4NDNwGHy" # تم تحديث كلمة المرور بدقة
REDIS_SSL = True # تم التثبيت على True لضمان استخدام بروتوكول rediss المشفر لـ Redis Cloud

# 5. إعدادات التسجيل (Logging)
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('trading_bot.log')
        ]
    )
    # تقليل ضجيج المكتبات الخارجية
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.INFO)
    logging.getLogger('websockets').setLevel(logging.INFO)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
