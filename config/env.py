import os
from dotenv import load_dotenv

load_dotenv()

def get_env(key, default=None, required=False):
    val = os.environ.get(key, default)
    if required and val is None:
        raise ValueError(f"Missing required environment variable: {key}")
    return val

def get_bool_env(key, default=False):
    val = os.environ.get(key, str(default)).lower()
    return val in ('true', '1', 't', 'y', 'yes')

def get_int_env(key, default=0):
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default

def get_float_env(key, default=0.0):
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default
