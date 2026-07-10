import os
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger(__name__)

# --- System Settings ---
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").strip().lower() in ("true", "1", "yes", "on")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- Telegram Settings ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8129443153:AAEPrpxbplE_Tf7fkR4eCueljc0DVLQcYxQ")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1503808643"))

# --- Database & Cache Settings ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
RAW_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-west-1.pooler.supabase.com:6543/postgres")
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
if "?ssl=require" not in DATABASE_URL:
    DATABASE_URL += "?ssl=require"

REDIS_URL = os.environ.get("REDIS_URL", "redis://:m4SWGkLu0SogNfODh1sIaHSJvpAICVVM@deft-wonderful-receipt-35081.db.redis.io:18244")
# For backward compatibility with CT's redis_client
REDIS_HOST = os.environ.get("REDIS_HOST", "deft-wonderful-receipt-35081.db.redis.io")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "18244"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "m4SWGkLu0SogNfODh1sIaHSJvpAICVVM")

# --- Trading Credentials ---
MT5_LOGIN = int(os.environ.get("MT5_LOGIN", "0"))
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "")
MT5_PATH = os.environ.get("MT5_PATH", None)
SIMULATION_MODE = os.environ.get("SIMULATION_MODE", "1") == "1"

# --- Trading Parameters ---
SYMBOL = os.environ.get("SYMBOL", "XAUUSD")
CAPITAL = float(os.environ.get("CAPITAL", "5000.0"))
RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE", "1.0"))
TIMEFRAME = os.environ.get("TIMEFRAME", "M15")

def validate_config():
    errors = []
    if not TELEGRAM_TOKEN: errors.append("TELEGRAM_TOKEN is missing")
    if not RAW_DATABASE_URL: errors.append("DATABASE_URL is missing")
    
    if not SIMULATION_MODE:
        if MT5_LOGIN == 0: errors.append("MT5_LOGIN is missing")
        if not MT5_PASSWORD: errors.append("MT5_PASSWORD is missing")
        if not MT5_SERVER: errors.append("MT5_SERVER is missing")
    
    if errors:
        raise RuntimeError(f"Config validation failed: {', '.join(errors)}")
    logger.info("Configuration validated successfully.")
