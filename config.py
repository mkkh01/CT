import os

# توكن التليجرام الخاص بك (تم التحديث إلى التوكن الجديد الآمن)
TELEGRAM_TOKEN = "8935169680:AAEUwvb6g6xhwaCe6PnKmO1Q2dKU_T_hQlc"

# رابط قاعدة البيانات المباشر والآمن (Asyncpg)
RAW_DATABASE_URL = "postgresql://copilot_user:ynPu1qycw2CrfixLRjkxVG0333NfXPYl@dpg-d84te69kh4rs73denmg0-a.virginia-postgres.render.com/copilot_db_ec8p"
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# الـ ID الخاص بك (الأدمن المصرح له بالتحكم)
ADMIN_ID = 1503808643

# إعدادات التداول الافتراضية والتعلم الذاتي (تم تعديل رأس المال هنا إلى 10.0 ليتناسب مع الصفقات الصغيرة)
DEFAULT_CAPITAL = 10.0
TRADE_FEE = 0.001

# رابط خدمة البث المباشر (WebSocket) لمنصة بينانس لملفات الرادار والمراقبة
BINANCE_WS_URL = "wss://stream.binance.com:9443"
