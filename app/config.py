from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    "TRXUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT", "UNIUSDT",
    "ATOMUSDT", "ETCUSDT", "FILUSDT", "APTUSDT", "ARBUSDT",
]
SUPPORTED_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _symbols(value: str | None) -> list[str]:
    raw = [item.strip().upper() for item in (value or "").split(",") if item.strip()]
    result = list(dict.fromkeys(raw or DEFAULT_SYMBOLS))
    return result[:20]


def _timeframes(value: str | None, default: list[str]) -> list[str]:
    raw = [item.strip().lower() for item in (value or "").split(",") if item.strip()]
    result = list(dict.fromkeys(item for item in (raw or default) if item in SUPPORTED_TIMEFRAMES))
    return result or list(default)


@dataclass(frozen=True)
class Settings:
    app_name: str = "Smart Trading Indicator"
    app_version: str = "1.0.0"
    timezone: str = "UTC"
    exchange: str = "binance"
    market_type: str = "spot"
    symbols: list[str] = field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    entry_timeframe: str = "15m"
    structure_timeframe: str = "1h"
    htf_timeframe: str = "4h"
    analysis_timeframes: list[str] = field(default_factory=lambda: ["5m", "15m", "1h"])
    stream_timeframes: list[str] = field(default_factory=lambda: list(SUPPORTED_TIMEFRAMES))
    min_signal_score: float = 80.0
    min_direction_gap: float = 15.0
    require_closed_candle: bool = True
    max_pending_candles: int = 10
    rr_tp1: float = 1.0
    rr_tp2: float = 2.0
    atr_buffer_multiplier: float = 0.1
    swing_left: int = 3
    swing_right: int = 3
    atr_period: int = 14
    min_structure_break_atr: float = 0.1
    history_limit: int = 500
    stale_data_seconds: int = 180
    binance_rest_url: str = "https://data-api.binance.vision/api/v3"
    binance_ws_url: str = "wss://data-stream.binance.vision/stream"
    supabase_url: str = ""
    supabase_key: str = ""
    redis_url: str = ""
    disable_auto_start: bool = False
    log_level: str = "INFO"
    config_version: str = "core_v1"

    @classmethod
    def from_env(cls) -> "Settings":
        entry = os.getenv("ENTRY_TIMEFRAME", os.getenv("EXECUTION_TIMEFRAME", "15m")).strip().lower()
        structure = os.getenv("STRUCTURE_TIMEFRAME", os.getenv("TRIGGER_TIMEFRAME", "1h")).strip().lower()
        htf = os.getenv("HTF_TIMEFRAME", os.getenv("HIGHER_TIMEFRAME", "4h")).strip().lower()
        analysis_timeframes = _timeframes(os.getenv("ANALYSIS_TIMEFRAMES"), ["5m", "15m", "1h"])
        stream_timeframes = _timeframes(os.getenv("STREAM_TIMEFRAMES"), list(SUPPORTED_TIMEFRAMES))
        if entry not in SUPPORTED_TIMEFRAMES:
            entry = "15m"
        if structure not in SUPPORTED_TIMEFRAMES:
            structure = "1h"
        if htf not in SUPPORTED_TIMEFRAMES:
            htf = "4h"
        return cls(
            app_name=os.getenv("APP_NAME", "Smart Trading Indicator"),
            app_version=os.getenv("APP_VERSION", "1.0.0"),
            symbols=_symbols(os.getenv("SELECTED_SYMBOLS")),
            entry_timeframe=entry,
            structure_timeframe=structure,
            htf_timeframe=htf,
            analysis_timeframes=analysis_timeframes,
            stream_timeframes=stream_timeframes,
            min_signal_score=_float(os.getenv("MIN_SIGNAL_SCORE"), 80.0),
            min_direction_gap=_float(os.getenv("MIN_DIRECTION_GAP"), 15.0),
            require_closed_candle=_bool(os.getenv("REQUIRE_CLOSED_CANDLE"), True),
            max_pending_candles=_int(os.getenv("MAX_PENDING_CANDLES"), 10),
            rr_tp1=_float(os.getenv("RR_TP1"), 1.0),
            rr_tp2=_float(os.getenv("RR_TP2"), 2.0),
            atr_buffer_multiplier=_float(os.getenv("ATR_BUFFER_MULTIPLIER"), 0.1),
            swing_left=_int(os.getenv("SWING_LEFT"), 3),
            swing_right=_int(os.getenv("SWING_RIGHT"), 3),
            atr_period=_int(os.getenv("ATR_PERIOD"), 14),
            min_structure_break_atr=_float(os.getenv("MIN_STRUCTURE_BREAK_ATR"), 0.1),
            history_limit=min(_int(os.getenv("HISTORY_LIMIT"), 500), 1000),
            stale_data_seconds=_int(os.getenv("STALE_DATA_SECONDS"), 180),
            binance_rest_url=os.getenv("BINANCE_REST_URL", "https://data-api.binance.vision/api/v3").rstrip("/"),
            binance_ws_url=os.getenv("BINANCE_WS_URL", "wss://data-stream.binance.vision/stream").rstrip("/"),
            supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
            supabase_key=os.getenv("SUPABASE_KEY", ""),
            redis_url=os.getenv("REDIS_URL", ""),
            disable_auto_start=_bool(os.getenv("DISABLE_AUTO_START"), False),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            config_version=os.getenv("CONFIG_VERSION", "core_v1"),
        )

    @property
    def mtf_mapping(self) -> dict[str, list[str]]:
        defaults = {"5m": ["15m", "1h"], "15m": ["1h", "4h"], "1h": ["4h", "1d"]}
        return {timeframe: defaults.get(timeframe, [self.structure_timeframe, self.htf_timeframe]) for timeframe in self.analysis_timeframes}

    @property
    def persistence_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)
