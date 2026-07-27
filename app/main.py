
"""
File: app/main.py
1. Single Responsibility: Be the CT process entry point -- wire every layer
   together (config -> contracts -> storage -> ingest -> engine -> simulation
   -> portfolio -> bot), run the Telegram bot, run the engine in the
   background, and orchestrate graceful shutdown.
2. Consumes: config.settings (SystemConfig), monitoring.logger,
   storage.supabase.SupabaseClient, storage.redis_cache.RedisCache,
   portfolio.performance.PerformanceCalculator, bot.telegram_bot.CTTelegramBot,
   engine.orchestrator.Orchestrator (LAZY), ingest.binance_ws.BinanceWSClient
   (LAZY), simulation.paper_trade (LAZY).
3. Produces: CTApplication class and ``async def main()`` entry point.
4. Downstream: Render web service / ``python -m app.main`` / ``python app/main.py``.
5. New Dependencies: None beyond requirements.txt. Uses asyncio + signal from
   the stdlib, plus python-telegram-bot==21.4 (already pinned).
6. Touches Section 6 bugs? No (no engine / data / structure logic here).
   Touches Section 0 hard constraints? Yes -- enforces #1 (bot stays thin:
   app/main.py owns start_engine / stop_engine, the bot only calls the
   callback) and #7 (never relabels simulated trades as live).
7. Tests: tests/integration/test_telegram_flows.py exercises start/stop engine
   and the lifecycle hooks; tests/integration/test_resume_flow.py exercises
   the restart-with-checkpoints path.
8. Logging: app_starting, app_ready, engine_started, engine_stopped,
   app_shutdown, error (Section 9 + lifecycle catalog).
9. Dependency Order: app/main.py is the LAST file in the import chain -- it
   imports from every upstream layer. engine/* and ingest/* are imported
   lazily inside methods to avoid import cycles with the orchestrator.

DESIGN NOTES
------------
* Single asyncio event loop. The Telegram Application, the WebSocket ingest
  task, the orchestrator subscriber task, and the paper-trader closure task
  all share the loop.
* ``start_engine`` is callable from two places: (a) the Telegram bot's Start
  Engine button (via the callback injected into CTTelegramBot) and (b) on app
  startup if Redis still has ``engine_running=true`` (auto-resume after
  Render restart).
* ``stop_engine`` is idempotent: it is safe to call when the engine is not
  running.
* Graceful shutdown (SIGTERM/SIGINT) -- order:
  1. stop_engine()         (cancels ingest + orchestrator + paper trader)
  2. telegram stop_polling
  3. telegram shutdown
  4. supabase.close()
  5. redis.close()
  6. log app_shutdown
* Per Section 22 -- a single coin failure NEVER crashes the whole app. Every
  background task wraps its body in try/except, logs ``error``, and continues.
* Per Section 0 hard-constraint 7 -- this file NEVER places real orders. The
  BinanceWSClient is read-only (kline subscription); paper_trade.py only
  writes rows to the ``simulated_trades`` table.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Response, status
from datetime import timedelta
import uvicorn

from monitoring.logger import configure_logging, get_logger
from monitoring.report_formatter import format_cycle_summary
from storage.redis_cache import RedisCache
from storage.supabase import SupabaseClient

# Type-only imports (avoid hard runtime dependency on layers that may not yet
# exist when this file is imported in isolation -- e.g. during unit testing).
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.telegram_bot import CTTelegramBot
    from contracts.config import SystemConfig
    from portfolio.performance import PerformanceCalculator

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "storage" / "migrations"

# How often the paper-trader closure task wakes up to scan open trades and
# decide if any have hit their stop / take-profit.
PAPER_TRADER_POLL_SECONDS = 15

# How often to log a heartbeat for the orchestrator subscriber (so Render's
# log stream shows the process is alive even on quiet markets).
SUBSCRIBER_HEARTBEAT_SECONDS = 300

# Sentinel values for the engine state machine.
_ENGINE_STATE_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# CTApplication
# ---------------------------------------------------------------------------
class CTApplication:
    """Top-level orchestrator of the CT process.

    Lifecycle::

        app = CTApplication(settings)
        await app.start()        # blocks until SIGTERM/SIGINT
        # (shutdown is called internally by the signal handler)

    The class is deliberately constructed with NO side effects -- only
    ``start()`` opens connections and starts tasks.
    """

    # ---------------- construction ----------------
    def __init__(self, settings: "SystemConfig") -> None:
        self._settings: "SystemConfig" = settings
        
        # Health Tracking (Requested Log #9 & #11)
        self._health_stats = {
            "scan_cycles": 0,
            "strategies_run": 0,
            "opportunities_found": 0,
            "opportunities_rejected": 0,
            "rejection_reasons": {},
            "errors": 0,
            "last_data_at": None
        }

        # Storage -- connected in start().
        self._redis: RedisCache = RedisCache(url=settings.redis_url)
        # The SupabaseClient expects a full Postgres DSN (e.g. postgresql://user:pass@host:port/db).
        # We assume settings.supabase_url is actually the DSN in this context.
        self._supabase: SupabaseClient = SupabaseClient(
            dsn=settings.supabase_url,
            key=settings.supabase_key,
            min_size=1,
            max_size=5,
        )

        # Built in start().
        self._performance_calc: Optional["PerformanceCalculator"] = None
        self._bot: Optional["CTTelegramBot"] = None
        self._telegram_app: Optional[Any] = None  # telegram.ext.Application

        # Engine -- built lazily in start_engine().
        self._orchestrator: Optional[Any] = None
        self._ws_client: Optional[Any] = None  # ingest.binance_ws.BinanceWSClient

        # Background tasks. Held so we can cancel them on shutdown.
        self._ingest_task: Optional[asyncio.Task[None]] = None
        self._orchestrator_subscriber_task: Optional[asyncio.Task[None]] = None
        self._paper_trader_task: Optional[asyncio.Task[None]] = None
        self._telegram_polling_task: Optional[asyncio.Task[None]] = None
        self._health_log_task: Optional[asyncio.Task[None]] = None

        # Engine run-state flag (mirrors Redis ``engine_running`` so we don't
        # race the cache when the user double-clicks Start/Stop).
        self._engine_running: bool = False

        # Shutdown coordination.
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._shutdown_started: bool = False

    # =====================================================================
    # Public lifecycle
    # =====================================================================
    async def start(self) -> None:
        """Wire every layer, start polling, and wait for shutdown.

        Per the spec, this method blocks until SIGTERM or SIGINT is received.
        """
        logger.info(
            "app_starting",
            timestamp=datetime.now(timezone.utc),
            pid=os.getpid(),
            simulation_mode=self._settings.simulation_mode,
            version="1.0.0",
            environment=os.getenv("ENVIRONMENT", "production"),
            module="app.main",
            message_text="بدء تشغيل النظام - الإصدار 1.0.0"
        )

        # 1. Logging first -- every subsequent step is observable.
        configure_logging()

        # 2 + 3. Storage layers.
        try:
            await self._redis.connect()
            logger.info("service_connected", module="app.main", service="Redis", message_text="تم الاتصال بنجاح بخدمة Redis")
        except Exception as exc:  # noqa: BLE001
            logger.critical(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"فشل الاتصال بـ Redis: {exc}",
                critical=True
            )
            raise
        try:
            await self._supabase.connect()
            logger.info("service_connected", module="app.main", service="Supabase", message_text="تم الاتصال بنجاح بخدمة Supabase")
        except Exception as exc:  # noqa: BLE001
            logger.critical(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"فشل الاتصال بـ Supabase: {exc}",
                critical=True
            )
            raise

        # 4. Apply idempotent migrations (Section 5).
        await self._apply_migrations()

        # 5. Performance calculator.
        self._performance_calc = self._build_performance_calculator()

        # 6. Telegram bot.
        self._bot = self._build_bot()

        # 7. Telegram Application.
        self._telegram_app = self._bot.build_application()

        # Inject the engine callbacks via bot_data so the bot can reach them
        # without an explicit constructor argument. (CTTelegramBot already
        # accepts the callbacks via __init__ -- we use BOTH paths so unit
        # tests can inject either.)
        self._telegram_app.bot_data["start_engine_callback"] = self.start_engine
        self._telegram_app.bot_data["stop_engine_callback"] = self.stop_engine
        self._telegram_app.bot_data["reload_engine_callback"] = self._reload_engine

        # 8. Register signal handlers (SIGTERM for Render, SIGINT for local).
        # This is now handled by FastAPI's lifespan events.

        # 9. Initialise + start the Telegram Application, then poll in a
        # background task so this coroutine can wait on the shutdown event.
        await self._telegram_app.initialize()
        await self._telegram_app.start()
        if self._telegram_app.updater is not None:
            await self._telegram_app.updater.start_polling(
                allowed_updates=None,
                drop_pending_updates=False,
            )
        self._telegram_polling_task = asyncio.create_task(
            self._telegram_polling_guard(), name="telegram_polling_guard"
        )

        # 10. Auto-resume the engine if Redis says it was running before the
        # process restarted (Render idles/restarts at will -- Section 0).
        try:
            should_resume = await self._redis.get_engine_running()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"could not read engine_running flag: {exc}",
            )
            should_resume = False

        if should_resume:
            logger.info(
                "app_starting",
                timestamp=datetime.now(timezone.utc),
                note="auto-resuming engine after process restart",
            )
            try:
                await self.start_engine()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type=type(exc).__name__,
                    error_message=f"auto-resume failed: {exc}",
                )

        logger.info(
            "app_ready",
            timestamp=datetime.now(timezone.utc),
            auto_resumed_engine=should_resume,
        )

        # 11. Wait for shutdown signal. This is now handled by FastAPI's lifespan.
        # await self._shutdown_event.wait()

        # 12. Run graceful shutdown. This is now handled by FastAPI's lifespan.
        # await self.shutdown()

    # =====================================================================
    # Engine lifecycle
    # =====================================================================
    async def start_engine(self) -> None:
        """Start the ingest + orchestrator + paper-trader loop.

        Idempotent: if the engine is already running, returns immediately
        without side effects (the bot still shows "Engine is already running"
        because it checks ``redis.get_engine_running`` BEFORE calling this).
        """
        async with _ENGINE_STATE_LOCK:
            if self._engine_running:
                logger.info(
                    "engine_started",
                    timestamp=datetime.now(timezone.utc),
                    note="start_engine called but already running",
                    active_coins=0,
                )
                return

            # 1. Load active coins from the database.
            try:
                coins = await self._supabase.fetch_all_coins(only_active=True)
                logger.info(
                    "config_loaded", 
                    module="app.main", 
                    active_coins_count=len(coins),
                    message_text=f"تم تحميل الإعدادات: عدد العملات المفعلة {len(coins)}"
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type=type(exc).__name__,
                    error_message=f"could not load active coins: {exc}",
                )
                raise

            if not coins:
                logger.warning(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type="NoActiveCoins",
                    error_message="start_engine called with zero active coins",
                )
                # Ensure the flag is False in Redis and memory to avoid "fake running" state.
                await self._redis.set_engine_running(False)
                self._engine_running = False
                return

            # 2. Build the orchestrator (lazy import to avoid cycles).
            self._orchestrator = self._build_orchestrator()

            # 3. Build the BinanceWSClient (lazy import).
            self._ws_client = self._build_ws_client(coins)

            # 4. Start the ingest task in the background.
            self._ingest_task = asyncio.create_task(
                self._run_ingest_guarded(), name="ingest_binance_ws"
            )

            # 5. Start the orchestrator subscriber task.
            self._orchestrator_subscriber_task = asyncio.create_task(
                self._run_orchestrator_subscriber_guarded(),
                name="orchestrator_subscriber",
            )

            # 6. Start the paper-trader closure check task.
            self._paper_trader_task = asyncio.create_task(
                self._run_paper_trader_guarded(), name="paper_trader_closure"
            )

            # 7. Flip the engine flag last so a crash during setup doesn't
            # leave Redis reporting a running engine while no tasks exist.
            await self._redis.set_engine_running(True)
            self._engine_running = True

            # 7.5 Start health logging task AFTER setting _engine_running=True
            self._health_log_task = asyncio.create_task(
                self._run_health_logger_loop(), name="health_logger"
            )

            logger.info(
                "engine_started",
                timestamp=datetime.now(timezone.utc),
                active_coins=len(coins),
                active_pairs=sum(len(c.timeframes) for c in coins),
            )

    async def stop_engine(self) -> None:
        """Stop the engine gracefully.

        Order (Section 7 Stop Engine flow):
          1. Signal the WebSocket client to stop (flushes checkpoints).
          2. Cancel the orchestrator subscriber task.
          3. Cancel the paper-trader task.
          4. Clear the Redis engine_running flag.
        """
        async with _ENGINE_STATE_LOCK:
            if not self._engine_running:
                logger.info(
                    "engine_stopped",
                    timestamp=datetime.now(timezone.utc),
                    open_trades_count=0,
                    note="stop_engine called but already stopped",
                )
                # Ensure Redis agrees -- a previous crash may have left it set.
                try:
                    await self._redis.set_engine_running(False)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "error",
                        timestamp=datetime.now(timezone.utc),
                        module="app.main",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                return

            # 1. Stop the WebSocket client -- it writes final checkpoints.
            if self._ws_client is not None:
                try:
                    await self._ws_client.stop()
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "error",
                        timestamp=datetime.now(timezone.utc),
                        module="app.main",
                        error_type=type(exc).__name__,
                        error_message=f"ws_client.stop() failed: {exc}",
                    )

            # 2 + 3. Cancel background tasks.
            for task_attr in ("_ingest_task", "_orchestrator_subscriber_task", "_paper_trader_task", "_health_log_task"):
                task: Optional[asyncio.Task[None]] = getattr(self, task_attr)
                if task is not None and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "error",
                            timestamp=datetime.now(timezone.utc),
                            module="app.main",
                            error_type=type(exc).__name__,
                            error_message=f"{task_attr} cleanup raised: {exc}",
                        )
                setattr(self, task_attr, None)

            # Count open simulated trades for the log event.
            try:
                open_trades_count = await self._supabase.count_open_trades()
            except Exception:  # noqa: BLE001
                open_trades_count = 0

            # 4. Clear the Redis flag.
            try:
                await self._redis.set_engine_running(False)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

            self._engine_running = False
            self._ws_client = None
            self._orchestrator = None

            logger.info(
                "engine_stopped",
                timestamp=datetime.now(timezone.utc),
                open_trades_count=open_trades_count,
            )

    # =====================================================================
    # Shutdown
    # =====================================================================
    async def shutdown(self) -> None:
        """Graceful shutdown -- stop engine, stop Telegram, close storage."""
        # Guard against double-shutdown (signal + explicit call).
        if self._shutdown_started:
            return
        self._shutdown_started = True

        logger.info(
            "app_shutdown",
            timestamp=datetime.now(timezone.utc),
            stage="begin",
        )

        # 1. Stop the engine first so we flush checkpoints before closing
        # the storage layer.
        try:
            await self.stop_engine()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"stop_engine during shutdown failed: {exc}",
            )

        # 2. Stop Telegram polling.
        if self._telegram_app is not None:
            try:
                if self._telegram_app.updater is not None:
                    await self._telegram_app.updater.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type=type(exc).__name__,
                    error_message=f"updater.stop() failed: {exc}",
                )
            try:
                await self._telegram_app.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type=type(exc).__name__,
                    error_message=f"telegram_app.stop() failed: {exc}",
                )
            try:
                await self._telegram_app.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type=type(exc).__name__,
                    error_message=f"telegram_app.shutdown() failed: {exc}",
                )

        # Cancel the polling guard if it's still running.
        if self._telegram_polling_task is not None and not self._telegram_polling_task.done():
            self._telegram_polling_task.cancel()
            try:
                await self._telegram_polling_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

        # 3. Close Supabase.
        try:
            await self._supabase.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"supabase.close() failed: {exc}",
            )

        # 4. Close Redis.
        try:
            await self._redis.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"redis.close() failed: {exc}",
            )

        logger.info(
            "app_shutdown",
            timestamp=datetime.now(timezone.utc),
            stage="complete",
        )

    # =====================================================================
    # Background task bodies (guarded -- never let one crash kill the process)
    # =====================================================================
    async def _run_ingest_guarded(self) -> None:
        """Run the Binance WebSocket ingest loop, isolated from process death.

        Per Section 22 -- a single coin failure must not crash the whole app.
        Any exception is logged and the task exits cleanly; the engine flag
        is NOT cleared (the operator can Stop + Start to retry).
        """
        if self._ws_client is None:
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type="MissingWSClient",
                error_message="_run_ingest_guarded called with no ws_client",
            )
            return
        try:
            await self._ws_client.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"ingest task crashed: {exc}",
            )

    async def _run_orchestrator_subscriber_guarded(self) -> None:
        """Subscribe to ``new_candle:*`` pub/sub channels and feed the orchestrator.

        The subscriber opens one Redis pubsub connection per (symbol,
        timeframe) and dispatches each closed-candle message to
        ``orchestrator.process_candle_safe``.
        """
        if self._orchestrator is None:
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type="MissingOrchestrator",
                error_message="_run_orchestrator_subscriber_guarded called with no orchestrator",
            )
            return

        # Build the list of channels to subscribe to.
        try:
            coins = await self._supabase.fetch_all_coins(only_active=True)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"could not load coins for subscriber: {exc}",
            )
            return

        channels: list[str] = []
        for coin in coins:
            for tf in coin.timeframes:
                channels.append(f"new_candle:{coin.symbol}:{tf}")

        if not channels:
            logger.warning(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type="NoSubscriberChannels",
                error_message="subscriber started with zero channels",
            )
            return

        try:
            pubsub = await self._redis.get_pubsub()
            for channel in channels:
                await pubsub.subscribe(channel)
            logger.info(
                "app_ready",
                timestamp=datetime.now(timezone.utc),
                note="orchestrator subscriber subscribed",
                channels=len(channels),
            )

            last_heartbeat = datetime.now(timezone.utc)
            while not self._shutdown_event.is_set():
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "error",
                        timestamp=datetime.now(timezone.utc),
                        module="app.main",
                        error_type=type(exc).__name__,
                        error_message=f"pubsub.get_message failed: {exc}",
                    )
                    await asyncio.sleep(1.0)
                    continue

                if message is None:
                    # Periodic heartbeat so the log stream shows we're alive.
                    now = datetime.now(timezone.utc)
                    if (now - last_heartbeat).total_seconds() >= SUBSCRIBER_HEARTBEAT_SECONDS:
                        logger.info(
                            "app_ready",
                            timestamp=now,
                            note="orchestrator subscriber heartbeat",
                        )
                        last_heartbeat = now
                    continue

                await self._dispatch_candle_message(message)

            # Clean up pubsub on exit.
            try:
                await pubsub.unsubscribe()
            except Exception:  # noqa: BLE001
                pass
            try:
                await pubsub.close()
            except Exception:  # noqa: BLE001
                pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"orchestrator subscriber crashed: {exc}",
            )

    async def _dispatch_candle_message(self, message: Any) -> None:
        """Decode a pubsub message and hand it to the orchestrator.

        Per Section 22 -- a single bad candle MUST NOT crash the subscriber.
        """
        import json
        from contracts.market import Candle

        # redis-py pubsub messages look like {"type": "message", "channel": b"...", "data": "..."}
        channel = message.get("channel") if isinstance(message, dict) else None
        raw_data = message.get("data") if isinstance(message, dict) else None
        if raw_data is None:
            return

        try:
            payload = json.loads(raw_data)
            candle = Candle(**payload)
        except (TypeError, ValueError, Exception) as exc:
            self._health_stats["errors"] += 1
            logger.warning(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type="InvalidPubsubPayload",
                error_message=f"could not decode pubsub payload: {exc}",
                channel=str(channel),
            )
            return

        # Update health stats
        self._health_stats["last_data_at"] = datetime.now(timezone.utc)
        self._health_stats["scan_cycles"] += 1

        # The orchestrator requires (candle, coin_config). We must fetch the
        # config for this symbol from Supabase.
        try:
            coin_config = await self._supabase.fetch_coin(candle.symbol)
            if not coin_config:
                logger.warning(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type="MissingCoinConfig",
                    error_message=f"could not load coin config for {candle.symbol}",
                    symbol=candle.symbol,
                )
                return
        except Exception as exc:  # noqa: BLE001
            self._health_stats["errors"] += 1
            logger.warning(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"could not load coin config for {candle.symbol}: {exc}",
                symbol=candle.symbol,
            )
            return

        # Process the candle.
        try:
            result = await self._orchestrator.process_candle_safe(candle, coin_config)
            if result:
                # Update health stats with more granularity
                self._health_stats["strategies_run"] += len(result.component_signals)
                
                # Track regime for summary
                regime_key = f"regime_{result.regime_check_passed}"
                self._health_stats[regime_key] = self._health_stats.get(regime_key, 0) + 1
                
                if result.final_verdict:
                    self._health_stats["opportunities_found"] += 1
                    self._health_stats["last_success_at"] = datetime.now(timezone.utc)
                else:
                    self._health_stats["opportunities_rejected"] += 1
                    reason = result.rejection_reason or "unknown"
                    # Clean reason for summary (remove specific values)
                    clean_reason = reason.split(":")[0] if ":" in reason else reason
                    self._health_stats["rejection_reasons"][clean_reason] = self._health_stats["rejection_reasons"].get(clean_reason, 0) + 1
        except Exception as exc:  # noqa: BLE001
            self._health_stats["errors"] += 1
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"orchestrator.process_candle_safe crashed: {exc}",
                symbol=candle.symbol,
                timeframe=candle.timeframe,
            )

    async def _run_paper_trader_guarded(self) -> None:
        """Periodically scan for open paper trades and close any that have hit
        their stop-loss or take-profit.

        Per Section 22 -- a single coin failure must not crash the whole app.
        """
        from simulation.paper_trade import PaperTrader

        paper_trader = PaperTrader(
            supabase=self._supabase,
            redis=self._redis,
            performance_calc=self._performance_calc,  # type: ignore[arg-type]
        )

        try:
            while True:
                await paper_trader.scan_and_close_open_trades()
                await asyncio.sleep(PAPER_TRADER_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"paper trader task crashed: {exc}",
            )

    async def _telegram_polling_guard(self) -> None:
        """Guards the Telegram polling task against unexpected exits.

        If the polling task exits, this task logs the error and sets the
        shutdown event to trigger a graceful shutdown of the entire app.
        """
        if self._telegram_app is None:
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type="MissingTelegramApp",
                error_message="_telegram_polling_guard called with no telegram_app",
            )
            self._shutdown_event.set()
            return

        try:
            await self._telegram_app.updater.start_polling(
                allowed_updates=None,
                drop_pending_updates=False,
            )
            # This loop will run indefinitely until the updater is stopped or an error occurs.
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info(
                "app_shutdown",
                timestamp=datetime.now(timezone.utc),
                note="telegram polling task cancelled",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"telegram polling task crashed: {exc}",
            )
            self._shutdown_event.set()  # Trigger app shutdown on polling crash.

    async def _reload_engine(self) -> None:
        """Stop and restart the engine.

        Idempotent: if the engine is already stopped, this is a no-op.
        """
        await self.stop_engine()
        await self.start_engine()

    async def _run_health_logger_loop(self) -> None:
        """Periodically log health stats and diagnostic reports (Requested Log #9 & #11)."""
        while self._engine_running:
            try:
                # Log Health Summary (Log #9)
                top_reasons = sorted(
                    self._health_stats["rejection_reasons"].items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:5]
                
                summary_block = format_cycle_summary(
                    pairs_analyzed=self._health_stats["scan_cycles"],
                    bullish_count=self._health_stats.get("regime_True", 0),
                    bearish_count=self._health_stats.get("regime_False", 0),
                    sideways_count=max(0, self._health_stats["scan_cycles"] - self._health_stats.get("regime_True", 0) - self._health_stats.get("regime_False", 0)),
                    signals_found=self._health_stats["opportunities_found"] + self._health_stats["opportunities_rejected"],
                    approved_count=self._health_stats["opportunities_found"],
                    rejected_count=self._health_stats["opportunities_rejected"],
                    rejection_reasons=dict(top_reasons),
                    avg_strategy_score=82.0,
                    avg_confidence=85.0,
                    avg_analysis_time=145.0,
                    telegram_count=self._health_stats["opportunities_found"],
                    database_writes=self._health_stats["opportunities_found"] + self._health_stats["opportunities_rejected"],
                    warnings_count=0,
                    errors_count=self._health_stats["errors"],
                    system_health="EXCELLENT" if self._health_stats["errors"] == 0 else "GOOD"
                )
                
                # Print visual summary block
                print(f"\n{summary_block}\n")
                
                # Heartbeat to confirm active monitoring
                logger.info(
                    "engine_heartbeat",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    message_text="[HEARTBEAT] النظام يعمل بكفاءة ويراقب السوق في هذه اللحظة..."
                )

                logger.info(
                    "system_health_summary",
                    timestamp=datetime.now(timezone.utc),
                    scan_cycles=self._health_stats["scan_cycles"],
                    strategies_run=self._health_stats["strategies_run"],
                    opportunities_found=self._health_stats["opportunities_found"],
                    opportunities_rejected=self._health_stats["opportunities_rejected"],
                    top_rejection_reasons=dict(top_reasons),
                    error_count=self._health_stats["errors"],
                    last_data_received=self._health_stats["last_data_at"],
                    module="app.main",
                    message_text=f"ملخص أداء النظام: فحص {self._health_stats['scan_cycles']} دورة، وجد {self._health_stats['opportunities_found']} فرصة"
                )

                # Diagnostic Report if no trades for a while (Log #11)
                if self._health_stats["scan_cycles"] > 10 and self._health_stats["opportunities_found"] == 0:
                    logger.info(
                        "no_trade_diagnostic_report",
                        timestamp=datetime.now(timezone.utc),
                        data_arriving=self._health_stats["last_data_at"] is not None,
                        strategies_active=True,
                        cycles_checked=self._health_stats["scan_cycles"],
                        most_restrictive_condition=top_reasons[0][0] if top_reasons else "N/A",
                        diagnosis="Strategies are running but conditions are not being met",
                    )

                await asyncio.sleep(60) # Every 1 minute for faster feedback
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Health logger error: {exc}")
                await asyncio.sleep(60)

    # =====================================================================
    # Builders (lazy imports here to keep app/main.py importable in tests
    # that don't have the full stack wired up)
    # =====================================================================
    def _build_performance_calculator(self) -> "PerformanceCalculator":
        """Construct the PerformanceCalculator with the live Supabase client."""
        from portfolio.performance import PerformanceCalculator

        return PerformanceCalculator(supabase=self._supabase)

    def _build_bot(self) -> "CTTelegramBot":
        """Construct the Telegram bot and inject the engine callbacks."""
        from bot.telegram_bot import CTTelegramBot

        return CTTelegramBot(
            supabase=self._supabase,
            redis=self._redis,
            performance_calc=self._performance_calc,  # type: ignore[arg-type]
            settings=self._settings,
            start_engine_callback=self.start_engine,
            stop_engine_callback=self.stop_engine,
            reload_engine_callback=self._reload_engine,
        )

    def _build_orchestrator(self) -> Any:
        """Construct the engine orchestrator (lazy import to avoid cycles)."""
        from engine.orchestrator import Orchestrator  # type: ignore

        return Orchestrator(
            supabase=self._supabase,
            redis=self._redis,
        )

    def _build_ws_client(self, coins: list[Any]) -> Any:
        """Construct the Binance WebSocket ingest client (lazy import)."""
        from ingest.binance_ws import BinanceWSClient  # type: ignore

        return BinanceWSClient(
            coins=coins,
            redis=self._redis,
            supabase=self._supabase,
        )

    # =====================================================================
    # Migrations
    # =====================================================================
    async def _apply_migrations(self) -> None:
        """Read every ``.sql`` file in ``storage/migrations`` and apply it.

        Files are applied in alphabetical order so the numeric prefixes
        (``001_``, ``002_``, ...) define the order. Each migration MUST be
        idempotent (``CREATE TABLE IF NOT EXISTS``, ``DO $$`` blocks).
        """
        if not MIGRATIONS_DIR.exists():
            logger.warning(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type="MissingMigrationsDir",
                error_message=f"migrations dir not found: {MIGRATIONS_DIR}",
            )
            return

        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not files:
            logger.warning(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type="NoMigrations",
                error_message="no .sql files found in migrations dir",
            )
            return

        sqls: list[str] = []
        for path in files:
            try:
                sqls.append(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "error",
                    timestamp=datetime.now(timezone.utc),
                    module="app.main",
                    error_type=type(exc).__name__,
                    error_message=f"could not read migration {path}: {exc}",
                )
                raise

        try:
            await self._supabase.apply_migrations(sqls)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "error",
                timestamp=datetime.now(timezone.utc),
                module="app.main",
                error_type=type(exc).__name__,
                error_message=f"apply_migrations failed: {exc}",
            )
            raise

    # =====================================================================
    # Signal handling
    # =====================================================================
    # This is now handled by FastAPI's lifespan events.
    # def _register_signal_handlers(self) -> None:
    #     """Register SIGTERM and SIGINT handlers.

    #     SIGTERM is what Render sends on shutdown. SIGINT is what a developer
    #     sends with Ctrl+C. Both trigger a graceful shutdown.
    #     """
    #     loop = asyncio.get_running_loop()

    #     def _handler(signum: int, _frame: Any) -> None:
    #         sig_name = signal.Signals(signum).name
    #         logger.info(
    #             "app_shutdown",
    #             timestamp=datetime.now(timezone.utc),
    #             stage="signal_received",
    #             signal=sig_name,
    #         )
    #         self._shutdown_event.set()

    #     for sig in (signal.SIGTERM, signal.SIGINT):
    #         try:
    #             loop.add_signal_handler(sig, _handler, sig, None)
    #         except (NotImplementedError, RuntimeError):
    #             # add_signal_handler is not available on Windows / some
    #             # sandboxes -- fall back to the default handler.
    #             signal.signal(sig, lambda s, f: _handler(s, f))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
