import os
from dotenv import load_dotenv

# تحميل ملف .env إذا كان موجوداً
load_dotenv()

# 1. التوكن الخاص بك
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8129443153:AAEPrpxbplE_Tf7fkR4eCueljc0DVLQcYxQ")

# 2. قاعدة البيانات
RAW_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-west-1.pooler.supabase.com:6543/postgres")

# تحويل الرابط ليدعم asyncpg مع فرض SSL
if "postgresql+asyncpg://" not in RAW_DATABASE_URL:
    DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "?" not in DATABASE_URL:
        DATABASE_URL += "?ssl=require"
    elif "ssl=require" not in DATABASE_URL:
        DATABASE_URL += "&ssl=require"
else:
    DATABASE_URL = RAW_DATABASE_URL

# 3. بقية الإعدادات
ADMIN_ID = int(os.getenv("ADMIN_ID", 1503808643))
DEFAULT_CAPITAL = float(os.getenv("DEFAULT_CAPITAL", 10.0))
TRADE_FEE = float(os.getenv("TRADE_FEE", 0.001))
BINANCE_WS_URL = "wss://stream.binance.com:9443"

# Redis Configuration (Redis Cloud)
REDIS_HOST = os.getenv("REDIS_HOST", "deft-wonderful-receipt-35081.db.redis.io")
REDIS_PORT = int(os.getenv("REDIS_PORT", 18244))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "m4SWGkLu0SogNfODh1sIaHSJvpAICVVM")
