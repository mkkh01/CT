import os
import sys
import asyncio
import time
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
from Core.redis_manager import redis_client
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
    from Core.trade_monitor import TradeMonitor # Import here to avoid circular dependency
    from Core.shadow_monitor import ShadowMonitor # Import here to avoid circular dependency
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
        
        # انتظار اكتمال الـ Warm-up: يجب أن ينتظر حتى يصبح لكل رمز بيانات كافية
        logger.info("⏳ [WARMUP] انتظار اكتمال الكاش لكل الرموز...")
        while not await state_manager.is_cache_warmed_up():
            await asyncio.sleep(5) # التحقق كل 5 ثواني
        
        state_manager.set_state(SystemState.READY)
        logger.info("✅ [SYSTEM] النظام جاهز بالكامل والبيانات مكتملة في الكاش.")
    except Exception as e:
        state_manager.set_state(SystemState.ERROR)
        logger.error(f"❌ [CRITICAL] فشل إطلاق المهام الخلفية: {e}")

async def post_init(app: Application):
    # تنظيف صارم لأي Webhook قديم لضمان عمل الـ Polling بدون تعارض (Conflict)
    await app.bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2) # تأخير قصير لضمان قطع اتصال أي نسخة قديمة تماماً
    
    asyncio.create_task(start_background_tasks(app))
    logger.info("🗑️ [SYSTEM] تم تنظيف الجلسات القديمة وتجهيز الـ Startup Sequence.")

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
    
    # تشغيل Flask Webhook Server للحفاظ على الخدمة حية
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
    
    # تشغيل البوت باستخدام Polling لتجنب تضارب المنافذ
    # Flask يعمل على المنفذ 10000 و Polling يستقبل الرسائل من Telegram مباشرة
    logger.info("✅ [RUN] بدء تشغيل البوت بنظام الـ Polling.")
    app.run_polling()


if __name__ == "__main__":
    main()
