# config.py

# 1. توكن التليجرام
TELEGRAM_TOKEN = "8935169680:AAHH2VJ_tn9xGwwu-ottEBWrh0GilngCpfc"

# 2. رابط Supabase النهائي (تم دمج Host مع كلمة المرور والمنفذ الصحيح)
RAW_DATABASE_URL = "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

# تحويل الرابط ليدعم البرمجة غير المتزامنة (Asyncpg)
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# 3. إعدادات الإدارة والتداول
ADMIN_ID = 1503808643
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001
BINANCE_WS_URL = "wss://stream.binance.com:9443"
