
"""
File: config/settings.py
Responsibility: Concrete runtime configuration -- plain Python values,
reading from environment variables with safe fallbacks.
"""

import os
import sys
from contracts.config import SystemConfig

# ---------------------------------------------------------------------------
# CREDENTIALS
# ---------------------------------------------------------------------------
# Telegram Token
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Supabase / Postgres (Transaction Pooler IPv4)
# For asyncpg.create_pool, the DSN must start with postgresql://
DATABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Redis Cloud
REDIS_URL = os.environ.get("REDIS_URL")

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_config():
    missing = []
    if not TELEGRAM_TOKEN: missing.append("TELEGRAM_BOT_TOKEN")
    if not DATABASE_URL: missing.append("SUPABASE_URL (Postgres DSN)")
    if not SUPABASE_KEY: missing.append("SUPABASE_KEY")
    if not REDIS_URL: missing.append("REDIS_URL")
    
    if missing:
        print(f"CRITICAL CONFIG ERROR: Missing environment variables: {', '.join(missing)}")
        print("Please set these variables in your environment or Render dashboard.")
        # We don't exit here to allow the app to try and fail gracefully with its own logging,
        # but we provide clear console output.
        return False
    return True

validate_config()

# Handle SSL for Postgres if using Supabase/Render
if DATABASE_URL and "ssl=" not in DATABASE_URL:
    separator = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL += f"{separator}sslmode=require"

# ---------------------------------------------------------------------------
# System Configuration
# ---------------------------------------------------------------------------
settings = SystemConfig(
    telegram_bot_token=TELEGRAM_TOKEN or "MISSING_TOKEN",
    supabase_url=DATABASE_URL or "postgresql://localhost/missing_db",
    supabase_key=SUPABASE_KEY or "MISSING_KEY",
    redis_url=REDIS_URL or "redis://localhost:6379/0",
    default_timeframes=["15m", "1h", "4h"],
    max_active_coins=10,
    simulation_mode=True,
    telegram_chat_id=TELEGRAM_CHAT_ID or "0",
)
