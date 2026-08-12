from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from datetime import datetime, date, timezone
from typing import Any

from flask import Flask, jsonify, render_template
from flask.json.provider import DefaultJSONProvider

from .config import Settings
from .runtime import BotRuntime

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

def create_app():
    logger.info("Creating Flask app...")
    settings = Settings.from_env()
    app = Flask(__name__)
    app.json = CustomJSONProvider(app)
    
    # Initialize runtime
    runtime = BotRuntime(settings)

    @app.get("/ping")
    def ping():
        return "pong", 200

    @app.get("/healthz")
    def healthz():
        return jsonify(runtime.health()), 200

    @app.get("/")
    @app.get("/dashboard")
    def dashboard_page():
        return render_template("dashboard.html")

    @app.get("/dashboard/api/overview")
    def dashboard_overview():
        try:
            return jsonify(runtime.dashboard_snapshot())
        except Exception as e:
            logger.error(f"API Error /overview: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.get("/dashboard/api/history")
    def dashboard_history():
        try:
            return jsonify(runtime.history_snapshot())
        except Exception as e:
            logger.error(f"API Error /history: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.get("/cron/heartbeat")
    def cron_heartbeat():
        return jsonify({
            "status": "ok", 
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "runtime_started": runtime._started
        }), 200

    # Start runtime in a safe background thread
    if os.getenv("DISABLE_AUTO_START", "0") != "1":
        def start_async():
            try:
                # Small delay to let server finish binding
                time.sleep(5)
                logger.info("Starting BotRuntime...")
                runtime.start()
                logger.info("BotRuntime started successfully.")
            except Exception as e:
                logger.error(f"Failed to start BotRuntime: {e}")
        
        t = threading.Thread(target=start_async, name="runtime-init", daemon=True)
        t.start()
        
        atexit.register(runtime.stop)

    logger.info("Flask app created successfully.")
    return app

# Entry point for Gunicorn
app = create_app()
