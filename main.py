from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.config import settings
from services.supabase_client import init_db, close_db, supabase
from services.redis_client import redis_client
from core.telegram_bot import application  # ✅ المسار الصحيح!

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ✅ بدء تشغيل الخدمات
    await init_db()
    await redis_client.connect()
    
    # ✅ بدء بوت التليجرام
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    print("🤖 Telegram Bot ONLINE ✅")
    
    yield  # ← التطبيق يعمل هنا

    # ✅ إيقاف آمن عند الإغلاق
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
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
        "redis": "✅ متصل" if redis_client.redis else "⚠️ غير متصل"
    }
