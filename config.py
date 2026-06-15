# config.py

# 1. التوكن الخاص بك
TELEGRAM_TOKEN = "8935169680:AAHH2VJ_tn9xGwwu-ottEBWrh0GilngCpfc"

# 2. الرابط الجديد من خانة Transaction pooler (الذي يدعم IPv4)
# ملاحظة: تم استخدام المنفذ 6543 واسم المستخدم المدمج كما يظهر في صورتك
RAW_DATABASE_URL = "postgresql://postgres.licqbfixgyzrahuscwnh:Mk_03065750@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"

# تحويل الرابط ليدعم asyncpg مع فرض SSL
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1) + "?ssl=require"

# 3. بقية الإعدادات
ADMIN_ID = 1503808643
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001
BINANCE_WS_URL = "wss://stream.binance.com:9443"

# 4. إعدادات Redis
REDIS_URL = "redis://:OsYazrMladbKz5s1W2p4bbzv4NDNwGHy@moon-close-reaction-79072.db.redis.io:10184"
