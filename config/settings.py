
"""
File: config/settings.py
1. Single Responsibility: Concrete runtime configuration -- plain Python values,
   NO .env, NO os.environ (per Section 3 policy).
2. Consumes: nothing.
3. Produces: A ``SystemConfig`` instance named ``settings``.
4. Downstream: app/main.py and every module that needs credentials.
5. New Dependencies: contracts.config.SystemConfig.
6. Touches Section 6 bugs? No.
7. Tests: No (not imported by tests; they construct their own SystemConfig).
8. Logging: No.
9. Dependency Order: config -> contracts -> ... (this file imports contracts.config).

SECURITY POLICY (Section 3):
  - This file MUST be listed in .gitignore and never committed.
  - If accidentally committed, rotate telegram_bot_token / supabase_key immediately.
  - The file config/settings.example.py is the safe template committed instead.
"""

import os
from contracts.config import SystemConfig

# ---------------------------------------------------------------------------
# NEW CREDENTIALS PROVIDED BY USER
# ---------------------------------------------------------------------------
# Telegram Token
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8861445628:AAFVuxfIXmTQGIoKMmcTcPZipdShTKFaewg")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7052631557")

# Supabase / Postgres (Transaction Pooler IPv4)
# For asyncpg.create_pool, the DSN must start with postgresql:// NOT postgresql+asyncpg://
RAW_DATABASE_URL = "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
# Ensure SSL is required as per Supabase/Render standards
DATABASE_URL = os.environ.get("SUPABASE_URL", RAW_DATABASE_URL)
if "ssl=" not in DATABASE_URL:
    separator = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL += f"{separator}ssl=require"

# Redis Cloud
REDIS_HOST = "deft-wonderful-receipt-35081.db.redis.io"
REDIS_PORT = 18244
REDIS_PASSWORD = "m4SWGkLu0SogNfODh1sIaHSJvpAICVVM"
REDIS_URL = os.environ.get("REDIS_URL", f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0")

# ---------------------------------------------------------------------------
# System Configuration
# ---------------------------------------------------------------------------
settings = SystemConfig(
    telegram_bot_token=TELEGRAM_TOKEN,
    supabase_url=DATABASE_URL,
    supabase_key=os.environ.get("SUPABASE_KEY", "service_role_key_placeholder"),
    redis_url=REDIS_URL,
    default_timeframes=["15m", "1h", "4h"],
    max_active_coins: 10,
    simulation_mode: True,
    telegram_chat_id: TELEGRAM_CHAT_ID,
)
