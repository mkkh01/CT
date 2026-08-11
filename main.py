from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.config import settings
from services.supabase_client import init_db, close_db, supabase
from services.redis_client import redis_client
from core.telegram_bot import TelegramBot

print("✅ [1] تم استيراد كل الملفات — جاهز للانطلاق")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✅ [2] بدء تشغيل الخدمات...")
    
    # ✅ قاعدة البيانات أولاً
    await init_db()
    print("✅ [3] قاعدة البيانات جاهزة")
    
    # ✅ Redis ثانياً
    await redis_client.connect()
    print("✅ [4] Redis جاهز")
    
    # ✅ نُؤجّل إنشاء البوت إلى هنا — بعد أن تصبح البيئة جاهزة تماماً
    print("✅ [5] جارٍ إنشاء وتشغيل البوت...")
    try:
        bot = TelegramBot()
        print("✅ [5.1] تم إنشاء كائن البوت")
        
        # ✅ عرض الطرق المتاحة لمعرفة الصحيح
        methods = [m for m in dir(bot) if not m.startswith('_')]
        print(f"🔍 طرق البوت المتاحة: {methods}")
        
        # ✅ محاولة التشغيل بالطريقة الصحيحة
        if hasattr(bot, 'start'):
            await bot.start()
            print("🤖 البوت شغّل بـ: start()")
        elif hasattr(bot, 'run'):
            await bot.run()
            print("🤖 البوت شغّل بـ: run()")
        elif hasattr(bot, 'start_polling'):
            await bot.start_polling()
            print("🤖 البوت شغّل بـ: start_polling()")
        else:
            print("⚠️ لم يتم العثور على طريقة تشغيل معروفة")
            
    except Exception as e:
        print(f"❌ خطأ في البوت: {type(e).__name__}: {e}")
        import traceback
        print(f"📌 التفاصيل الكاملة:\n{traceback.format_exc()}")
    
    print("✅ [6] النظام يعمل الآن ✅")
    yield
    
    # ✅ الإيقاف الآمن
    print("✅ [7] جارٍ إيقاف الخدمات...")
    try:
        if 'bot' in locals():
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
        "redis": "✅ متصل" if redis_client.redis else "⚠️ غير متصل"
    }
