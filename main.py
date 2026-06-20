import os
import sys
import asyncio
import logging
import signal
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from config import TELEGRAM_TOKEN, setup_logging
from database import init_db, engine
from bot.handlers import (
    start, handle_message, process_add_symbol, process_add_capital, 
    process_add_risk, process_add_tf,
    ADD_SYMBOL, ADD_CAPITAL, ADD_RISK, ADD_TF
)
from Core.trade_monitor import TradeMonitor
from Core.shadow_monitor import ShadowMonitor
from Core.state_manager import state_manager, SystemState
from Core.process_lock import ProcessLock
from Core.event_queue import event_queue
from keep_alive import keep_alive

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
            cls._instance._is_shutting_down = False
            cls._instance._background_tasks = set()
            cls._instance._loop = None
        return cls._instance

    async def start_background_tasks(self, app: Application):
        if state_manager.state != SystemState.INIT: return

        try:
            state_manager.set_state(SystemState.WARMING_UP)
            self.trade_monitor = TradeMonitor(bot=app.bot)
            self.shadow_monitor = ShadowMonitor(bot=app.bot)
            
            # Start Background Supervisors with factory-like restartability
            self._create_supervised_task(self.trade_monitor.check_prices, "TradeMonitor")
            self._create_supervised_task(self.shadow_monitor.check_shadow_trades, "ShadowMonitor")
            
            # Warmup with timeout
            await state_manager.wait_for_ready(timeout=120)
            
            if state_manager.state != SystemState.READY:
                state_manager.set_state(SystemState.READY)
                logger.info("✅ [SYSTEM] Forced READY mode after warmup.")
                
        except Exception as e:
            logger.error(f"❌ [STARTUP ERROR] {e}")
            state_manager.set_state(SystemState.READY)

    def _create_supervised_task(self, coro_func, name):
        task = asyncio.create_task(self._task_supervisor(coro_func, name), name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _task_supervisor(self, coro_func, name):
        """Crash shield and auto-restart supervisor with function factory"""
        consecutive_failures = 0
        while not self._is_shutting_down:
            try:
                logger.info(f"🛡️ [SUPERVISOR] Starting task: {name}")
                await coro_func()
                # If it finishes normally, we check if we should restart
                if self._is_shutting_down: break
                logger.warning(f"⚠️ [SUPERVISOR] Task {name} finished unexpectedly. Restarting...")
            except asyncio.CancelledError:
                logger.info(f"🛑 [SUPERVISOR] Task {name} cancelled.")
                break
            except Exception as e:
                consecutive_failures += 1
                delay = min(10 * consecutive_failures, 60)
                logger.error(f"💥 [CRASH] Task {name} failed: {e}. Restarting in {delay}s...")
                await asyncio.sleep(delay)
            else:
                consecutive_failures = 0
            await asyncio.sleep(1)

    async def post_init(self, app: Application):
        # 1. Clear Webhook to prevent 409 Conflict
        try:
            logger.info("🧹 [SYSTEM] Clearing Telegram Webhook...")
            await app.bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logger.error(f"❌ [SYSTEM] Failed to delete webhook: {e}")
            
        # 2. Init DB
        await init_db()
        
        # 3. Start Tasks
        self._loop = asyncio.get_running_loop()
        asyncio.create_task(self.start_background_tasks(app))

    async def post_shutdown(self, app: Application):
        if self._is_shutting_down: return
        self._is_shutting_down = True
        
        logger.info("🛑 [SHUTDOWN] Initiating graceful shutdown...")
        
        if self.trade_monitor:
            self.trade_monitor.is_running = False
        if self.shadow_monitor:
            self.shadow_monitor.is_running = False
            
        await event_queue.stop_workers()
        
        # Cancel all background tasks
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        
        try:
            await engine.dispose()
        except: pass
        logger.info("👋 [SHUTDOWN] System closed.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "Conflict" in str(context.error):
        logger.warning("⚠️ [BOT] Conflict detected. Another instance might be running.")
        return
    logger.error(f"⚠️ [BOT ERROR] {context.error}")

def main():
    # Use a more unique lock file to prevent collision on shared /tmp
    lock_file = f"/tmp/ct_bot_{TELEGRAM_TOKEN.split(':')[0]}.lock"
    lock = ProcessLock(lock_file=lock_file)
    
    if not lock.acquire():
        logger.critical("🚨 [SYSTEM] Fatal: Another instance is already running. Exiting.")
        sys.exit(1)
        
    try:
        trading_app = TradingApplication()
        app = Application.builder() \
            .token(TELEGRAM_TOKEN) \
            .post_init(trading_app.post_init) \
            .post_shutdown(trading_app.post_shutdown) \
            .build()
        
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

        keep_alive(app)

        logger.info("🚀 [SYSTEM] Starting Bot Polling...")
        app.run_polling(drop_pending_updates=True, close_loop=False)
        
    except Exception as e:
        logger.critical(f"🚨 [SYSTEM] Global crash: {e}")
    finally:
        lock.release()

if __name__ == "__main__":
    main()
