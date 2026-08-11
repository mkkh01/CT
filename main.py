from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.config import settings
from services.supabase_client import init_db, close_db, supabase
from services.redis_client import redis_client
from core.telegram_bot import TelegramBot

print("✅ [1] تم استيراد كل الملفات")

bot = TelegramBot()
print("✅ [2] تم إنشاء كائن البوت")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✅ [3] بدء تشغيل الخدمات...")
    
    await init_db()
    print("✅ [4] قاعدة البيانات جاهزة")
    
    await redis_client.connect()
    print("✅ [5] Redis جاهز")
    
    print("✅ [6] جارٍ تشغيل البوت...")
    try:
        # ✅ نعرض طرق الكلاس أولاً
        print(f"🔍 طرق TelegramBot: {[m for m in dir(bot) if not m.startswith('_')]}")
        
        # ✅ محاولة تشغيل البوت
        if hasattr(bot, 'run'):
            await bot.run()
            print("🤖 البوت شغّل بـ: run()")
        elif hasattr(bot, 'start'):
            await bot.start()
            print("🤖 البوت شغّل بـ: start()")
        elif hasattr(bot, 'start_polling'):
            await bot.start_polling()
            print("🤖 البوت شغّل بـ: start_polling()")
        else:
            print("⚠️ لم يتم العثور على طريقة تشغيل للبوت")
    except Exception as e:
        print(f"❌ خطأ تشغيل البوت: {type(e).__name__}: {e}")
        import traceback
        print(f"📌 التفاصيل: {traceback.format_exc()}")
    
    print("✅ [7] النظام جاهز ✅")
    yield
    
    print("✅ [8] جارٍ إيقاف...")
    try:
        if hasattr(bot, 'stop'):
            await bot.stop()
        elif hasattr(bot, 'stop_polling'):
            await bot.stop_polling()
        print("✅ تم إيقاف البوت")
    except Exception as e:
        print(f"⚠️ خطأ إيقاف البوت: {type(e).__name__}: {e}")
    
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
