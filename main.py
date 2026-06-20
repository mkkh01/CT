import os
import sys
import asyncio
import logging
import signal
from contextlib import asynccontextmanager
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
    def __init__(self):
        self.app = None
        self.trade_monitor = None
        self.shadow_monitor = None
        self.tasks = []
        self._stop_event = asyncio.Event()

    async def start_background_tasks(self):
        """التحكم في دورة التشغيل: Connect -> Warm-up -> Ready"""
        try:
            state_manager.set_state(SystemState.WARMING_UP)
            logger.info("🕒 [STARTUP] بدء مرحلة الـ Warm-up لتجهيز الكاش...")
            
            self.trade_monitor = TradeMonitor(bot=self.app.bot)
            self.shadow_monitor = ShadowMonitor(bot=self.app.bot)
            
            # إنشاء المهام وتخزينها للإلغاء لاحقاً
            monitor_task = asyncio.create_task(self.trade_monitor.check_prices())
            shadow_task = asyncio.create_task(self.shadow_monitor.check_shadow_trades())
            self.tasks.extend([monitor_task, shadow_task])
            
            logger.info("⏳ [WARMUP] انتظار اكتمال الكاش لكل الرموز...")
            while not await state_manager.is_cache_warmed_up() and not self._stop_event.is_set():
                await asyncio.sleep(5)
            
            if not self._stop_event.is_set():
                state_manager.set_state(SystemState.READY)
                logger.info("✅ [SYSTEM] النظام جاهز بالكامل والبيانات مكتملة في الكاش.")
        except Exception as e:
            state_manager.set_state(SystemState.ERROR)
            logger.error(f"❌ [CRITICAL] فشل إطلاق المهام الخلفية: {e}", exc_info=True)

    async def post_init(self, app: Application):
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("🗑️ [SYSTEM] تم تنظيف الجلسات القديمة.")
        asyncio.create_task(self.start_background_tasks())

    async def shutdown(self):
        """إغلاق الموارد بشكل Graceful"""
        logger.info("🛑 [SHUTDOWN] بدء عملية الإغلاق الآمن...")
        self._stop_event.set()
        
        # 1. إيقاف البوت يتم التعامل معه في run_app
        
        # 2. إلغاء المهام الخلفية
        if self.trade_monitor:
            self.trade_monitor.is_running = False
        if self.shadow_monitor:
            self.shadow_monitor.is_running = False
            
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
            logger.info("✅ [SHUTDOWN] تم إيقاف جميع المهام الخلفية.")
            
        # إيقاف معالجي الأحداث
        from Core.event_queue import event_queue
        if event_queue.is_running:
            await event_queue.stop_workers()
            
        # 3. إغلاق قاعدة البيانات
        logger.info("🛑 [SHUTDOWN] إغلاق اتصال قاعدة البيانات...")
        await engine.dispose()
        logger.info("✅ [SHUTDOWN] تم إغلاق اتصال قاعدة البيانات.")
        
        logger.info("👋 [SHUTDOWN] اكتمل الإغلاق بنجاح.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"⚠️ [BOT ERROR] {context.error}", exc_info=context.error)

def main():
    logger.info("🚀 جاري إقلاع نظام التداول المؤسسي CT V5.0 (The Fox)... ")
    
    trading_app = TradingApplication()
    
    # بناء التطبيق
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(trading_app.post_init).build()
    trading_app.app = app
    
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
    
    # تشغيل Flask Webhook Server
    keep_alive(app)
    
    # تشغيل البوت
    logger.info("✅ [RUN] بدء تشغيل البوت بنظام الـ Polling.")
    
    loop = asyncio.get_event_loop()
    
    # التعامل مع إشارات الإنهاء
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(trading_app.shutdown()))

    async def run_app():
        try:
            # تهيئة قاعدة البيانات أولاً
            await init_db()
            
            # تهيئة وتشغيل التطبيق يدوياً لضمان سياق آمن لـ HTTPX
            async with app:
                await app.initialize()
                await app.start()
                await app.updater.start_polling(drop_pending_updates=True)
                
                logger.info("✅ [RUN] البوت يعمل الآن بنظام الـ Polling.")
                
                # الانتظار حتى يتم إرسال إشارة الإيقاف
                while not trading_app._stop_event.is_set():
                    await asyncio.sleep(1)
                
                # إيقاف الـ polling
                if app.updater.running:
                    await app.updater.stop()
                if app.running:
                    await app.stop()
                await app.shutdown()
        except Exception as e:
            logger.error(f"💥 [CRITICAL] خطأ غير متوقع في الحلقة الرئيسية: {e}", exc_info=True)
        finally:
            if not trading_app._stop_event.is_set():
                await trading_app.shutdown()

    try:
        loop.run_until_complete(run_app())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"💥 [FATAL] {e}")
    finally:
        loop.close()

if __name__ == "__main__":
    main()
