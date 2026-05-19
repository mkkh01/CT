# main.py
import asyncio
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from config import TELEGRAM_TOKEN
from database import init_db
from bot.handlers import start_cmd, button_handler
from Core.whale_tracker import WhaleTracker  # تم التعديل هنا إلى Core
from keep_alive import keep_alive

async def start_background_tasks():
    """تشغيل المهام الخلفية مثل رادار الحيتان"""
    tracker = WhaleTracker()
    symbols_to_track = ["BTCUSDT", "ETHUSDT", "PEPEUSDT"] 
    
    print("🔄 جاري تشغيل رادار الحيتان للعملات المحددة...")
    asyncio.create_task(tracker.start_tracking(symbols_to_track))

async def main():
    print("🚀 جاري إقلاع النظام المتقدم...")
    
    # تشغيل خادم الويب الوهمي لإرضاء منصة Render
    keep_alive()
    
    # 1. تهيئة قاعدة البيانات
    await init_db()
    
    # 2. تشغيل المهام الخلفية (الحيتان)
    await start_background_tasks()
    
    # 3. تهيئة وتشغيل بوت التليجرام
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ النظام يعمل بكامل طاقته! اذهب إلى تليجرام وأرسل /start")
    
    # تشغيل البوت
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # إبقاء النظام يعمل
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف النظام بأمان.")
