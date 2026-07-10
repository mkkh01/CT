import asyncio
import sys
import signal
from loguru import logger

from config.config import config
from Core.observability import setup_logging
from Core.redis_client import redis_client
from Core.telegram_manager import get_telegram_manager, set_telegram_manager
from bot.handlers import setup_handlers
from src.db.supabase_client import supabase_manager

async def shutdown(loop, signal=None):
    if signal:
        logger.info(f"Received exit signal {signal.name}...")
    logger.info("Shutting down...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

def handle_exception(loop, context):
    msg = context.get("exception", context["message"])
    logger.error(f"Caught exception: {msg}")
    asyncio.create_task(shutdown(loop))

async def main():
    # 1. Setup Logging
    setup_logging()
    logger.info("Starting CT Trading Bot...")

    # 2. Validate Config
    try:
        config.validate()
        logger.info("Configuration validated.")
    except Exception as e:
        logger.critical(f"Config validation failed: {e}")
        sys.exit(1)

    # 3. Initialize Components
    tm = get_telegram_manager()
    if tm.app:
        setup_handlers(tm.app)
        # استخدام Webhook بدلاً من Polling كما طلب المستخدم
        import config
        print(f"Starting Webserver on port {getattr(config, 'PORT', 10000)}...")
        await tm.start_webhook()
        await tm.send_admin("🚀 CT Bot is now online (Webhook Mode) and monitoring markets.")
    
    # 4. Load AI and Trading Engines (Simulated integration)
    logger.info("Loading AI Models and Trading Engine...")
    # from src.xaubot_engine import TradingBot
    # bot = TradingBot()
    # await bot.start()

    # 5. Keep alive
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(loop, signal=s)))
    loop.set_exception_handler(handle_exception)

    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
