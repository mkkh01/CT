import os
import sys
import traceback

# Mock environment
os.environ["TELEGRAM_CHAT_ID"] = "1"
os.environ["TELEGRAM_BOT_TOKEN"] = "1:a"
os.environ["SUPABASE_URL"] = "https://a.supabase.co"
os.environ["SUPABASE_KEY"] = "a"
os.environ["REDIS_URL"] = "redis://localhost"

try:
    from app.config import Settings
    from app.runtime import BotRuntime
    
    print("Initializing BotRuntime...")
    settings = Settings.from_env()
    runtime = BotRuntime(settings)
    
    print("Calling dashboard_snapshot()...")
    data = runtime.dashboard_snapshot()
    print("SUCCESS: Snapshot returned data.")
    print(f"Data keys: {list(data.keys())}")
    
except Exception:
    print("FAILURE: Snapshot failed.")
    traceback.print_exc()
