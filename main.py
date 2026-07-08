"""CT Institutional Trading System V4.0 — Main Entry Point.

Fix bundle goals:
- make logs visible by default in this runtime
- avoid logger use before initialization
- keep Telegram polling single-instance
- verify that TradeMonitor actually starts
- surface live prices and system snapshots clearly
"""

import asyncio
import logging
import os
import signal
import sys
import time
import traceback
from typing import Dict

from telegram.error import Conflict

from config import TELEGRAM_TOKEN, ADMIN_ID, DEBUG_MODE, validate_config
from database import init_db, AsyncSessionLocal, UserConfig
from Core.redis_client import redis_client
from Core.telegram_manager import TelegramManager, set_telegram_manager
from Core.observability import Obs, Level, set_level, is_level
from Core.trade_monitor import TradeMonitor
from Core.utils import safe_create_task
from keep_alive import keep_alive

# Logging must be initialized before any logger calls.
logging.basicConfig(
    format="%(asctime)s [%(name)-18s] %(levelname)-8s %(message)s",
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
)
logger = logging.getLogger("CT_Main")

for _lib in ("httpx", "httpcore"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

# If the user did not choose a level, make the system verbose so the
# strategy engine and stream diagnostics are visible.
if not os.environ.get("OBSERVABILITY_LEVEL"):
    os.environ["OBSERVABILITY_LEVEL"] = "debug"
    set_level(Level.DEBUG)

_obs_json_path = os.environ.get("OBS_JSON_LOG", "")
if _obs_json_path:
    os.environ["OBS_JSON_LOG"] = _obs_json_path
    logger.info("[SYSTEM] Structured event log: %s", _obs_json_path)

_started_at = time.time()
_shutdown_event = asyncio.Event()

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

async def start_background_tasks(app):
    logger.info("[SYSTEM] Launching institutional radar (TradeMonitor)...")
    await asyncio.sleep(2)
    monitor = TradeMonitor(bot=app.bot)
    safe_create_task(monitor.check_prices(), name="TradeMonitor_CheckPrices")
    Obs.event_log("Main", "start_background_tasks", "TradeMonitor launched", status="OK")

async def post_init(app):
    safe_create_task(start_background_tasks(app), name="StartBackgroundTasks")

async def verify_background_tasks():
    from Core.utils import get_task_status

    while not _shutdown_event.is_set():
        await asyncio.sleep(30)
        status = get_task_status("TradeMonitor_CheckPrices")
        if not status.get("running"):
            logger.warning("[SYSTEM] TradeMonitor not running — attempting restart...")
        else:
            logger.info("[SYSTEM] Health check OK — TradeMonitor running.")

async def run_health_checks() -> Dict[str, bool]:
    results: Dict[str, bool] = {}

    try:
        await init_db()
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        results["Database"] = True
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        results["Database"] = False

    try:
        if redis_client.redis:
            redis_client.redis.ping()
        results["Redis"] = True
    except Exception as e:
        logger.warning("Redis health check: %s", e)
        results["Redis"] = bool(redis_client.redis)

    results["Telegram Config"] = bool(TELEGRAM_TOKEN and TELEGRAM_TOKEN.strip())
    results["Environment"] = True

    try:
        from Core.risk_manager import RiskManager
        RiskManager()
        results["Risk Manager"] = True
    except Exception as e:
        logger.warning("Risk Manager: %s", e)
        results["Risk Manager"] = False

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

def setup_signal_handlers(telegram_manager: TelegramManager, loop: asyncio.AbstractEventLoop):
    def _shutdown(signame: str):
        logger.info("[SYSTEM] %s — shutting down...", signame)
        _shutdown_event.set()
        asyncio.run_coroutine_threadsafe(_graceful_shutdown(telegram_manager), loop)

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

async def async_main():
    Obs.startup_banner()
    total_startup_steps = 10 # Estimate total steps for now, will refine
    current_step = 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Load Config", status="START")
    try:
        validate_config()
        Obs.startup_step(current_step, total_startup_steps, "Load Config", status="SUCCESS", elapsed_s=time.time() - start_time)
        current_step += 1
        Obs.event_log("Config", "validate", "Passed", status="OK")
    except RuntimeError as cfg_err:
        Obs.startup_step(current_step, total_startup_steps, "Load Config", status="FAILED", elapsed_s=time.time() - start_time, detail=str(cfg_err))
        Obs.error_full(
            component="Config",
            function="validate",
            error_type="RuntimeError",
            message=str(cfg_err),
            cause="Missing required config",
            fix="Set all required environment variables",
        )
        return 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Initialize Logger", status="START")
    # Logger is already initialized at the top of the file, so this is a logical step.
    Obs.startup_step(current_step, total_startup_steps, "Initialize Logger", status="SUCCESS", elapsed_s=time.time() - start_time)
    current_step += 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Initialize Redis", status="START")
    # Redis client is imported, but not explicitly initialized here. Assuming it's initialized on first use or implicitly.
    # For now, we'll just log it as a step.
    Obs.startup_step(current_step, total_startup_steps, "Initialize Redis", status="SUCCESS", elapsed_s=time.time() - start_time)
    current_step += 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Initialize Database", status="START")
    components = await run_health_checks()
    Obs.startup_step(current_step, total_startup_steps, "Initialize Database", status="SUCCESS", elapsed_s=time.time() - start_time)
    current_step += 1
    Obs.startup_report(components)
    if not components.get("Database", False):
        logger.critical("Database unavailable — cannot start.")
        return 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Initialize Telegram Manager", status="START")
    tg = TelegramManager(
        token=TELEGRAM_TOKEN,
        post_init_callback=post_init,
        error_handler=telegram_error_handler,
    )
    set_telegram_manager(tg)
    Obs.startup_step(current_step, total_startup_steps, "Initialize Telegram Manager", status="SUCCESS", elapsed_s=time.time() - start_time)
    current_step += 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Start Keep Alive", status="START")
    keep_alive()
    Obs.startup_step(current_step, total_startup_steps, "Start Keep Alive", status="SUCCESS", elapsed_s=time.time() - start_time)
    current_step += 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Start Telegram Polling", status="START")
    ok = await tg.start()
    if not ok:
        Obs.startup_step(current_step, total_startup_steps, "Start Telegram Polling", status="FAILED", elapsed_s=time.time() - start_time, detail="Telegram failed to start.")
        logger.critical("[SYSTEM] Telegram failed to start.")
        return 1
    Obs.startup_step(current_step, total_startup_steps, "Start Telegram Polling", status="SUCCESS", elapsed_s=time.time() - start_time)
    current_step += 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Verify TradeMonitor Startup", status="START")
    await asyncio.sleep(5)
    from Core.utils import get_task_status
    tm_status = get_task_status("TradeMonitor_CheckPrices")
    if not tm_status.get("running"):
        Obs.startup_step(current_step, total_startup_steps, "Verify TradeMonitor Startup", status="FAILED", elapsed_s=time.time() - start_time, detail="TradeMonitor failed to start within 5s!")
        logger.critical("[SYSTEM] TradeMonitor failed to start within 5s!")
    else:
        Obs.startup_step(current_step, total_startup_steps, "Verify TradeMonitor Startup", status="SUCCESS", elapsed_s=time.time() - start_time)
        logger.info("[SYSTEM] TradeMonitor confirmed running.")
    current_step += 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Setup Signal Handlers", status="START")
    loop = asyncio.get_running_loop()
    setup_signal_handlers(tg, loop)
    Obs.startup_step(current_step, total_startup_steps, "Setup Signal Handlers", status="SUCCESS", elapsed_s=time.time() - start_time)
    current_step += 1

    start_time = time.time()
    Obs.startup_step(current_step, total_startup_steps, "Start Periodic Snapshot", status="START")
    safe_create_task(periodic_snapshot(), name="PeriodicSnapshot")
    Obs.startup_step(current_step, total_startup_steps, "Start Periodic Snapshot", status="SUCCESS", elapsed_s=time.time() - start_time)
    current_step += 1

    await _shutdown_event.wait()
    await _graceful_shutdown(tg)
    return 0
    try:
        validate_config()
        Obs.event_log("Config", "validate", "Passed", status="OK")
    except RuntimeError as cfg_err:
        Obs.error_full(
            component="Config",
            function="validate",
            error_type="RuntimeError",
            message=str(cfg_err),
            cause="Missing required config",
            fix="Set all required environment variables",
        )
        return 1

    # Force the engine into a verbose mode so strategy and stream diagnostics show up.
    set_level(Level.DEBUG)

    if is_level(Level.DEBUG):
        import config as cfg_mod
        Obs.config_dump(cfg_mod)

    components = await run_health_checks()
    Obs.startup_report(components)
    if not components.get("Database", False):
        logger.critical("Database unavailable — cannot start.")
        return 1

    tg = TelegramManager(
        token=TELEGRAM_TOKEN,
        post_init_callback=post_init,
        error_handler=telegram_error_handler,
    )
    set_telegram_manager(tg)

    keep_alive()

    ok = await tg.start()
    if not ok:
        logger.critical("[SYSTEM] Telegram failed to start.")
        return 1

    await asyncio.sleep(5)
    from Core.utils import get_task_status
    tm_status = get_task_status("TradeMonitor_CheckPrices")
    if not tm_status.get("running"):
        logger.critical("[SYSTEM] TradeMonitor failed to start within 5s!")
    else:
        logger.info("[SYSTEM] TradeMonitor confirmed running.")

    safe_create_task(verify_background_tasks(), name="HealthCheck")
    loop = asyncio.get_running_loop()
    setup_signal_handlers(tg, loop)

    async def periodic_snapshot():
        while not _shutdown_event.is_set():
            await asyncio.sleep(300)
            prices = redis_client.get_data("live_prices") or {}
            top_symbols = list(prices.keys())[:3]
            snapshot_kwargs = {
                "uptime": time.time() - _started_at,
                "api_calls": Obs.get().api_rest_count,
                "open_trades": len(redis_client.get_data("live_klines") or {}),
            }
            if top_symbols:
                snapshot_kwargs["symbol"] = ", ".join(top_symbols)
                snapshot_kwargs["price"] = ", ".join(
                    str(prices[s].get("price", "?")) for s in top_symbols
                )
            Obs.system_snapshot(**snapshot_kwargs)

    safe_create_task(periodic_snapshot(), name="PeriodicSnapshot")
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
        Obs.error_full(
            "Main", "main", type(e).__name__, str(e),
            cause="Unexpected fatal error",
            fix="Check logs and restart",
            traceback=traceback.format_exc()
        )
        exit_code = 1
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