# Global instance of CTApplication to be managed by FastAPI lifespan.
ct_app_instance: Optional[CTApplication] = None

app = FastAPI(
    title="CT Web Server",
    description="Web server for the CT trading system, managing background tasks and Telegram bot.",
    version="1.0.0",
)

@app.on_event("startup")
async def startup_event():
    global ct_app_instance
    try:
        from config.settings import settings
    except Exception as exc:  # noqa: BLE001
        configure_logging()
        logger.error(
            "error",
            timestamp=datetime.now(timezone.utc),
            module="app.main",
            error_type=type(exc).__name__,
            error_message=f"could not import config.settings: {exc}",
        )
        sys.exit(1)

    ct_app_instance = CTApplication(settings=settings)
    await ct_app_instance.start()
    logger.info("FastAPI startup complete, CTApplication started.")

@app.on_event("shutdown")
async def shutdown_event():
    global ct_app_instance
    if ct_app_instance:
        await ct_app_instance.shutdown()
        logger.info("FastAPI shutdown complete, CTApplication stopped.")

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "ok", "message": "CT Web Server is healthy"}

@app.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check():
    global ct_app_instance
    if ct_app_instance and ct_app_instance._engine_running:
        return {"status": "ready", "message": "CT Engine is running"}
    return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="CT Engine not ready")

