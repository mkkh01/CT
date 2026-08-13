import sys
import os
import traceback

print("Testing imports...")
try:
    from app.main import app
    print("SUCCESS: app.main.app imported successfully.")
except Exception:
    print("FAILURE: app.main.app import failed.")
    traceback.print_exc()
    sys.exit(1)
