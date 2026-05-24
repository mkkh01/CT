# config.py

# 1. توكن التليجرام الخاص بك
TELEGRAM_TOKEN = "8935169680:AAHH2VJ_tn9xGwwu-ottEBWrh0GilngCpfc"

# 2. رابط قاعدة البيانات المستخرج من الصورة الأخيرة
# ملاحظة: تم استبدال [YOUR-PASSWORD] بكلمة مرورك Mk_03065750
RAW_DATABASE_URL = "postgresql://postgres:Mk_03065750@db.licqbfixgyzrahuscwnh.supabase.co:5432/postgres"

# تحويل الرابط ليدعم asyncpg مع إضافة ssl=require لضمان الاتصال من Render
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1) + "?ssl=require"

# 3. بقية الإعدادات
ADMIN_ID = 1503808643
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001
BINANCE_WS_URL = "wss://stream.binance.com:9443"