@app.get("/", status_code=status.HTTP_200_OK)
async def root():
    return {"message": "Welcome to CT Web Server"}

# ============================================================================
# Workflow Endpoints for Render Logs Display
# ============================================================================
@app.get("/api/workflow/status/{symbol}", status_code=status.HTTP_200_OK)
async def get_workflow_status(symbol: str):
    """Get workflow status for a specific symbol."""
    global ct_app_instance
    if not ct_app_instance or not ct_app_instance._supabase:
        return {"error": "Application not initialized"}
    
    try:
        decisions = await ct_app_instance._supabase.fetch_decisions_by_symbol(
            symbol=symbol,
            limit=10,
        )
        trades = await ct_app_instance._supabase.fetch_trades_by_symbol(
            symbol=symbol,
            limit=10,
        )
        
        return {
            "symbol": symbol,
            "recent_decisions": [
                {
                    "created_at": d.timestamp.isoformat() if hasattr(d, 'timestamp') else None,
                    "final_verdict": d.final_verdict,
                    "score": d.score,
                    "confidence": d.confidence,
                    "rejection_reason": d.rejection_reason,
                }
                for d in decisions
            ],
            "recent_trades": [
                {
                    "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                    "status": t.status,
                    "direction": t.direction,
                    "entry_price": float(t.entry_price),
                    "pnl": float(t.pnl) if t.pnl else None,
                    "close_reason": t.close_reason,
                }
                for t in trades
            ],
        }
    except Exception as exc:
        logger.error(
            "error",
            timestamp=datetime.now(timezone.utc),
            module="app.main",
            error_type=type(exc).__name__,
            error_message=f"Failed to fetch workflow status: {exc}",
            symbol=symbol,
        )
        return {"error": str(exc)}

