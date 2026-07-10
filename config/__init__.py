# Backward Compatibility and Package Init
from .settings import *

# Mapping for CT Core components
RAW_DATABASE_URL = RAW_DATABASE_URL
DATABASE_URL = DATABASE_URL
TELEGRAM_TOKEN = TELEGRAM_TOKEN
ADMIN_ID = ADMIN_ID
REDIS_HOST = REDIS_HOST
REDIS_PORT = REDIS_PORT
REDIS_PASSWORD = REDIS_PASSWORD
DEBUG_MODE = DEBUG_MODE

def validate_config():
    from .settings import validate_config as vc
    return vc()
