from __future__ import annotations

import atexit
import logging
import os
import threading
import time
import traceback
from datetime import datetime, date, timezone
from typing import Any

from flask import Flask, jsonify, render_template
from flask.json.provider import DefaultJSONProvider

from .config import Settings
from .runtime import BotRuntime

# BUILD ID: 2026-08-13-T10-50-SYNC-FIX
BUILD_ID = "2026-08-13-T10-50-SYNC-FIX"

# Basic logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)

def create_app(start_runtime: bool | None = None):
    logger.info(f"Creating Flask app (PID: {os.getpid()})...")
    try:
        settings = Settings.from_env()
        app = Flask(__name__)
        app.json = CustomJSONProvider(app)
        app.config["START_RUNTIME_ON_REQUEST"] = start_runtime is not False
        
        # Initialize runtime
        runtime = BotRuntime(settings)

        @app.get("/ping")
        def ping():
            return f"pong (PID: {os.getpid()})", 200

        @app.get("/healthz")
        def healthz():
            try:
                h = runtime.health()
                h["pid"] = os.getpid()
                return jsonify(h), 200
            except Exception as e:
                return jsonify({"status": "error", "error": str(e), "pid": os.getpid()}), 500

        @app.get("/cron/heartbeat")
        def cron_heartbeat():
            return jsonify(runtime.health()), 200

        @app.get("/api/status")
        def api_status():
            return jsonify(runtime.health()), 200

        @app.get("/api/snapshot")
        def api_snapshot():
            return jsonify(runtime.dashboard_snapshot()), 200

        @app.get("/debug/env")
        def debug_env():
            keys = list(os.environ.keys())
            important = ["TELEGRAM_CHAT_ID", "TELEGRAM_BOT_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "REDIS_URL"]
            status = {k: (k in keys and bool(os.environ[k])) for k in important}
            return jsonify({"env_status": status, "all_keys": keys, "pid": os.getpid()}), 200

        @app.get("/")
        @app.get("/dashboard")
        def dashboard_page():
            return render_template("dashboard.html")

        @app.get("/dashboard/api/overview")
        def dashboard_overview():
            try:
                # In production, overview can start a lazily initialized runtime;
                # explicit test instances remain side-effect free.
                if not runtime._started and app.config.get("START_RUNTIME_ON_REQUEST", True):
                    logger.warning(f"Runtime not started in process {os.getpid()}, starting now...")
                    runtime.start()

                data = runtime.dashboard_snapshot()
                if "overview" in data:
                    data["overview"]["build_id"] = BUILD_ID
                return jsonify(data)
            except Exception as e:
                error_details = {
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "endpoint": "/overview",
                    "pid": os.getpid()
                }
                logger.error(f"API Error /overview: {e}\n{error_details['traceback']}")
                return jsonify(error_details), 500

        @app.get("/dashboard/api/history")
        def dashboard_history():
            try:
                return jsonify(runtime.history_snapshot())
            except Exception as e:
                return jsonify({"error": str(e), "traceback": traceback.format_exc(), "pid": os.getpid()}), 500

        # Start runtime in a safe background thread unless explicitly disabled.
        should_start_runtime = (start_runtime if start_runtime is not None else os.getenv("DISABLE_AUTO_START", "0") != "1")
        if should_start_runtime:
            def start_async():
                try:
                    logger.info(f"Starting BotRuntime in background (PID: {os.getpid()})...")
                    runtime.start()
                    logger.info(f"BotRuntime started in process {os.getpid()}.")
                except Exception as e:
                    logger.error(f"Failed to start BotRuntime in process {os.getpid()}: {e}")
            
            t = threading.Thread(target=start_async, name="runtime-init", daemon=True)
            t.start()
            atexit.register(runtime.stop)

        logger.info(f"Flask app created successfully (PID: {os.getpid()}).")
        return (app, runtime) if start_runtime is not None else app
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to create app: {e}\n{tb}")
        fallback = Flask(__name__)
        @fallback.route("/<path:p>")
        @fallback.route("/")
        def err(p=""):
            return f"CRITICAL STARTUP ERROR (PID: {os.getpid()}):\n{tb}", 500
        return fallback

# Production entry point is `run.py:app`; avoid constructing a global runtime on import.
