# config.py
import logging

logger = logging.getLogger(__name__)

# --- إعدادات خادم الويب (Render Webserver) ---
PORT = 10000
# ضع هنا الرابط الفعلي لمشروعك على منصة Render
WEBHOOK_URL = "https://crypto-trading-ru2v.onrender.com" 

# --- إعدادات التشغيل ---
DEBUG_MODE = False

# 1. التوكن الخاص بك
TELEGRAM_TOKEN = "8129443153:AAEPrpxbplE_Tf7fkR4eCueljc0DVLQcYxQ"

# Binance API Credentials
BINANCE_API_KEY = ""
BINANCE_API_SECRET = ""

# Decision-Engine configuration object
DECISION_CONFIG = None

# 2. إعدادات قاعدة البيانات (Supabase)
RAW_DATABASE_URL = "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1) + "?ssl=require"

# 3. بقية الإعدادات
ADMIN_ID = 1503808643
HTF_MODE = "SKIP"  # Options: SKIP, CONTINUE_LOW_CONF, FALLBACK
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001
BINANCE_WS_URL = "wss://stream.binance.com:9443"

# 4. إعدادات Redis
REDIS_HOST = "deft-wonderful-receipt-35081.db.redis.io"
REDIS_PORT = 18244
REDIS_PASSWORD = "m4SWGkLu0SogNfODh1sIaHSJvpAICVVM"

# Configuration validation
def validate_config():
    errors = []

    if not TELEGRAM_TOKEN or not TELEGRAM_TOKEN.strip():
        errors.append("TELEGRAM_TOKEN is missing or empty.")
    if not WEBHOOK_URL or "your-app-name" in WEBHOOK_URL:
        errors.append("WEBHOOK_URL is not set correctly. Please update it with your Render URL.")
    if not RAW_DATABASE_URL or not RAW_DATABASE_URL.strip():
        errors.append("RAW_DATABASE_URL is missing or empty.")
    if not REDIS_HOST or not REDIS_HOST.strip():
        errors.append("REDIS_HOST is missing or empty.")
    if not REDIS_PORT:
        errors.append("REDIS_PORT is missing.")

    if errors:
        summary = "\n".join("  * " + e for e in errors)
        raise RuntimeError(
            "Configuration validation failed (" + str(len(errors)) + " issue(s)):\n" + summary + "\nCheck your configuration and restart."
        )

    logger.info("Configuration validated successfully.")
