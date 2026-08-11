from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.config import settings
from services.supabase_client import init_db, close_db, supabase
from services.redis_client import redis_client
from core.telegram_bot import TelegramBot

bot = TelegramBot()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await redis_client.connect()
    
    try:
        await bot.start()
        print("🤖 Telegram Bot ONLINE ✅")
    except Exception as e:
        print(f"⚠️ مشكلة في تشغيل البوت: {type(e).__name__}: {e}")
    
    yield

    try:
        await bot.stop()
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
        "bot": "✅ محمّل" if bot else "⚠️ غير محمّل"
    }
