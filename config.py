# config.py
import os

# بياناتك الحقيقية
TELEGRAM_TOKEN = "8935169680:AAEo1yzskX1HQHchv_0mt9BvEc1bzZ9fdhU"
RAW_DATABASE_URL = "postgresql://copilot_user:ynPu1qycw2CrfixLRjkxVG0333NfXPYl@dpg-d84te69kh4rs73denmg0-a.virginia-postgres.render.com/copilot_db_ec8p"
DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

ADMIN_ID = 0 # تذكر تغيير هذا للـ ID الخاص بك لاحقاً

# إعدادات التداول
DEFAULT_CAPITAL = 1000.0
TRADE_FEE = 0.001 # 0.1%
WHALE_MIN_VALUE = 100000.0 # الحد الأدنى لاعتبار الصفقة "حوت" للعملات الكبيرة
