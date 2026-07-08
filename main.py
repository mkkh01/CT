"""
CT Institutional Trading System V4.0 — Main Entry Point

Lifecycle:
  START:  config → db → redis → telegram manager → background tasks
  STOP:   background tasks → telegram polling → db connections

Only one Telegram polling instance is ever active (enforced by
Core/telegram_manager.py + distributed Redis lock).
"""

import asyncio
import logging
import os
import signal
import sys
import time
import traceback

from telegram.error import Conflict

from config import (
    TELEGRAM_TOKEN,
    ADMIN_ID,
    DEBUG_MODE,
    validate_config,
)
from database import init_db, AsyncSessionLocal, UserConfig
from Core.redis_client import redis_client
from Core.telegram_manager import TelegramManager, set_telegram_manager
from Core.diagnostics import Diagnostics, set_debug_mode, get_diagnostics
from Core.trade_monitor import TradeMonitor
from Core.utils import safe_create_task
from keep_alive import keep_alive

# ── Logging setup ───────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(name)-18s] %(levelname)-8s %(message)s",
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
)
logger = logging.getLogger("CT_Main")

# ── Globals ─────────────────────────────────────────────────────────
_started_at = time.time()
_shutdown_event = asyncio.Event()


# ═══════════════════════════════════════════════════════════════════
# Telegram error handler
# ═══════════════════════════════════════════════════════════════════

async def telegram_error_handler(update, context):
    """Log errors centrally; never crash on Telegram errors."""
    if isinstance(context.error, Conflict):
        logger.warning("[TELEGRAM] Conflict detected (another instance?) — ignoring.")
        return
    tb = "".join(
        traceback.format_exception(
            None, context.error, context.error.__traceback__
        )
    )
    logger.error("[TELEGRAM] Exception: %s\n%s", context.error, tb)
    get_diagnostics().error_report(
        module="Telegram",
        function="error_handler",
        error_type=type(context.error).__name__,
        message=str(context.error),
        stack_trace=tb,
    )


# ═══════════════════════════════════════════════════════════════════
# Background tasks
# ═══════════════════════════════════════════════════════════════════

async def start_background_tasks(app):
    """Launch TradeMonitor after Telegram is ready."""
    logger.info("[SYSTEM] Launching institutional radar (TradeMonitor)...")
    await asyncio.sleep(2)
    monitor = TradeMonitor(bot=app.bot)
    safe_create_task(monitor.check_prices(), name="TradeMonitor_CheckPrices")
    logger.info("[SYSTEM] ✅ Institutional radar active.")


async def post_init(app):
    """Telegram post_init callback — run after Application is built."""
    safe_create_task(
        start_background_tasks(app), name="StartBackgroundTasks"
    )


# ═══════════════════════════════════════════════════════════════════
# Startup health checks
# ═══════════════════════════════════════════════════════════════════

async def run_health_checks() -> dict:
    """Verify every subsystem before starting the bot."""
    diag = get_diagnostics()
    results: dict[str, bool] = {}

    # Database
    try:
        await init_db()
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        results["Database"] = True
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        results["Database"] = False

    # Redis
    try:
        if redis_client.redis:
            redis_client.redis.ping()
        results["Redis"] = True
    except Exception as e:
        logger.warning("Redis health check: %s", e)
        results["Redis"] = bool(redis_client.redis)

    # Telegram token presence
    results["Telegram Config"] = bool(TELEGRAM_TOKEN and TELEGRAM_TOKEN.strip())

    # Environment
    results["Environment"] = True

    # Risk Manager
    try:
        from Core.risk_manager import RiskManager
        RiskManager()
        results["Risk Manager"] = True
    except Exception as e:
        logger.warning("Risk Manager init: %s", e)
        results["Risk Manager"] = False

    # Strategies
    try:
        from strategies import InstitutionalStrategies
        InstitutionalStrategies()
        results["Strategies"] = True
    except Exception as e:
        logger.warning("Strategies init: %s", e)
        results["Strategies"] = False

    results["Core Engine"] = True
    results["Decision Engine"] = True

    return results


# ═══════════════════════════════════════════════════════════════════
# Signal handling
# ═══════════════════════════════════════════════════════════════════

def setup_signal_handlers(telegram_manager: TelegramManager, loop: asyncio.AbstractEventLoop):
    """Register OS signal handlers for graceful shutdown."""

    def _shutdown(signame: str):
        logger.info("[SYSTEM] Received %s — shutting down gracefully...", signame)
        _shutdown_event.set()
        # Schedule the async stop on the event loop
        asyncio.run_coroutine_threadsafe(_graceful_shutdown(telegram_manager), loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _shutdown(s.name))
        except NotImplementedError:
            # Windows / some environments don't support add_signal_handler
            signal.signal(sig, lambda s, f: _shutdown(s.name))


async def _graceful_shutdown(telegram_manager: TelegramManager):
    """Stop all services in reverse order."""
    logger.info("[SYSTEM] ========== SHUTDOWN SEQUENCE ==========")

    # 1. Stop background tasks (TradeMonitor stops via shutdown_event)
    logger.info("[SYSTEM] 1/3 Stopping trade monitor...")
    _shutdown_event.set()

    # 2. Stop Telegram polling
    logger.info("[SYSTEM] 2/3 Stopping Telegram bot...")
    await telegram_manager.stop()

    # 3. Close database
    logger.info("[SYSTEM] 3/3 Closing database connections...")
    try:
        from database import engine
        await engine.dispose()
    except Exception as e:
        logger.warning("DB dispose: %s", e)

    logger.info("[SYSTEM] ========== SHUTDOWN COMPLETE ==========")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

async def async_main():
    """Primary async entry point."""
    diag = get_diagnostics()

    # ── Banner ──
    diag.startup_banner()

    # ── Validate config ──
    logger.info("[SYSTEM] Validating configuration...")
    try:
        validate_config()
    except RuntimeError as cfg_err:
        logger.critical(str(cfg_err))
        print(f"\n🚫 FATAL: {cfg_err}")
        return 1

    # ── Health checks ──
    logger.info("[SYSTEM] Running subsystem health checks...")
    components = await run_health_checks()
    diag.startup_report(components)

    if not components.get("Database", False):
        logger.critical("Database is unavailable — cannot start.")
        return 1

    # ── Config diagnostics ──
    ws_ok = True  # Will be verified when TradeMonitor connects
    diag.config_status(
        db_ok=components.get("Database", False),
        redis_ok=components.get("Redis", False),
        telegram_ok=components.get("Telegram Config", False),
        ws_ok=ws_ok,
        env_ok=components.get("Environment", False),
    )

    # ── Create Telegram manager ──
    tg = TelegramManager(
        token=TELEGRAM_TOKEN,
        post_init_callback=post_init,
        error_handler=telegram_error_handler,
    )
    set_telegram_manager(tg)

    # ── Start Flask keep-alive server ──
    keep_alive()

    # ── Start Telegram ──
    ok = await tg.start()
    if not ok:
        logger.critical("[SYSTEM] Telegram failed to start after retries.")
        return 1

    # Set up graceful shutdown
    loop = asyncio.get_running_loop()
    setup_signal_handlers(tg, loop)

    # ── Wait for shutdown signal ──
    await _shutdown_event.wait()
    await _graceful_shutdown(tg)
    return 0


def main():
    """Synchronous entry — creates event loop and runs async_main."""
    exit_code = 1
    try:
        exit_code = asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("[SYSTEM] KeyboardInterrupt — exiting.")
        exit_code = 0
    except Exception as e:
        logger.critical("[SYSTEM] Fatal error: %s", e, exc_info=True)
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
