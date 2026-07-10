import sys
from pathlib import Path

# إضافة المسار الرئيسي للبحث عن config.py
sys.path.append(str(Path(__file__).parent.parent))

try:
    import config
except ImportError:
    import config

def get_env(key, default=None, required=False):
    """تحويل الطلبات من os.environ إلى config.py"""
    val = getattr(config, key, default)
    if required and val is None:
        raise ValueError(f"Missing required config variable: {key}")
    return val

def get_bool_env(key, default=False):
    val = get_env(key, default)
    if isinstance(val, bool):
        return val
    return str(val).lower() in ('true', '1', 't', 'y', 'yes')

def get_int_env(key, default=0):
    try:
        return int(get_env(key, default))
    except (ValueError, TypeError):
        return default

def get_float_env(key, default=0.0):
    try:
        return float(get_env(key, default))
    except (ValueError, TypeError):
        return default
