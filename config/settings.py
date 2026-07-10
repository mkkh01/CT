import sys
import os
from pathlib import Path

# إضافة المسار الرئيسي للبحث عن config.py
sys.path.append(str(Path(__file__).parent.parent))

try:
    import config
except ImportError:
    # في حالة فشل الاستيراد، نحاول استيراده كملف محلي
    import config as config

# نسخ الإعدادات من config.py إلى settings.py للحفاظ على التوافق مع بقية المشروع
DEBUG_MODE = config.DEBUG_MODE
TELEGRAM_TOKEN = config.TELEGRAM_TOKEN
ADMIN_ID = config.ADMIN_ID
RAW_DATABASE_URL = config.RAW_DATABASE_URL
DATABASE_URL = config.DATABASE_URL
REDIS_HOST = config.REDIS_HOST
REDIS_PORT = config.REDIS_PORT
REDIS_PASSWORD = config.REDIS_PASSWORD

# إعدادات إضافية قد تكون مطلوبة من قبل أجزاء أخرى من النظام
PORT = config.PORT
WEBHOOK_URL = config.WEBHOOK_URL
BINANCE_API_KEY = config.BINANCE_API_KEY
BINANCE_API_SECRET = config.BINANCE_API_SECRET
BINANCE_WS_URL = config.BINANCE_WS_URL
DEFAULT_CAPITAL = config.DEFAULT_CAPITAL
TRADE_FEE = config.TRADE_FEE
HTF_MODE = config.HTF_MODE

# الحفاظ على المتغيرات القديمة التي قد تستخدمها أجزاء أخرى
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}"
LOG_LEVEL = "INFO"
SIGNAL_MODE = True
LIVE_MODE = False
SIMULATION_MODE = False
SYMBOL = "XAUUSD"
CAPITAL = DEFAULT_CAPITAL
RISK_PER_TRADE = 1.0
TIMEFRAME = "M15"

def validate_config():
    return config.validate_config()
