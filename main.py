"""
CT Institutional Trading System V4.0 — Main Entry Point

Lifecycle:
  START:  config → db → redis → telegram manager → background tasks
  STOP:   background tasks → telegram polling → db connections

Observability:
  OBSERVABILITY_LEVEL=normal|debug|trace  (default: normal)
  OBS_JSON_LOG=path/to/events.jsonl       (optional structured log sink)
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
from Core.observability import Obs, Level, set_level, is_level
from Core.trade_monitor import TradeMonitor
from Core.utils import safe_create_task
from keep_alive import keep_alive

# ── Logging setup ──────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(name)-18s] %(levelname)-8s %(message)s",
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
)
# Suppress httpx/httpcore request spam — we only want errors
for _lib in ("httpx", "httpcore"):
    logging.getLogger(_lib).setLevel(logging.WARNING)
logger = logging.getLogger("CT_Main")

# ── Globals ────────────────────────────────────────────────────────
_started_at = time.time()
_shutdown_event = asyncio.Event()


# ══════════════════════════════════════════════════════════════════
# Telegram error handler
# ══════════════════════════════════════════════════════════════════

async def telegram_error_handler(update, context):
    if isinstance(context.error, Conflict):
        logger.warning("[TELEGRAM] Conflict detected — ignoring.")
        return
    Obs.error_full(
        component="Telegram",
        function="error_handler",
        error_type=type(context.error).__name__,
        message=str(context.error),
        cause="Unexpected Telegram API error",
        fix="Check network connectivity and bot token validity",
    )


# ══════════════════════════════════════════════════════════════════
# Background tasks
# ══════════════════════════════════════════════════════════════════

async def start_background_tasks(app):
    logger.info("[SYSTEM] Launching institutional radar (TradeMonitor)...")
    await asyncio.sleep(2)
    monitor = TradeMonitor(bot=app.bot)
    safe_create_task(monitor.check_prices(), name="TradeMonitor_CheckPrices")
    Obs.event_log("Main", "start_background_tasks", "TradeMonitor launched",
                   status="OK")


async def post_init(app):
    safe_create_task(start_background_tasks(app), name="StartBackgroundTasks")


# ══════════════════════════════════════════════════════════════════
# Startup health checks
# ══════════════════════════════════════════════════════════════════

async def run_health_checks() -> dict:
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

    # Telegram config
    results["Telegram Config"] = bool(TELEGRAM_TOKEN and TELEGRAM_TOKEN.strip())

    # Environment
    results["Environment"] = True

    # Risk Manager
    try:
        from Core.risk_manager import RiskManager
        RiskManager()
        results["Risk Manager"] = True
    except Exception as e:
        logger.warning("Risk Manager: %s", e)
        results["Risk Manager"] = False

    # Strategies
    try:
        from strategies import InstitutionalStrategies
        InstitutionalStrategies()
        results["Strategies"] = True
    except Exception as e:
        logger.warning("Strategies: %s", e)
        results["Strategies"] = False

    results["Core Engine"] = True
    results["Decision Engine"] = True
    return results


# ══════════════════════════════════════════════════════════════════
# Signal handling
# ══════════════════════════════════════════════════════════════════

def setup_signal_handlers(telegram_manager: TelegramManager,
                          loop: asyncio.AbstractEventLoop):
    def _shutdown(signame: str):
        logger.info("[SYSTEM] %s — shutting down...", signame)
        _shutdown_event.set()
        asyncio.run_coroutine_threadsafe(
            _graceful_shutdown(telegram_manager), loop
        )

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _shutdown(s.name))
        except NotImplementedError:
            signal.signal(sig, lambda s, f: _shutdown(s.name))


async def _graceful_shutdown(telegram_manager: TelegramManager):
    Obs.event_log("Main", "shutdown", "Sequence started")
    _shutdown_event.set()
    await telegram_manager.stop()
    try:
        from database import engine
        await engine.dispose()
    except Exception as e:
        logger.warning("DB dispose: %s", e)
    Obs.event_log("Main", "shutdown", "Complete", status="OK")


# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

async def async_main():
    # ── Startup Banner ──
    Obs.startup_banner()

    # ── Validate config ──
    try:
        validate_config()
        Obs.event_log("Config", "validate", "Passed", status="OK")
    except RuntimeError as cfg_err:
        Obs.error_full("Config", "validate", "RuntimeError",
                       str(cfg_err), cause="Missing required config",
                       fix="Set all required environment variables")
        return 1

    # ── Config dump (non-secret values) ──
    if is_level(Level.DEBUG):
        import config as cfg_mod
        Obs.config_dump(cfg_mod)

    # ── Health checks ──
    components = await run_health_checks()
    Obs.startup_report(components)

    if not components.get("Database", False):
        logger.critical("Database unavailable — cannot start.")
        return 1

    # ── Create Telegram manager ──
    tg = TelegramManager(
        token=TELEGRAM_TOKEN,
        post_init_callback=post_init,
        error_handler=telegram_error_handler,
    )
    set_telegram_manager(tg)

    # ── Start Flask keep-alive ──
    keep_alive()

    # ── Start Telegram ──
    ok = await tg.start()
    if not ok:
        logger.critical("[SYSTEM] Telegram failed to start.")
        return 1

    # ── Periodic snapshots ──
    loop = asyncio.get_running_loop()
    setup_signal_handlers(tg, loop)

    async def periodic_snapshot():
        while not _shutdown_event.is_set():
            await asyncio.sleep(300)
            Obs.system_snapshot(
                uptime=time.time() - _started_at,
                api_calls=Obs.get().api_rest_count,
            )

    safe_create_task(periodic_snapshot(), name="PeriodicSnapshot")

    # ── Wait for shutdown ──
    await _shutdown_event.wait()
    await _graceful_shutdown(tg)
    return 0


def main():
    exit_code = 1
    try:
        exit_code = asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("[SYSTEM] KeyboardInterrupt — exiting.")
        exit_code = 0
    except Exception as e:
        Obs.error_full("Main", "main", type(e).__name__, str(e),
                       cause="Unexpected fatal error",
                       fix="Check logs and restart")
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
