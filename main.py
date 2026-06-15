import os
import sys
import asyncio
import logging
from keep_alive import keep_alive
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, AsyncSessionLocal, UserConfig
from bot.handlers import (
    start, handle_message, process_add_symbol, process_add_capital, 
    process_add_risk, process_add_tf,
    ADD_SYMBOL, ADD_CAPITAL, ADD_RISK, ADD_TF
)
from Core.trade_monitor import TradeMonitor

# إعداد نظام السجلات (Logging)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# تشغيل خادم Keep-Alive
keep_alive()

async def start_background_tasks(app):
    """تشغيل الرادار المؤسسي والمراقبة"""
    await asyncio.sleep(5)
    monitor = TradeMonitor(bot=app.bot)
    asyncio.create_task(monitor.check_prices())
    logger.info("📡 [SYSTEM] تم إطلاق الرادار المؤسسي والمراقبة اللحظية.")

async def post_init(app: Application):
    asyncio.create_task(start_background_tasks(app))

def main():
    logger.info("🚀 جاري إقلاع نظام التداول المؤسسي CT V4.0...")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # إعداد المحادثة المؤسسية لإضافة عملة
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ إضافة عملة$"), handle_message)],
        states={
            ADD_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_symbol)],
            ADD_CAPITAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_capital)],
            ADD_RISK: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_risk)],
            ADD_TF: [CallbackQueryHandler(process_add_tf, pattern='^tf_')],
        },
        fallbacks=[CommandHandler('start', start)],
        per_message=False
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ النظام المؤسسي جاهز بالكامل.")
    # استخدام drop_pending_updates=True لتجنب تعارض النسخ وتنظيف التحديثات القديمة
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
