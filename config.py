# config.py

# 1. توكن التليجرام
TELEGRAM_TOKEN = "8935169680:AAHH2VJ_tn9xGwwu-ottEBWrh0GilngCpfc"

# 2. رابط الـ Connection Pooler (الحل الموصى به لـ Render و Supabase)
# لاحظ المنفذ 6543 وإضافة المعرف لاسم المستخدم
RAW_DATABASE_URL = "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

# التحويل ليدعم asyncpg مع التأكد من فرض SSL
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1) + "?ssl=require"

# 3. بقية الإعدادات الخاصة بك
ADMIN_ID = 1503808643
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001
BINANCE_WS_URL = "wss://stream.binance.com:9443"
