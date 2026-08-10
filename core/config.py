import os
from typing import List

def _e(k, alt=None, default=None):
    v = os.getenv(k)
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    if alt:
        v = os.getenv(alt)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return default

class Settings:
    APP_ENV = _e("APP_ENV", "production")
    
    se_val = _e("SYSTEM_ENABLED", default="true") or "true"
    SYSTEM_ENABLED = se_val.lower() == "true"
    
    MODE = _e("TRADING_MODE", "BALANCED")

    SUPABASE_URL = _e("SUPABASE_URL")
    SUPABASE_KEY = _e("SUPABASE_KEY", "SUPABASE_SERVICE_KEY")

    REDIS_URL = _e("REDIS_URL", "redis://localhost:6379/0")

    TELEGRAM_BOT_TOKEN = _e("TELEGRAM_BOT_TOKEN")
    
    _tid = _e("TELEGRAM_ADMIN_ID", "TELEGRAM_CHAT_ID", "0") or "0"
    TELEGRAM_ADMIN_ID = int(_tid) if _tid and _tid.isdigit() else None

    _sym = _e("SYMBOL_LIST", "BTC/USDT,ETH/USDT,SOL/USDT") or "BTC/USDT,ETH/USDT,SOL/USDT"
    SYMBOLS: List[str] = [s.strip().upper() for s in _sym.split(",") if s.strip()]

    TP_PCT = 1.00
    SL_PCT = 0.40
    TIMEOUT_HOURS = 12
    MIN_WIN_RATE = 82.0

    TRADE_START_UTC = "07:30"
    TRADE_END_UTC   = "19:30"
    MIN_ATR_PCT = 0.15
    MAX_ATR_PCT = 0.70
    MAX_SLIPPAGE = 0.10

    MAX_DAILY_LOSS_PCT = 0.80
    MAX_TRADES_PER_DAY = 3
    MAX_CONSECUTIVE_LOSS = 3
    COOLDOWN_MIN = 30

settings = Settings()
