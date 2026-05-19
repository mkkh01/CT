import os

# توكن التليجرام الخاص بك
TELEGRAM_TOKEN = "8935169680:AAEo1yzskX1HQHchv_0mt9BvEc1bzZ9fdhU"

# رابط قاعدة البيانات
RAW_DATABASE_URL = "postgresql://copilot_user:ynPu1qycw2CrfixLRjkxVG0333NfXPYl@dpg-d84te69kh4rs73denmg0-a.virginia-postgres.render.com/copilot_db_ec8p"
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# الـ ID الخاص بك (الأدمن الوحيد الذي سيستقبل الإشعارات)
ADMIN_ID = 1503808643

# إعدادات التداول الافتراضية
DEFAULT_CAPITAL = 1000.0
TRADE_FEE = 0.001
