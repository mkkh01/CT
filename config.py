# config.py

# 1. توكن التليجرام
TELEGRAM_TOKEN = "8935169680:AAHH2VJ_tn9xGwwu-ottEBWrh0GilngCpfc"

# 2. رابط الـ Pooler المخصص (يحل مشكلة Tenant not found)
# العنوان يبدأ بـ aws-0-eu-central-1 والمنفذ 6543
RAW_DATABASE_URL = "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

# تحويل الرابط ليدعم asyncpg مع فرض SSL لبيئة Render
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1) + "?ssl=require"

# 3. إعدادات الإدارة
ADMIN_ID = 1503808643
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001
BINANCE_WS_URL = "wss://stream.binance.com:9443"
