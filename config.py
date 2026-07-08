# config.py
import os
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Environment-driven configuration
# ═══════════════════════════════════════════════════════════════════

DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").strip().lower() in (
    "true", "1", "yes", "on"
)

# ═══════════════════════════════════════════════════════════════════
# 1. Telegram Bot Token — environment variable ONLY (never hardcoded)
# ═══════════════════════════════════════════════════════════════════
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

# ── Binance API Credentials (optional for monitoring-only mode) ──
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# ── Decision-Engine configuration object ──
# strategies.py uses _DecisionConfigProxy which falls back to defaults
# when DECISION_CONFIG is None.
DECISION_CONFIG = None

# ═══════════════════════════════════════════════════════════════════
# Configuration validation
# ═══════════════════════════════════════════════════════════════════

def validate_config():
    """
    Validate critical runtime configuration.
    Raises RuntimeError on hard failures; logs warnings for soft misses.
    """
    errors: list[str] = []

    # Telegram token (required)
    if not TELEGRAM_TOKEN or not TELEGRAM_TOKEN.strip():
        errors.append(
            "TELEGRAM_TOKEN is missing or empty — "
            "set the TELEGRAM_TOKEN environment variable."
        )

    # Binance credentials (optional — public endpoints work without them)
    if BINANCE_API_KEY and not BINANCE_API_KEY.strip():
        errors.append("BINANCE_API_KEY is set but whitespace-only.")
    if BINANCE_API_SECRET and not BINANCE_API_SECRET.strip():
        errors.append("BINANCE_API_SECRET is set but whitespace-only.")

    # Database
    if not RAW_DATABASE_URL or not RAW_DATABASE_URL.strip():
        errors.append("RAW_DATABASE_URL is missing or empty.")
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

    logger.info("[CONFIG] ✅ Configuration validated successfully.")


# ═══════════════════════════════════════════════════════════════════
# 2. Database
# ═══════════════════════════════════════════════════════════════════
RAW_DATABASE_URL = os.environ.get(
    "RAW_DATABASE_URL",
    "postgresql://postgres.licqbfixgyzrahuscwnh:***@"
    "aws-0-eu-west-1.pooler.supabase.com:6543/postgres",
)

DATABASE_URL = (
    RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    + "?ssl=require"
)

# ═══════════════════════════════════════════════════════════════════
# 3. Application settings
# ═══════════════════════════════════════════════════════════════════
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1503808643"))
HTF_MODE = os.environ.get("HTF_MODE", "SKIP")
DEFAULT_CAPITAL = float(os.environ.get("DEFAULT_CAPITAL", "10.0"))
TRADE_FEE = float(os.environ.get("TRADE_FEE", "0.001"))
BINANCE_WS_URL = os.environ.get(
    "BINANCE_WS_URL", "wss://stream.binance.com:9443"
)

# ═══════════════════════════════════════════════════════════════════
# 4. Redis
# ═══════════════════════════════════════════════════════════════════
REDIS_HOST = os.environ.get(
    "REDIS_HOST", "deft-wonderful-receipt-35081.db.redis.io"
)
REDIS_PORT = int(os.environ.get("REDIS_PORT", "18244"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "m4SWGk…CVVM")