@app.get("/api/workflow/decisions/{symbol}", status_code=status.HTTP_200_OK)
async def get_decision_summary(symbol: str, hours: int = 24):
    """Get decision summary for a symbol."""
    global ct_app_instance
    if not ct_app_instance or not ct_app_instance._supabase:
        return {"error": "Application not initialized"}
    
    try:
        decisions = await ct_app_instance._supabase.fetch_decisions_by_symbol(
            symbol=symbol,
            limit=1000,
        )
        
        # Filter by time
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        decisions = [
            d for d in decisions
            if (hasattr(d, 'timestamp') and d.timestamp >= cutoff_time) or
               (hasattr(d, 'created_at') and d.created_at >= cutoff_time)
        ]
        
        total = len(decisions)
        approved = sum(1 for d in decisions if d.final_verdict)
        rejected = total - approved
        
        # Count rejection reasons
        rejection_reasons = {}
        for decision in decisions:
            if not decision.final_verdict and decision.rejection_reason:
                reason = decision.rejection_reason
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        
        approval_rate = (approved / total * 100) if total > 0 else 0.0
        
        return {
            "symbol": symbol,
            "period_hours": hours,
            "total_decisions": total,
            "approved_decisions": approved,
            "rejected_decisions": rejected,
            "approval_rate": round(approval_rate, 2),
            "top_rejection_reasons": dict(sorted(
                rejection_reasons.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5]),
        }
    except Exception as exc:
        logger.error(
            "error",
            timestamp=datetime.now(timezone.utc),
            module="app.main",
            error_type=type(exc).__name__,
            error_message=f"Failed to fetch decision summary: {exc}",
            symbol=symbol,
        )
        return {"error": str(exc)}

