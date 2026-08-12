from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


def _csv(value: str) -> List[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _normalise_supabase_url(raw: str) -> tuple[str, str]:
    value = raw.strip().rstrip("/")
    if value.startswith(("postgres://", "postgresql://")):
        return "", "SUPABASE_URL is a PostgreSQL connection string; use the REST URL https://PROJECT_REF.supabase.co"
    if value and not value.startswith("https://"):
        return "", "SUPABASE_URL must start with https://"
    return value, ""


@dataclass(frozen=True)
class Settings:
    telegram_chat_id: str = ""
    telegram_bot_token: str = ""
    dashboard_token: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_url_issue: str = ""
    redis_url: str = ""
    selected_symbols: List[str] = field(default_factory=list)
    initial_capital_usdt: float = 0.0
    max_concurrent_positions: int = 5
    daily_loss_limit_pct: float = 0.09
    risk_per_trade_pct: float = 0.005
    stop_loss_pct: float = 0.015
    take_profit_r_multiple: float = 2.0
    execution_timeframe: str = "1h"
    higher_timeframe: str = "4h"
    signal_cooldown_seconds: int = 3600
    binance_stream_url: str = "wss://data-stream.binance.vision:443/stream"
    binance_rest_url: str = "https://data-api.binance.vision/api/v3"
    heartbeat_interval_seconds: int = 15
    stale_data_seconds: int = 180
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        supabase_url, supabase_url_issue = _normalise_supabase_url(os.getenv("SUPABASE_URL", ""))
        return cls(
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            dashboard_token=os.getenv("DASHBOARD_TOKEN", "").strip(),
            supabase_url=supabase_url,
            supabase_key=os.getenv("SUPABASE_KEY", "").strip(),
            supabase_url_issue=supabase_url_issue,
            redis_url=os.getenv("REDIS_URL", "").strip(),
            selected_symbols=_csv(os.getenv("SELECTED_SYMBOLS", "")),
            initial_capital_usdt=float(os.getenv("INITIAL_CAPITAL_USDT", "0") or 0),
            max_concurrent_positions=int(os.getenv("MAX_CONCURRENT_POSITIONS", "5")),
            daily_loss_limit_pct=float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.09")),
            risk_per_trade_pct=float(os.getenv("RISK_PER_TRADE_PCT", "0.005")),
            stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", "0.015")),
            take_profit_r_multiple=float(os.getenv("TAKE_PROFIT_R_MULTIPLE", "2.0")),
            execution_timeframe=os.getenv("EXECUTION_TIMEFRAME", "1h").strip(),
            higher_timeframe=os.getenv("HIGHER_TIMEFRAME", "4h").strip(),
            signal_cooldown_seconds=int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "3600")),
            binance_stream_url=os.getenv("BINANCE_STREAM_URL", "wss://data-stream.binance.vision:443/stream").strip(),
            binance_rest_url=os.getenv("BINANCE_REST_URL", "https://data-api.binance.vision/api/v3").strip().rstrip("/"),
            heartbeat_interval_seconds=int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "15")),
            stale_data_seconds=int(os.getenv("STALE_DATA_SECONDS", "180")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    def missing_integrations(self) -> list[str]:
        missing = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        if self.supabase_url_issue:
            missing.append(self.supabase_url_issue)
        elif not self.supabase_url or not self.supabase_key:
            missing.append("SUPABASE_URL/SUPABASE_KEY")
        if not self.redis_url:
            missing.append("REDIS_URL")
        return missing

    @property
    def is_ready_for_live_notifications(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def is_ready_for_persistence(self) -> bool:
        return bool(self.supabase_url and self.supabase_key and not self.supabase_url_issue)
