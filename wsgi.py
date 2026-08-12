import os
import sys
import traceback

# Add the current directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app.main import app
except Exception:
    print("CRITICAL: Failed to import app from app.main")
    traceback.print_exc()
    from flask import Flask
    app = Flask(__name__)
    @app.route("/<path:path>")
    @app.route("/")
    def error_fallback(path=""):
        return f"<h1>WSGI Import Error</h1><pre>{traceback.format_exc()}</pre>", 500

if __name__ == "__main__":
    app.run()
