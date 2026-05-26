import os
import sys
import asyncio
from keep_alive import keep_alive

# تشغيل الخادم الوهمي فوراً لضمان استمرار السيرفر على Render
keep_alive()
print("✅ خادم Keep-Alive يعمل.")

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, AsyncSessionLocal, TrackedCoin
from bot.handlers import start_cmd, button_handler, text_handler
from Core.whale_tracker import WhaleTracker
from Core.trade_monitor import TradeMonitor
from sqlalchemy import select

async def start_background_tasks(app):
    """تشغيل المهام الخلفية مع نظام حماية من الحظر"""
    try:
        # انتظر قليلاً قبل البدء لضمان استقرار اتصال الإنترنت
        await asyncio.sleep(2)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedCoin.symbol))
            symbols = result.scalars().all()
        
        if not symbols:
            symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
            
        print(f"🛠️ جاري تهيئة الرادار لـ {len(symbols)} عملة...")

        # 1. رادار الحيتان (Whale Tracker)
        # تمت إضافة تأخير داخلي في الكلاس لتجنب طلبات Binance المتتالية
        tracker = WhaleTracker(bot=app.bot, chat_id=ADMIN_ID)
        asyncio.create_task(tracker.start_tracking(symbols))
        
        # تأخير 5 ثوانٍ بين تشغيل الرادار ومراقب الصفقات لتخفيف الضغط
        await asyncio.sleep(5)
        
        # 2. مراقب الصفقات (التعلم الذاتي ومراقبة الأهداف)
        monitor = TradeMonitor(bot=app.bot)
        asyncio.create_task(monitor.check_prices())
        
        print(f"🔄 المهام الخلفية تعمل الآن بنظام الحماية الذكي.")
    except Exception as e:
        print(f"⚠️ فشل بدء المهام الخلفية: {e}")

async def post_init(app: Application):
    """تُستدعى تلقائياً لتشغيل المهام الحرة"""
    await start_background_tasks(app)

def main():
    print("🚀 جاري إقلاع النظام المطور V3 (نسخة الحماية)...")
    
    # بناء قاعدة البيانات
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(init_db())
    except Exception as e:
        print(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")
    
    # بناء التطبيق مع نظام إدارة الطلبات لتيليجرام
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # إضافة المعالجات (Handlers)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    print("✅ النظام V3 جاهز تماماً ومعزز ببروتوكول Anti-Ban!")
    
    # drop_pending_updates=True تضمن عدم الرد على الرسائل القديمة أثناء التوقف وتجنب Conflict الـ Webhooks
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف النظام يدوياً.")
    except Exception as e:
        print(f"💥 خطأ غير متوقع في التشغيل: {e}")
