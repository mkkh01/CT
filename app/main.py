from __future__ import annotations

import atexit
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, render_template

from .config import Settings
from .runtime import BotRuntime

# Basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

def create_app():
    settings = Settings.from_env()
    app = Flask(__name__)
    runtime = BotRuntime(settings)

    @app.get("/ping")
    def ping():
        return "pong", 200

    @app.get("/healthz")
    def healthz():
        return jsonify(runtime.health()), 200

    @app.get("/")
    @app.get("/dashboard")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/dashboard/api/overview")
    def dashboard_overview():
        return jsonify(runtime.dashboard_snapshot())

    @app.get("/dashboard/api/history")
    def dashboard_history():
        return jsonify(runtime.history_snapshot())

    @app.get("/cron/heartbeat")
    def cron_heartbeat():
        return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}), 200

    # Start runtime in a safe background thread
    if os.getenv("DISABLE_AUTO_START", "0") != "1":
        def start_async():
            try:
                logger.info("Starting BotRuntime background thread...")
                runtime.start()
            except Exception as e:
                logger.error(f"Failed to start BotRuntime: {e}")
        
        t = threading.Thread(target=start_async, name="runtime-init", daemon=True)
        t.start()
        
        atexit.register(runtime.stop)

    return app

# Gunicorn entry point
app = create_app()
