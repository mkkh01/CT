# config/__init__.py
import sys
import importlib.util
from pathlib import Path

# Path to the actual config.py in the root directory
ROOT_DIR = Path(__file__).parent.parent
CONFIG_PATH = ROOT_DIR / "config.py"

def _load_main_config():
    if CONFIG_PATH.exists():
        spec = importlib.util.spec_from_file_location("main_config", CONFIG_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return None

main_config = _load_main_config()

# Proxy all attributes from main_config to this module
def _proxy_config():
    current_module = sys.modules[__name__]
    if main_config:
        for attr in dir(main_config):
            if not attr.startswith("__"):
                setattr(current_module, attr, getattr(main_config, attr))

    # Ensure some critical defaults exist even if missing in config.py
    defaults = {
        "DEBUG_MODE": False,
        "PORT": 10000,
        "WEBHOOK_URL": "",
        "SUPABASE_URL": "",
        "SUPABASE_KEY": "",
        "LOG_LEVEL": "INFO",
        "TELEGRAM_TOKEN": "",
        "ADMIN_ID": 0,
        "RAW_DATABASE_URL": "",
        "DATABASE_URL": "",
        "REDIS_HOST": "",
        "REDIS_PORT": 0,
        "REDIS_PASSWORD": "",
        "BINANCE_API_KEY": "",
        "BINANCE_API_SECRET": "",
        "BINANCE_WS_URL": "",
        "DEFAULT_CAPITAL": 0.0,
        "TRADE_FEE": 0.0,
        "HTF_MODE": "SKIP"
    }
    for key, val in defaults.items():
        if not hasattr(current_module, key):
            setattr(current_module, key, val)

_proxy_config()

def validate_config():
    if main_config and hasattr(main_config, 'validate_config'):
        return main_config.validate_config()
    return True
