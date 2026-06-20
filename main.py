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
            cls._instance._stop_event = asyncio.Event()
            cls._instance._is_shutting_down = False
            logger.info("🆕 [SYSTEM] TradingApplication Instance Created (Singleton)")
        return cls._instance

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
        # تشغيل المهام الخلفية
        asyncio.create_task(self.start_background_tasks())

    async def shutdown(self):
        """إغلاق الموارد بشكل Graceful ومرتب"""
        if self._is_shutting_down:
            return
        
        self._is_shutting_down = True
        logger.info("🛑 [SHUTDOWN] بدء عملية الإغلاق الآمن...")
        self._stop_event.set()
        
        # 1. إلغاء المهام الخلفية أولاً
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
        try:
            from Core.event_queue import event_queue
            if event_queue.is_running:
                await event_queue.stop_workers()
        except Exception as e:
            logger.error(f"⚠️ [SHUTDOWN] خطأ أثناء إيقاف event_queue: {e}")
            
        # 2. إيقاف البوت بترتيب دقيق (Stop Polling -> Stop App -> Shutdown App)
        if self.app:
            try:
                if self.app.updater and self.app.updater.running:
                    logger.info("🛑 [SHUTDOWN] Polling Stopped")
                    await self.app.updater.stop()
                
                if self.app.running:
                    logger.info("🛑 [SHUTDOWN] Application Stopped")
                    await self.app.stop()
                
                logger.info("🛑 [SHUTDOWN] Application Shutdown")
                await self.app.shutdown()
            except Exception as e:
                logger.error(f"⚠️ [SHUTDOWN] خطأ أثناء إيقاف البوت: {e}")

        # 3. إغلاق قاعدة البيانات
        logger.info("🛑 [SHUTDOWN] إغلاق اتصال قاعدة البيانات...")
        await engine.dispose()
        logger.info("✅ [SHUTDOWN] تم إغلاق اتصال قاعدة البيانات.")
        
        logger.info("👋 [SHUTDOWN] Exit Complete")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # تجاهل أخطاء الـ Conflict أثناء الإغلاق لتقليل الضجيج
    if "Conflict" in str(context.error):
        logger.debug(f"ℹ️ [BOT] Conflict error suppressed during operation/shutdown.")
        return
    logger.error(f"⚠️ [BOT ERROR] {context.error}", exc_info=context.error)

async def run_app():
    """دالة تشغيل التطبيق مع إدارة دورة الحياة الصارمة"""
    trading_app = TradingApplication()
    
    # بناء التطبيق
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(trading_app.post_init).build()
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

    # تشغيل Flask في Thread منفصل (بدون إعادة تحميل)
    keep_alive(app)

    try:
        # 1. تهيئة قاعدة البيانات
        await init_db()
        
        # 2. دورة التشغيل الرسمية
        logger.info("🚀 [SYSTEM] Initializing Application...")
        await app.initialize()
        
        # 3. تنظيف الـ Webhook "قبل" البدء لضمان عدم وجود تضارب
        logger.info("🗑️ [SYSTEM] Cleaning up Webhooks...")
        await app.bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(1) # وقت قصير للتأكد من المعالجة في خوادم تليجرام
        
        logger.info("🚀 [SYSTEM] Starting Application...")
        await app.start()
        
        # 4. بدء الـ Polling مع حماية
        if app.updater:
            logger.info("🚀 [SYSTEM] Polling Started")
            await app.updater.start_polling(drop_pending_updates=True, stop_signals=None)
        
        # 5. الانتظار حتى إشارة الإغلاق
        while not trading_app._stop_event.is_set():
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"💥 [CRITICAL] خطأ في الحلقة الرئيسية: {e}", exc_info=True)
    finally:
        await trading_app.shutdown()

def main():
    logger.info("🚀 جاري إقلاع نظام التداول المؤسسي CT V5.1 (The Fox)... ")
    
    # استخدام loop واحد فقط ومنع إنشاء loops متعددة
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    trading_app = TradingApplication()
    
    def handle_exit(sig, frame):
        if not trading_app._is_shutting_down:
            logger.info(f"📥 [SIGNAL] Received signal {sig}, triggering shutdown...")
            # جدولة مهمة الإغلاق في الـ loop الفعال
            loop.call_soon_threadsafe(trading_app._stop_event.set)

    # تسجيل إشارات الإغلاق لـ Render (SIGTERM)
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    try:
        loop.run_until_complete(run_app())
    except Exception as e:
        logger.error(f"💥 [FATAL] {e}")
    finally:
        logger.info("🛑 [SYSTEM] Final Cleanup...")
        # لا نغلق الـ loop هنا للسماح لـ shutdown بالعمل
        # سيتم الخروج من البرنامج تلقائياً بعد انتهاء run_until_complete

if __name__ == "__main__":
    main()