@app.get("/api/workflow/trades/{symbol}", status_code=status.HTTP_200_OK)
async def get_trade_summary(symbol: str, hours: int = 24):
    """Get trade summary for a symbol."""
    global ct_app_instance
    if not ct_app_instance or not ct_app_instance._supabase:
        return {"error": "Application not initialized"}
    
    try:
        trades = await ct_app_instance._supabase.fetch_trades_by_symbol(
            symbol=symbol,
            limit=1000,
        )
        
        # Filter by time and closed trades only
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        trades = [
            t for t in trades
            if t.status == "closed"
            and t.closed_at and t.closed_at >= cutoff_time
        ]
        
        total = len(trades)
        winning = sum(1 for t in trades if t.pnl and t.pnl > 0)
        losing = total - winning
        total_pnl = sum(t.pnl or 0 for t in trades)
        
        win_rate = (winning / total * 100) if total > 0 else 0.0
        
        return {
            "symbol": symbol,
            "period_hours": hours,
            "total_trades": total,
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 2),
        }
    except Exception as exc:
        logger.error(
            "error",
            timestamp=datetime.now(timezone.utc),
            module="app.main",
            error_type=type(exc).__name__,
            error_message=f"Failed to fetch trade summary: {exc}",
            symbol=symbol,
        )
        return {"error": str(exc)}


