import os
import sys
import traceback

# Add the current directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = None

try:
    print("WSGI: Attempting to import app from app.main...")
    from app.main import app as flask_app
    app = flask_app
    print("WSGI: Import successful.")
except Exception as e:
    print(f"WSGI CRITICAL: Failed to import app from app.main: {e}")
    traceback.print_exc()
    from flask import Flask
    app = Flask(__name__)
    tb_str = traceback.format_exc()
    @app.route("/<path:path>")
    @app.route("/")
    def error_fallback(path=""):
        return f"<h1>WSGI Import Error</h1><p>The application failed to start due to an import error.</p><pre>{tb_str}</pre>", 500

if __name__ == "__main__":
    if app:
        app.run()
