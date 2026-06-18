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

from Core.state_manager import state_manager, SystemState

async def start_background_tasks(app):
    """التحكم في دورة التشغيل: Connect -> Warm-up -> Ready"""
    try:
        state_manager.set_state(SystemState.WARMING_UP)
        logger.info("🕒 [STARTUP] بدء مرحلة الـ Warm-up (30 ثانية) لتجهيز الكاش...")
        
        # تشغيل مراقب التداول الحقيقي (سيبدأ بجمع البيانات فوراً)
        monitor = TradeMonitor(bot=app.bot)
        asyncio.create_task(monitor.check_prices())
        
        # تشغيل مراقب التعلم الخفي (Shadow Monitor)
        shadow = ShadowMonitor(bot=app.bot)
        asyncio.create_task(shadow.check_shadow_trades())
        
        # انتظار اكتمال الـ Warm-up
        await asyncio.sleep(state_manager.min_warmup_sec)
        
        state_manager.set_state(SystemState.READY)
        logger.info("✅ [SYSTEM] النظام جاهز بالكامل والبيانات مكتملة في الكاش.")
    except Exception as e:
        state_manager.set_state(SystemState.ERROR)
        logger.error(f"❌ [CRITICAL] فشل إطلاق المهام الخلفية: {e}")

async def post_init(app: Application):
    # إعداد الـ Webhook لضمان جلسة واحدة فقط (Render URL)
    webhook_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if webhook_url:
        full_url = f"{webhook_url}/webhook"
        await app.bot.set_webhook(url=full_url, drop_pending_updates=True)
        logger.info(f"🌐 [WEBHOOK] تم تفعيل الـ Webhook على: {full_url}")
    else:
        # Fallback لـ Polling في بيئة التطوير فقط مع تنظيف صارم
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.warning("⚠️ [SYSTEM] RENDER_EXTERNAL_URL غير موجود، استخدام Polling كبديل.")
    
    asyncio.create_task(start_background_tasks(app))
    logger.info("🗑️ [SYSTEM] تم تنظيف الجلسات وتجهيز الـ Startup Sequence.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تسجيل الأخطاء التي تحدث أثناء تشغيل البوت"""
    logger.error(f"⚠️ [BOT ERROR] {context.error}")

def main():
    logger.info("🚀 جاري إقلاع نظام التداول المؤسسي CT V5.0 (The Fox)... ")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    
    # بناء التطبيق
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # تشغيل Flask Webhook Server
    keep_alive(app)
    
    # إضافة معالجات الأوامر
    app.add_error_handler(error_handler)
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
    
    # تشغيل البوت: Webhook لبيئة الإنتاج، Polling للتطوير
    if os.environ.get("RENDER_EXTERNAL_URL"):
        logger.info("✅ [RUN] بدء تشغيل البوت بنظام الـ Webhook.")
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 10000)),
            url_path="webhook",
            webhook_url=f"{os.environ.get('RENDER_EXTERNAL_URL')}/webhook"
        )
    else:
        logger.info("✅ [RUN] بدء تشغيل البوت بنظام الـ Polling (بيئة تطوير).")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