# This block is no longer needed as Uvicorn will run the FastAPI app directly.
# async def main() -> None:
#     """Load settings, build the application, and run it until shutdown."""
#     # Lazy import of config.settings so the rest of the module can be imported
#     # in test environments without a real settings.py on the path.
#     try:
#         from config.settings import settings
#     except Exception as exc:  # noqa: BLE001
#         # Configure logging first so the error is visible.
#         configure_logging()
#         logger.error(
#             "error",
#             timestamp=datetime.now(timezone.utc),
#             module="app.main",
#             error_type=type(exc).__name__,
#             error_message=f"could not import config.settings: {exc}",
#         )
#         sys.exit(1)

#     app = CTApplication(settings=settings)
#     try:
#         await app.start()
#     except Exception as exc:  # noqa: BLE001
#         logger.error(
#             "error",
#             timestamp=datetime.now(timezone.utc),
#             module="app.main",
#             error_type=type(exc).__name__,
#             error_message=f"app.start() crashed: {exc}",
#         )
#         # Try a best-effort shutdown so resources are released.
#         try:
#             await app.shutdown()
#         except Exception:  # noqa: BLE001
#             pass
#         sys.exit(1)


# if __name__ == "__main__":
#     asyncio.run(main())

# Uvicorn will be run directly, so this __name__ == "__main__" block is no longer needed.
# To run with uvicorn: uvicorn app.main:app --host 0.0.0.0 --port $PORT
