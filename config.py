# config.py

# 1. توكن التليجرام الخاص بك
TELEGRAM_TOKEN = "8935169680:AAHH2VJ_tn9xGwwu-ottEBWrh0GilngCpfc"

# 2. رابط قاعدة البيانات المباشر والآمن (Asyncpg) لمنصة Render
RAW_DATABASE_URL = "postgresql://copilot_user:ynPu1qycw2CrfixLRjkxVG0333NfXPYl@dpg-d84te69kh4rs73denmg0-a.virginia-postgres.render.com/copilot_db_ec8p"
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# 3. الـ ID الخاص بك (الأدمن المصرح له بالتحكم)
ADMIN_ID = 1503808643

# 4. إعدادات التداول الافتراضية والتعلم الذاتي
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001

# 5. رابط خدمة البث المباشر (WebSocket) لمنصة بينانس
BINANCE_WS_URL = "wss://stream.binance.com:9443"
