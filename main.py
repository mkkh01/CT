import os
import sys
import asyncio
from keep_alive import keep_alive

# تشغيل الخادم الوهمي لضمان استقرار Render
keep_alive()
print("✅ خادم Keep-Alive يعمل.")

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, AsyncSessionLocal, TrackedCoin, UserConfig
from bot.handlers import start_cmd, button_handler, text_handler
from Core.whale_tracker import WhaleTracker
from Core.trade_monitor import TradeMonitor
from sqlalchemy import select

async def start_background_tasks(app):
    """تشغيل المهام الخلفية بنظام تحكم آمن"""
    print("⏳ نظام الحماية: انتظار 30 ثانية لاستقرار الاتصال...")
    await asyncio.sleep(30)
    
    tracker = WhaleTracker(bot=app.bot, chat_id=ADMIN_ID)
    monitor = TradeMonitor(bot=app.bot)

    print(f"📡 تم تشغيل الرادار والمحلل التحليلي V3.2 بنجاح.")

    while True:
        try:
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
                cfg = res.scalars().first()
                
                if cfg and cfg.is_active:
                    coin_res = await session.execute(select(TrackedCoin.symbol))
                    symbols = coin_res.scalars().all()
                    
                    if symbols:
                        if hasattr(tracker, 'start_tracking'):
                            await tracker.start_tracking(symbols)
                        await monitor.check_prices() 
            
            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"⚠️ خطأ في دورة المهام الخلفية: {e}")
            await asyncio.sleep(60)

async def post_init(app: Application):
    """تهيئة المهام الخلفية عند بدء التشغيل"""
    asyncio.create_task(start_background_tasks(app))

def main():
    print("🚀 جاري إقلاع النظام المطور V3...")
    
    # تهيئة قاعدة البيانات
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(init_db())
    except Exception as e:
        print(f"❌ خطأ في قاعدة البيانات: {e}")
    
    # بناء التطبيق
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # [تعديل هام] حذف أي Webhook قديم عالق لضمان عمل الـ Polling
    loop.run_until_complete(app.bot.delete_webhook())
    
    # إضافة المعالجات (Handlers) بالترتيب الصحيح
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler)) # الأزرار أولاً
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    print("✅ النظام جاهز. تحكم بالتعلم الخفي من الأزرار السفلية.")
    
    # تشغيل البوت
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف النظام.")
