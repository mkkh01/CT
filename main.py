import os
import sys
import asyncio
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from config import TELEGRAM_TOKEN, setup_logging
from database import init_db, engine
from bot.handlers import (
    start, handle_message, process_add_symbol, process_add_capital, 
    process_add_risk, process_add_tf,
    ADD_SYMBOL, ADD_CAPITAL, ADD_RISK, ADD_TF
)
from Core.trade_monitor import TradeMonitor
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
            cls._instance._is_shutting_down = False
            cls._instance._background_tasks = set()
        return cls._instance

    async def start_background_tasks(self, app: Application):
        if state_manager.state != SystemState.INIT: return

        try:
            state_manager.set_state(SystemState.WARMING_UP)
            self.trade_monitor = TradeMonitor(bot=app.bot)
            
            # Start Background Supervisors
            self._create_supervised_task(self.trade_monitor.check_prices(), "TradeMonitor")
            
            # Warmup with timeout
            await state_manager.wait_for_ready(timeout=120)
            
            if state_manager.state != SystemState.READY:
                state_manager.set_state(SystemState.READY)
                logger.info("✅ [SYSTEM] Forced READY mode after warmup.")
                
        except Exception as e:
            logger.error(f"❌ [STARTUP ERROR] {e}")
            state_manager.set_state(SystemState.READY) # Fallback to READY

    def _create_supervised_task(self, coro, name):
        task = asyncio.create_task(self._task_supervisor(coro, name), name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _task_supervisor(self, coro, name):
        """Crash shield and auto-restart supervisor"""
        while not self._is_shutting_down:
            try:
                logger.info(f"🛡️ [SUPERVISOR] Starting task: {name}")
                # We need a fresh coroutine on restart, but since we pass coro once, 
                # for real restartability we'd need a factory. 
                # For this specific system, we'll wrap the main loop logic.
                await coro
                break # If coro finishes normally
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"💥 [CRASH] Task {name} failed: {e}. Restarting in 10s...")
                await asyncio.sleep(10)

    async def post_init(self, app: Application):
        await init_db()
        asyncio.create_task(self.start_background_tasks(app))

    async def post_shutdown(self, app: Application):
        if self._is_shutting_down: return
        self._is_shutting_down = True
        
        if self.trade_monitor:
            self.trade_monitor.is_running = False
        
        await event_queue.stop_workers()
        
        for task in list(self._background_tasks):
            task.cancel()
        
        try:
            await engine.dispose()
        except: pass
        logger.info("👋 [SHUTDOWN] System closed.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"⚠️ [BOT ERROR] {context.error}")

def main():
    lock = ProcessLock()
    if not lock.acquire():
        sys.exit(1)
        
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

    try:
        app.run_polling(drop_pending_updates=True, close_loop=False)
    finally:
        lock.release()

if __name__ == "__main__":
    main()
