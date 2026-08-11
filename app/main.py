from __future__ import annotations

import atexit
import logging
import os
from typing import Any

from flask import Flask, jsonify

from .config import Settings
from .runtime import BotRuntime


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app(start_runtime: bool = True) -> tuple[Flask, BotRuntime]:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    app = Flask(__name__)
    runtime = BotRuntime(settings)

    @app.get("/")
    def index() -> Any:
        return jsonify({
            "service": "CT Binance Spot Live Recommendations",
            "mode": "recommendations_only",
            "execution": "disabled",
            "health": runtime.health(),
        })

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

    if start_runtime and os.getenv("DISABLE_AUTO_START", "0") != "1":
        runtime.start()
        atexit.register(runtime.stop)

    return app, runtime


app, runtime = create_app()
