from __future__ import annotations

import atexit
import logging
import os
from functools import wraps
from hmac import compare_digest
from typing import Any, Callable

from flask import Flask, jsonify, redirect, render_template, request

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

    def dashboard_auth(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            expected = settings.dashboard_token
            supplied = request.headers.get("X-Dashboard-Token", "")
            if not expected:
                return jsonify({"error": "DASHBOARD_TOKEN is not configured on Render"}), 503
            if not supplied or not compare_digest(supplied, expected):
                return jsonify({"error": "dashboard authentication required"}), 401
            return view(*args, **kwargs)

        return wrapped

    @app.get("/")
    def index() -> Any:
        return redirect("/dashboard")

    @app.get("/healthz")
    def healthz() -> Any:
        status = runtime.health()
        return jsonify(status), (200 if status["status"] == "ok" else 503)

    @app.get("/api/status")
    def api_status() -> Any:
        return jsonify(runtime.health())

    @app.get("/api/snapshot")
    @dashboard_auth
    def api_snapshot() -> Any:
        return jsonify(runtime.trader.snapshot())

    @app.get("/dashboard")
    def dashboard() -> Any:
        return render_template("dashboard.html")

    @app.get("/dashboard/api/overview")
    @dashboard_auth
    def dashboard_overview() -> Any:
        return jsonify(runtime.dashboard_snapshot())

    if start_runtime and os.getenv("DISABLE_AUTO_START", "0") != "1":
        runtime.start()
        atexit.register(runtime.stop)

    return app, runtime


app, runtime = create_app()
