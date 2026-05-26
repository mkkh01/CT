import os
import sys
import asyncio
from keep_alive import keep_alive

# تشغيل الخادم الوهمي
keep_alive()
print("✅ خادم Keep-Alive يعمل.")

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, AsyncSessionLocal, TrackedCoin, UserConfig
from bot.handlers import start_cmd, button_handler, text_handler, start_add_coin, get_coin_name, get_capital, get_timeframe, NAME, CAPITAL, TIMEFRAME
from Core.whale_tracker import WhaleTracker
from Core.trade_monitor import TradeMonitor
from sqlalchemy import select

# --- [إضافة المحرك الجديد] ---
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_add_coin, pattern='^add_coin$')],
    states={
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_coin_name)],
        CAPITAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_capital)],
        TIMEFRAME: [CallbackQueryHandler(get_timeframe, pattern='^tf_')]
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

async def start_background_tasks(app):
    # ... (نفس منطقك السابق بدون تغيير)
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
                        if hasattr(tracker, 'start_tracking'): await tracker.start_tracking(symbols)
                        await monitor.check_prices() 
            await asyncio.sleep(60)
        except Exception as e:
            print(f"⚠️ خطأ في دورة المهام الخلفية: {e}")
            await asyncio.sleep(60)

async def post_init(app: Application):
    asyncio.create_task(start_background_tasks(app))

def main():
    print("🚀 جاري إقلاع النظام المطور V3...")
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(init_db())
    except Exception as e:
        print(f"❌ خطأ في قاعدة البيانات: {e}")
    
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # حذف Webhook لضمان Polling مستقر
    loop.run_until_complete(app.bot.delete_webhook())
    
    # [الترتيب مهم جداً]:
    app.add_handler(conv_handler) # 1. المحرك الجديد أولاً
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler)) 
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    print("✅ النظام جاهز. ConversationHandler مفعل.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
