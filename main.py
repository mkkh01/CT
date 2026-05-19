import os
import sys
import asyncio
from keep_alive import keep_alive

# تشغيل الخادم الوهمي فوراً
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
    """تشغيل المهام الخلفية (الرادار ومراقب الصفقات)"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TrackedCoin.symbol))
        symbols = result.scalars().all()
    
    if not symbols:
        symbols = ["BTCUSDT", "ETHUSDT"]
        
    # 1. رادار الحيتان
    tracker = WhaleTracker(bot=app.bot, chat_id=ADMIN_ID)
    asyncio.create_task(tracker.start_tracking(symbols))
    
    # 2. مراقب الصفقات (التعلم الذاتي)
    monitor = TradeMonitor(bot=app.bot)
    asyncio.create_task(monitor.check_prices())
    
    print(f"🔄 المهام الخلفية تعمل لـ {len(symbols)} عملة.")

async def main():
    print("🚀 جاري إقلاع النظام المطور V3...")
    await init_db()
    
    # بناء التطبيق
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # إضافة الموجهات والـ handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    # تشغيل المهام الخلفية عند بدء تشغيل البوت مباشرة بطريقة آمنة
    await start_background_tasks(app)
    
    print("✅ النظام V3 يعمل الآن بكامل طاقته تلقائياً!")
    
    # التشغيل القياسي الآمن الذي يمنع التعارض ويغلق الجلسات القديمة تلقائياً
    async with app:
        await app.updater.start_polling()
        await app.start()
        # الانتظار بشكل آمن يمنع تجمد السيرفر وتكرار العمليات
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        # إعداد بيئة التشغيل لأنظمة الأيوسنكرونوس المتقدمة
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 توقف النظام.")
