import os
import sys
import asyncio
import logging
from keep_alive import keep_alive
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, AsyncSessionLocal, UserConfig
from bot.handlers import (
    start, handle_message, process_add_symbol, process_add_capital, 
    process_add_risk, process_add_tf,
    ADD_SYMBOL, ADD_CAPITAL, ADD_RISK, ADD_TF
)
from Core.trade_monitor import TradeMonitor
from Core.shadow_monitor import ShadowMonitor

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
    """تشغيل الرادار المؤسسي والمراقبة والتعلم الخفي مع معالجة الأخطاء"""
    try:
        await asyncio.sleep(15) # تأخير كافٍ لضمان استقرار البوت
        
        # تشغيل مراقب التداول الحقيقي
        monitor = TradeMonitor(bot=app.bot)
        asyncio.create_task(monitor.check_prices())
        
        # تشغيل مراقب التعلم الخفي (Shadow Monitor)
        shadow = ShadowMonitor(bot=app.bot)
        asyncio.create_task(shadow.check_shadow_trades())
        
        logger.info("📡 [SYSTEM] تم إطلاق الرادار المؤسسي ونظام التعلم الخفي.")
    except Exception as e:
        logger.error(f"❌ [CRITICAL] فشل إطلاق المهام الخلفية: {e}")

async def post_init(app: Application):
    # تنظيف أي Webhook قديم وإضافة تأخير لقطع الاتصال عن أي نسخة أخرى
    await app.bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(3)
    asyncio.create_task(start_background_tasks(app))
    logger.info("🗑️ [SYSTEM] تم تنظيف الجلسات القديمة وتجهيز المهام الخلفية.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تسجيل الأخطاء التي تحدث أثناء تشغيل البوت"""
    logger.error(f"⚠️ [BOT ERROR] {context.error}")

def main():
    logger.info("🚀 جاري إقلاع نظام التداول المؤسسي CT V5.0 (The Fox)... ")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    
    # بناء التطبيق مع إعدادات أمان إضافية
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # إضافة معالج الأخطاء
    app.add_error_handler(error_handler)
    
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
    
    # تشغيل البوت مع إعدادات محسنة لتقليل تضارب الجلسات
    app.run_polling(
        drop_pending_updates=True, 
        close_loop=False
    )

if __name__ == "__main__":
    main()
