from __future__ import annotations

import atexit
import logging
import os
from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, render_template

from .config import Settings
from .runtime import BotRuntime


class RuntimeLogHandler(logging.Handler):
    """Copies application logs into the runtime dashboard without exposing secrets."""

    _ct_dashboard_handler = True

    def __init__(self, runtime: BotRuntime) -> None:
        super().__init__(level=logging.INFO)
        self.runtime = runtime

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.runtime.add_runtime_log(
                record.levelname,
                self.format(record),
                record.name,
                persist=record.levelno >= logging.WARNING,
            )
        except Exception:
            # Logging must never take down the trading recommendation process.
            pass


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _attach_runtime_log_handler(runtime: BotRuntime) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_ct_dashboard_handler", False):
            root.removeHandler(handler)
    handler = RuntimeLogHandler(runtime)
    handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
    root.addHandler(handler)


def create_app(start_runtime: bool = True) -> tuple[Flask, BotRuntime]:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    app = Flask(__name__)
    runtime = BotRuntime(settings)
    _attach_runtime_log_handler(runtime)

    @app.get("/")
    def index() -> Any:
        # Serve the dashboard at the root so browsers and simple monitors do not
        # receive a redirect when opening the Render service URL.
        return render_template("dashboard.html")

    @app.get("/cron/heartbeat")
    def cron_heartbeat() -> Any:
        # Public, minimal keep-alive endpoint for external Cron services.
        # It intentionally exposes no capital, symbol, token, or database data.
        health = runtime.health()
        return jsonify({
            "status": "ok",
            "service": "CT Binance Spot Live Recommendations",
            "runtime_started": health.get("runtime_started", False),
            "websocket_connected": health.get("websocket_connected", False),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    @app.get("/healthz")
    def healthz() -> Any:
        status = runtime.health()
        return jsonify(status), (200 if status["status"] == "ok" else 503)

    @app.get("/api/status")
    def api_status() -> Any:
        return jsonify(runtime.health())

    @app.get("/api/snapshot")
    def api_snapshot() -> Any:
        return jsonify(runtime.trader.snapshot())

    @app.post("/api/market/refresh")
    def market_refresh() -> Any:
        # Manually trigger a REST poll cycle to recover from silent disconnects.
        runtime.market._poll_once()
        return jsonify({"status": "ok", "source": runtime.market.live_data_source}), 200

    @app.get("/dashboard")
    def dashboard() -> Any:
        return render_template("dashboard.html")

    @app.get("/dashboard/api/overview")
    def dashboard_overview() -> Any:
        return jsonify(runtime.dashboard_snapshot())

    @app.get("/dashboard/api/history")
    def dashboard_history() -> Any:
        return jsonify(runtime.history_snapshot())

    def _ensure_runtime_running():
        if start_runtime and os.getenv("DISABLE_AUTO_START", "0") != "1":
            # Ensure runtime is started and its background threads are alive.
            # Gunicorn forks workers, which can leave the runtime in a "started" state
            # but without the actual background threads from the master process.
            if not runtime._started or not runtime.is_alive():
                runtime.start()
                # Use a flag to avoid multiple registrations
                if not hasattr(app, "_atexit_registered"):
                    atexit.register(runtime.stop)
                    app._atexit_registered = True

    @app.before_request
    def lazy_start_runtime():
        _ensure_runtime_running()

    return app, runtime


app, runtime = create_app()
