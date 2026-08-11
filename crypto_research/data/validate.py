from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class ValidationReport:
    symbol: str
    rows: int
    duplicate_timestamps: int
    missing_candles: int
    invalid_ohlc: int
    negative_values: int
    non_monotonic: bool
    timezone_aware: bool
    extreme_return_count: int
    first_timestamp: str | None
    last_timestamp: str | None
    passed: bool
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_ohlcv(frame: pd.DataFrame, interval: str, symbol: str = "UNKNOWN", extreme_return: float = 0.50) -> ValidationReport:
    errors: list[str] = []
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing_columns = required - set(frame.columns)
    if missing_columns:
        return ValidationReport(symbol, len(frame), 0, 0, 0, 0, False, False, 0, None, None, False, [f"missing_columns={sorted(missing_columns)}"])

    df = frame.copy()
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    timezone_aware = bool(getattr(ts.dt, "tz", None) is not None)
    duplicate_count = int(ts.duplicated().sum())
    non_monotonic = not ts.is_monotonic_increasing
    numeric = df[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    negative_values = int((numeric < 0).sum().sum())
    invalid_ohlc = int((
        (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1))
        | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))
        | (numeric["open"] <= 0) | (numeric["high"] <= 0)
        | (numeric["low"] <= 0) | (numeric["close"] <= 0)
    ).sum())

    freq = pd.Timedelta(interval_to_pandas_freq(interval))
    clean_ts = ts.dropna().drop_duplicates().sort_values()
    gaps = clean_ts.diff().dropna()
    missing_candles = int(np.maximum((gaps / freq).round().astype(int) - 1, 0).sum()) if len(gaps) else 0
    returns = numeric["close"].pct_change().replace([np.inf, -np.inf], np.nan)
    extreme_count = int((returns.abs() > extreme_return).sum())

    if duplicate_count:
        errors.append(f"duplicate_timestamps={duplicate_count}")
    if non_monotonic:
        errors.append("timestamps_not_monotonic")
    if not timezone_aware:
        errors.append("timestamps_not_timezone_aware")
    if invalid_ohlc:
        errors.append(f"invalid_ohlc={invalid_ohlc}")
    if negative_values:
        errors.append(f"negative_values={negative_values}")
    if missing_candles:
        errors.append(f"missing_candles={missing_candles}")
    if extreme_count:
        errors.append(f"extreme_returns_review={extreme_count}")

    return ValidationReport(
        symbol=symbol, rows=len(df), duplicate_timestamps=duplicate_count,
        missing_candles=missing_candles, invalid_ohlc=invalid_ohlc,
        negative_values=negative_values, non_monotonic=non_monotonic,
        timezone_aware=timezone_aware, extreme_return_count=extreme_count,
        first_timestamp=str(clean_ts.iloc[0]) if len(clean_ts) else None,
        last_timestamp=str(clean_ts.iloc[-1]) if len(clean_ts) else None,
        passed=not any((duplicate_count, invalid_ohlc, negative_values, non_monotonic, not timezone_aware)),
        errors=errors,
    )


def interval_to_pandas_freq(interval: str) -> str:
    mapping = {"1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1D"}
    if interval not in mapping:
        raise ValueError(f"Unsupported interval: {interval}")
    return mapping[interval]


def validate_universe(universe: dict[str, pd.DataFrame], interval: str) -> pd.DataFrame:
    reports = [validate_ohlcv(frame, interval, symbol).to_dict() for symbol, frame in universe.items()]
    return pd.DataFrame(reports)
