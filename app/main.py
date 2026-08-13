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
    try:
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
            try:
                h = runtime.health()
                return jsonify(h), 200
            except Exception as e:
                return jsonify({"status": "error", "error": str(e)}), 500

        @app.get("/debug/env")
        def debug_env():
            keys = list(os.environ.keys())
            important = ["TELEGRAM_CHAT_ID", "TELEGRAM_BOT_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "REDIS_URL"]
            status = {k: (k in keys and bool(os.environ[k])) for k in important}
            return jsonify({"env_status": status, "all_keys": keys}), 200

        @app.get("/")
        @app.get("/dashboard")
        def dashboard_page():
            return render_template("dashboard.html")

        @app.get("/dashboard/api/overview")
        def dashboard_overview():
            try:
                data = runtime.dashboard_snapshot()
                return jsonify(data)
            except Exception as e:
                error_details = {
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "endpoint": "/overview"
                }
                logger.error(f"API Error /overview: {e}\n{error_details['traceback']}")
                return jsonify(error_details), 500

        @app.get("/dashboard/api/history")
        def dashboard_history():
            try:
                return jsonify(runtime.history_snapshot())
            except Exception as e:
                error_details = {
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "endpoint": "/history"
                }
                logger.error(f"API Error /history: {e}\n{error_details['traceback']}")
                return jsonify(error_details), 500

        # Start runtime in a safe background thread
        if os.getenv("DISABLE_AUTO_START", "0") != "1":
            def start_async():
                try:
                    time.sleep(5)
                    logger.info("Starting BotRuntime in background...")
                    runtime.start()
                    logger.info("BotRuntime started.")
                except Exception as e:
                    logger.error(f"Failed to start BotRuntime: {e}")
            
            t = threading.Thread(target=start_async, name="runtime-init", daemon=True)
            t.start()
            atexit.register(runtime.stop)

        logger.info("Flask app created successfully.")
        return app
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Failed to create app: {e}\n{tb}")
        fallback = Flask(__name__)
        @fallback.route("/<path:p>")
        @fallback.route("/")
        def err(p=""):
            return f"CRITICAL STARTUP ERROR:\n{tb}", 500
        return fallback

# Global app object for Gunicorn
app = create_app()
