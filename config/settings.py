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

from contracts.config import SystemConfig

# ---------------------------------------------------------------------------
# REPLACE the placeholders below with real values before running the bot.
# ---------------------------------------------------------------------------
settings = SystemConfig(
    telegram_bot_token="PUT-YOUR-TELEGRAM-BOT-TOKEN-HERE",
    supabase_url="https://YOUR-PROJECT.supabase.co",
    supabase_key="YOUR-SUPABASE-SERVICE-KEY",
    redis_url="redis://localhost:6379/0",
    default_timeframes=["15m", "1h", "4h"],
    max_active_coins=10,
    simulation_mode=True,
)
