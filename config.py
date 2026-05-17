import os

# توكن بوت التلغرام الخاص بك الحقيقي والمباشر
TELEGRAM_TOKEN = "8935169680:AAEo1yzskX1HQHchv_0mt9BvEc1bzZ9fdhU"

# رابط قاعدة البيانات الحقيقي والمباشر الخاص بك على Render
DATABASE_URL = "Postgresql://copilot_user:ynPu1qycw2CrfixLRjkxVG0333NfXPYl@dpg-d84te69kh4rs73denmg0-a.virginia-postgres.render.com/copilot_db_ec8p"

# التحقق الصارم من تشغيل النظام لمنع الأخطاء المفاجئة
if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "":
    raise ValueError("CRITICAL ERROR: يرجى وضع توكن التلغرام الحقيقي الخاص بك أولاً!")
