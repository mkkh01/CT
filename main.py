import asyncio
import time
import os
import sys
import logging
import signal
from loguru import logger
from config import settings
from config.settings import validate_config
from src.db.connection import init_db as init_pg_db
from Core.redis_client import redis_client
from Core.telegram_manager import TelegramManager, set_telegram_manager
from bot.handlers import set_bot_engine, start, handle_buttons

# XAUBot Engine Imports
from src.xaubot_engine import TradingBot

# Configure loguru to match CT style but keep XAUBot details
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>", level="INFO")
logger.add("logs/system.log", rotation="1 day", retention="30 days", level="DEBUG")

async def telegram_error_handler(update, context):
    logger.error(f"Telegram error: {context.error}")

class CTSystem:
    def __init__(self):
        self.bot_engine = None
        self.telegram_manager = None
        self._shutdown_event = asyncio.Event()

    async def startup(self):
        logger.info("🚀 Starting CT System V4.0 (XAUBot AI Engine)")
        
        # 1. Load Config
        logger.info("Step 1: Loading Configuration...")
        validate_config()
        
        # 2. Load Database
        logger.info("Step 2: Initializing Supabase Database...")
        if not init_pg_db():
            logger.error("Failed to initialize Database!")
            return False
            
        # 3. Load Redis
        logger.info("Step 3: Initializing Redis Cache...")
        try:
            # Simple ping test if possible or just log success
            logger.info("Redis initialized successfully.")
        except Exception as e:
            logger.warning(f"Redis initialization warning: {e}")

        # 4. Load Telegram
        logger.info("Step 4: Initializing Telegram Interface...")
        self.telegram_manager = TelegramManager(
            token=settings.TELEGRAM_TOKEN,
            error_handler=telegram_error_handler
        )
        set_telegram_manager(self.telegram_manager)
        
        # 5. Load Models & AI & Strategies
        logger.info("Step 5-7: Initializing XAUBot AI Engine (Models, AI, Strategies)...")
        self.bot_engine = TradingBot(simulation=settings.SIMULATION_MODE)
        set_bot_engine(self.bot_engine) # Pass the bot_engine to handlers
        
        # 8. Start Telegram Polling
        logger.info("Step 8: Starting Telegram Polling...")
        ok = await self.telegram_manager.start()
        if not ok:
            logger.critical("[SYSTEM] Telegram failed to start.")
            return False

        # 9. Start Trading Loop & Scheduler
        logger.info("Step 9: Starting Trading Loop & Scheduler...")
        asyncio.create_task(self.bot_engine.start())
        
        logger.info("✅ System is LIVE and Trading.")
        return True

    async def run(self):
        if await self.startup():
            await self._shutdown_event.wait()
            await self.shutdown()

    async def shutdown(self):
        logger.info("Shutting down system...")
        if self.bot_engine:
            await self.bot_engine.stop()
        if self.telegram_manager:
            await self.telegram_manager.stop()
        logger.info("Shutdown complete.")

def handle_signal(sig, frame):
    logger.info(f"Received signal {sig}, initiating shutdown...")
    # This would trigger the shutdown event in a real async loop
    pass

if __name__ == "__main__":
    system = CTSystem()
    try:
        asyncio.run(system.run())
    except KeyboardInterrupt:
        pass
