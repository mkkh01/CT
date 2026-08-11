from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.config import settings
from services.supabase_client import init_db, close_db, supabase
from services.redis_client import redis_client

# ✅ اكتشاف ما هو متاح في ملف البوت
print("🔍 جارٍ فحص محتوى core/telegram_bot.py ...")
try:
    import core.telegram_bot as tb_module
    print(f"✅ المتاح في الملف: {[x for x in dir(tb_module) if not x.startswith('_')]}")
    # محاولة استيراد الاسم الصحيح
    if hasattr(tb_module, 'application'):
        from core.telegram_bot import application
        print("✅ تم العثور على: application")
    elif hasattr(tb_module, 'app'):
        application = tb_module.app
        print("✅ تم العثور على: app")
    elif hasattr(tb_module, 'bot'):
        application = tb_module.bot
        print("✅ تم العثور على: bot")
    elif hasattr(tb_module, 'updater'):
        application = tb_module.updater
        print("✅ تم العثور على: updater")
    else:
        print("⚠️ لم يتم العثور على كائن بوت معروف!")
        application = None
except Exception as e:
    print(f"❌ خطأ في استيراد البوت: {type(e).__name__}: {e}")
    application = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ✅ بدء تشغيل الخدمات
    await init_db()
    await redis_client.connect()
    
    # ✅ بدء بوت التليجرام (إذا وُجد)
    if application:
        try:
            if hasattr(application, 'initialize'):
                await application.initialize()
            if hasattr(application, 'start'):
                await application.start()
            if hasattr(application, 'updater') and hasattr(application.updater, 'start_polling'):
                await application.updater.start_polling()
            print("🤖 Telegram Bot ONLINE ✅")
        except Exception as e:
            print(f"⚠️ مشكلة في تشغيل البوت: {type(e).__name__}: {e}")
    else:
        print("⚠️ البوت غير مهيأ — نظام يعمل بدون بوت مؤقتاً")
    
    yield  # ← التطبيق يعمل هنا

    # ✅ إيقاف آمن عند الإغلاق
    if application:
        try:
            if hasattr(application, 'updater') and hasattr(application.updater, 'stop'):
                await application.updater.stop()
            if hasattr(application, 'stop'):
                await application.stop()
            if hasattr(application, 'shutdown'):
                await application.shutdown()
            print("✅ تم إيقاف البوت بأمان")
        except Exception as e:
            print(f"⚠️ مشكلة في إيقاف البوت: {type(e).__name__}: {e}")
    await close_db()
    await redis_client.close()
    print("✅ تم إيقاف النظام بأمان")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "✅ SYSTEM ONLINE"}

@app.get("/health")
async def health_check():
    return {
        "status": "✅ ONLINE",
        "supabase": "✅ متصل" if supabase else "⚠️ غير متصل",
        "redis": "✅ متصل" if redis_client.redis else "⚠️ غير متصل",
        "bot": "✅ محمّل" if application else "⚠️ غير محمّل"
    }
