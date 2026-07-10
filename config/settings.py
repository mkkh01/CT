import os
from .env import get_env, get_bool_env, get_int_env, get_float_env
import logging

# --- System Settings ---
DEBUG_MODE = get_bool_env("DEBUG_MODE", False)
LOG_LEVEL = get_env("LOG_LEVEL", "INFO").upper()

# --- Operating Modes ---
SIGNAL_MODE = get_bool_env("SIGNAL_MODE", True)
LIVE_MODE = get_bool_env("LIVE_MODE", False)
SIMULATION_MODE = get_bool_env("SIMULATION_MODE", False)

# --- Telegram Settings ---
TELEGRAM_TOKEN = get_env("TELEGRAM_TOKEN", "8129443153:AAEPrpxbplE_Tf7fkR4eCueljc0DVLQcYxQ")
ADMIN_ID = get_int_env("ADMIN_ID", 1503808643)

# --- Database & Cache Settings ---
SUPABASE_URL = get_env("SUPABASE_URL", "")
SUPABASE_KEY = get_env("SUPABASE_KEY", "")
RAW_DATABASE_URL = get_env("DATABASE_URL", "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-west-1.pooler.supabase.com:6543/postgres")
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
if "?ssl=require" not in DATABASE_URL:
    DATABASE_URL += "?ssl=require"

REDIS_URL = get_env("REDIS_URL", "redis://:m4SWGkLu0SogNfODh1sIaHSJvpAICVVM@deft-wonderful-receipt-35081.db.redis.io:18244")
REDIS_HOST = get_env("REDIS_HOST", "deft-wonderful-receipt-35081.db.redis.io")
REDIS_PORT = get_int_env("REDIS_PORT", 18244)
REDIS_PASSWORD = get_env("REDIS_PASSWORD", "m4SWGkLu0SogNfODh1sIaHSJvpAICVVM")

# --- Trading Credentials ---
MT5_LOGIN = get_int_env("MT5_LOGIN", 0)
MT5_PASSWORD = get_env("MT5_PASSWORD", "")
MT5_SERVER = get_env("MT5_SERVER", "")
MT5_PATH = get_env("MT5_PATH", None)

# --- Trading Parameters ---
SYMBOL = get_env("SYMBOL", "XAUUSD")
CAPITAL = get_float_env("CAPITAL", 5000.0)
RISK_PER_TRADE = get_float_env("RISK_PER_TRADE", 1.0)
TIMEFRAME = get_env("TIMEFRAME", "M15")

def validate_config():
    errors = []
    if not TELEGRAM_TOKEN: errors.append("TELEGRAM_TOKEN is missing")
    if not RAW_DATABASE_URL: errors.append("DATABASE_URL is missing")
    
    if LIVE_MODE:
        if MT5_LOGIN == 0: errors.append("MT5_LOGIN is missing for LIVE_MODE")
        if not MT5_PASSWORD: errors.append("MT5_PASSWORD is missing for LIVE_MODE")
        if not MT5_SERVER: errors.append("MT5_SERVER is missing for LIVE_MODE")
    
    if errors:
        raise RuntimeError(f"Config validation failed: {', '.join(errors)}")
    return True
