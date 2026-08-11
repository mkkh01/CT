from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .models import Signal


def _closes(candles: Iterable[dict[str, Any]]) -> list[float]:
    return [float(c["close"]) for c in candles]


def ema(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = (price - value) * multiplier + value
    return value


def rsi(values: list[float], period: int = 14) -> Optional[float]:
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for before, after in zip(values[-period - 1 : -1], values[-period:]):
        change = after - before
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def average_volume(candles: list[dict[str, Any]], period: int = 20) -> Optional[float]:
    if len(candles) < period:
        return None
    return sum(float(c["volume"]) for c in candles[-period:]) / period


def evaluate_signal(
    symbol: str,
    execution_candles: list[dict[str, Any]],
    higher_candles: list[dict[str, Any]],
    stop_loss_pct: float = 0.015,
    take_profit_r_multiple: float = 2.0,
) -> Optional[Signal]:
    """Return a long-only spot signal only after a fully closed execution candle.

    The strategy intentionally prefers fewer signals: higher-timeframe trend,
    moving-average alignment, breakout close, volume confirmation and a
    not-overbought filter must all pass.
    """
    if len(execution_candles) < 55 or len(higher_candles) < 55:
        return None

    last = execution_candles[-1]
    previous = execution_candles[-2]
    htf_closes = _closes(higher_candles)
    exec_closes = _closes(execution_candles)

    htf_ema20 = ema(htf_closes, 20)
    htf_ema50 = ema(htf_closes, 50)
    exec_ema20 = ema(exec_closes, 20)
    exec_ema50 = ema(exec_closes, 50)
    last_rsi = rsi(exec_closes, 14)
    avg_vol = average_volume(execution_candles, 20)

    if None in (htf_ema20, htf_ema50, exec_ema20, exec_ema50, last_rsi, avg_vol):
        return None

    close = float(last["close"])
    previous_high = float(previous["high"])
    volume = float(last["volume"])
    is_bullish_trend = close > float(htf_ema50) and float(htf_ema20) > float(htf_ema50)
    is_aligned = close > float(exec_ema20) > float(exec_ema50)
    is_breakout = close > previous_high
    has_volume = volume >= float(avg_vol) * 0.8
    not_overbought = float(last_rsi) <= 70.0
    bullish_body = close > float(last["open"])

    if not all((is_bullish_trend, is_aligned, is_breakout, has_volume, not_overbought, bullish_body)):
        return None

    stop_loss = close * (1 - stop_loss_pct)
    risk_per_unit = close - stop_loss
    take_profit = close + risk_per_unit * take_profit_r_multiple
    risk_reward = (take_profit - close) / risk_per_unit if risk_per_unit else 0.0

    if risk_reward < 1.5:
        return None

    return Signal(
        symbol=symbol.upper(),
        timeframe="1h",
        generated_at=datetime.now(timezone.utc),
        candle_open_time=int(last["open_time"]),
        entry_price=close,
        stop_loss=stop_loss,
        take_profit=take_profit,
        reason="4H uptrend + 1H EMA alignment + closed-candle breakout + volume confirmation",
        risk_reward=risk_reward,
    )
