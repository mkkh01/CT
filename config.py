# config.py
import os
import logging

logger = logging.getLogger(__name__)

# Debug mode
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").strip().lower() in ("true", "1", "yes", "on")

# 1. التوكن الخاص بك
TELEGRAM_TOKEN = "8129443153:AAEPrpxbplE_Tf7fkR4eCueljc0DVLQcYxQ"

# Binance API Credentials (optional)
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# Decision-Engine configuration object
DECISION_CONFIG = None

# Configuration validation
def validate_config():
    errors = []

    if not TELEGRAM_TOKEN or not TELEGRAM_TOKEN.strip():
        errors.append("TELEGRAM_TOKEN is missing or empty.")

    if BINANCE_API_KEY and not BINANCE_API_KEY.strip():
        errors.append("BINANCE_API_KEY is set but whitespace-only.")
    if BINANCE_API_SECRET and not BINANCE_API_SECRET.strip():
        errors.append("BINANCE_API_SECRET is set but whitespace-only.")

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

# 2. الرابط الجديد من خانة Transaction pooler (الذي يدعم IPv4)
# ملاحظة: تم استخدام المنفذ 6543 واسم المستخدم المدمج كما يظهر في صورتك
RAW_DATABASE_URL = "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"

# تحويل الرابط ليدعم asyncpg مع فرض SSL
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1) + "?ssl=require"

# 3. بقية الإعدادات
ADMIN_ID = 1503808643
HTF_MODE = "SKIP"  # Options: SKIP, CONTINUE_LOW_CONF, FALLBACK
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001
BINANCE_WS_URL = "wss://stream.binance.com:9443"

# Redis Configuration (Redis Cloud)
REDIS_HOST = "deft-wonderful-receipt-35081.db.redis.io"
REDIS_PORT = 18244
REDIS_PASSWORD = "m4SWGkLu0SogNfODh1sIaHSJvpAICVVM"
