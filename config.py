# config.py
import os
import logging

logger = logging.getLogger(__name__)

# ── Binance API Credentials (canonical source: environment variables) ──
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ── Decision-Engine configuration object ──
# strategies.py ships a _DecisionConfigProxy that uses its own defaults when
# DECISION_CONFIG is None, so backward compatibility is preserved.
DECISION_CONFIG = None

# ── Configuration validation ──
def validate_config():
    """
    Validate that every critical runtime secret is present and non-trivial.
    Raises RuntimeError with a human-readable summary on failure so the
    operator never receives a cryptic ImportError or a late-stage crash.
    """
    errors: list[str] = []

    # Binance credentials — optional for monitoring-only mode.
    # When absent, ccxt fetches public OHLCV data without authentication.
    # When present, higher rate limits and private endpoints are unlocked.
    if BINANCE_API_KEY and not BINANCE_API_KEY.strip():
        errors.append("BINANCE_API_KEY is set but appears to be whitespace-only.")
    if BINANCE_API_SECRET and not BINANCE_API_SECRET.strip():
        errors.append("BINANCE_API_SECRET is set but appears to be whitespace-only.")

    # Telegram token
    if not TELEGRAM_TOKEN or not TELEGRAM_TOKEN.strip():
        errors.append("TELEGRAM_TOKEN is missing or empty.")

    # Database URL
    if not RAW_DATABASE_URL or not RAW_DATABASE_URL.strip():
        errors.append("RAW_DATABASE_URL is missing or empty.")

    # Redis
    if not REDIS_HOST or not REDIS_HOST.strip():
        errors.append("REDIS_HOST is missing or empty.")
    if not REDIS_PORT:
        errors.append("REDIS_PORT is missing.")

    if errors:
        summary = "\n".join(f"  • {e}" for e in errors)
        raise RuntimeError(
            f"Configuration validation failed ({len(errors)} issue(s)):\n{summary}\n"
            f"Check your environment variables and restart."
        )

    logger.info("✅ Configuration validated successfully.")


# 1. التوكن الخاص بك
TELEGRAM_TOKEN = "8129443153:AAEPrpxbplE_Tf7fkR4eCueljc0DVLQcYxQ"

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
