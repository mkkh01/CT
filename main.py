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
    """تشغيل المهام الخلفية عند إقلاع البوت"""
    try:
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
    except Exception as e:
        print(f"⚠️ فشل بدء المهام الخلفية: {e}")

async def post_init(app: Application):
    """تُستدعى تلقائياً لتشغيل المهام الحرة"""
    await start_background_tasks(app)

def main():
    print("🚀 جاري إقلاع النظام المطور V3...")
    
    # بناء قاعدة البيانات
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    
    # بناء التطبيق مع drop_pending_updates لتجنب الـ Conflict
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    print("✅ النظام V3 جاهز تماماً للعمل المستقر!")
    
    # drop_pending_updates=True تضمن عدم الرد على الرسائل القديمة أثناء التوقف
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 توقف النظام.")
