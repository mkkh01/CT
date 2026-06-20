import os
import sys
import asyncio
import logging
import signal
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from config import TELEGRAM_TOKEN, ADMIN_ID, setup_logging
from database import init_db, engine
from bot.handlers import (
    start, handle_message, process_add_symbol, process_add_capital, 
    process_add_risk, process_add_tf,
    ADD_SYMBOL, ADD_CAPITAL, ADD_RISK, ADD_TF
)
from Core.trade_monitor import TradeMonitor
from Core.shadow_monitor import ShadowMonitor
from Core.state_manager import state_manager, SystemState
from keep_alive import keep_alive

# إعداد نظام السجلات (Logging)
setup_logging()
logger = logging.getLogger(__name__)

class TradingApplication:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TradingApplication, cls).__new__(cls)
            cls._instance.app = None
            cls._instance.trade_monitor = None
            cls._instance.shadow_monitor = None
            cls._instance.tasks = []
            cls._instance._is_shutting_down = False
            logger.info("🆕 [SYSTEM] TradingApplication Instance Created (Singleton)")
        return cls._instance

    async def start_background_tasks(self, app: Application):
        """التحكم في دورة التشغيل: Connect -> Warm-up -> Ready"""
        try:
            state_manager.set_state(SystemState.WARMING_UP)
            logger.info("🕒 [STARTUP] بدء مرحلة الـ Warm-up لتجهيز الكاش...")
            
            self.trade_monitor = TradeMonitor(bot=app.bot)
            self.shadow_monitor = ShadowMonitor(bot=app.bot)
            
            # إنشاء المهام وتخزينها للإلغاء لاحقاً
            monitor_task = asyncio.create_task(self.trade_monitor.check_prices())
            shadow_task = asyncio.create_task(self.shadow_monitor.check_shadow_trades())
            self.tasks.extend([monitor_task, shadow_task])
            
            logger.info("⏳ [WARMUP] انتظار اكتمال الكاش لكل الرموز...")
            while not await state_manager.is_cache_warmed_up():
                await asyncio.sleep(5)
            
            state_manager.set_state(SystemState.READY)
            logger.info("✅ [SYSTEM] النظام جاهز بالكامل والبيانات مكتملة في الكاش.")
        except Exception as e:
            state_manager.set_state(SystemState.ERROR)
            logger.error(f"❌ [CRITICAL] فشل إطلاق المهام الخلفية: {e}", exc_info=True)

    async def post_init(self, app: Application):
        # 1. تهيئة قاعدة البيانات
        await init_db()
        # 2. تشغيل المهام الخلفية
        asyncio.create_task(self.start_background_tasks(app))
        logger.info("🚀 [SYSTEM] Application Post-Init Complete")

    async def post_shutdown(self, app: Application):
        """إغلاق الموارد بعد توقف البوت"""
        logger.info("🛑 [SHUTDOWN] بدء عملية الإغلاق النهائي...")
        
        # إلغاء المهام الخلفية
        if self.trade_monitor:
            self.trade_monitor.is_running = False
        if self.shadow_monitor:
            self.shadow_monitor.is_running = False
            
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
            
        # إغلاق قاعدة البيانات
        await engine.dispose()
        logger.info("👋 [SHUTDOWN] Resources Cleared.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "Conflict" in str(context.error):
        logger.warning("⚠️ [BOT] Conflict detected. Render might be overlapping instances.")
        return
    logger.error(f"⚠️ [BOT ERROR] {context.error}", exc_info=context.error)

def main():
    logger.info("🚀 جاري إقلاع نظام التداول المؤسسي CT V5.2 (The Fox)... ")
    
    trading_app = TradingApplication()
    
    # بناء التطبيق باستخدام النمط الرسمي لـ PTB v20+
    app = Application.builder() \
        .token(TELEGRAM_TOKEN) \
        .post_init(trading_app.post_init) \
        .post_shutdown(trading_app.post_shutdown) \
        .build()
    
    trading_app.app = app
    
    # إضافة المعالجات
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

    # تشغيل Flask للبقاء حياً على Render
    keep_alive(app)

    # تشغيل البوت باستخدام run_polling() وهي الطريقة الأكثر استقراراً
    # فهي تدير الـ Loop، الـ Signals (SIGTERM/SIGINT)، والـ Shutdown تلقائياً
    logger.info("🚀 [SYSTEM] Starting Polling Mode...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
