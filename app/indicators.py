from __future__ import annotations

from statistics import mean
from typing import Iterable

from .models import Candle, SwingPoint


def true_ranges(candles: list[Candle]) -> list[float]:
    ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        if previous_close is None:
            ranges.append(candle.high - candle.low)
        else:
            ranges.append(max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close)))
        previous_close = candle.close
    return ranges


def atr(candles: list[Candle], period: int = 14) -> float:
    if not candles:
        return 0.0
    values = true_ranges(candles)
    return mean(values[-period:]) if values else 0.0


def ema(values: Iterable[float], period: int) -> float:
    data = list(values)
    if not data:
        return 0.0
    alpha = 2 / (period + 1)
    result = data[0]
    for value in data[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi(candles: list[Candle], period: int = 14) -> float:
    closes = [c.close for c in candles]
    if len(closes) < 2:
        return 50.0
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    window = changes[-period:]
    gains = [change for change in window if change > 0]
    losses = [-change for change in window if change < 0]
    average_gain = sum(gains) / len(window) if window else 0.0
    average_loss = sum(losses) / len(window) if window else 0.0
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    return 100 - (100 / (1 + average_gain / average_loss))


def detect_swings(candles: list[Candle], left: int = 3, right: int = 3) -> tuple[list[SwingPoint], list[SwingPoint]]:
    highs: list[SwingPoint] = []
    lows: list[SwingPoint] = []
    if len(candles) < left + right + 1:
        return highs, lows
    for index in range(left, len(candles) - right):
        current = candles[index]
        left_slice = candles[index - left:index]
        right_slice = candles[index + 1:index + right + 1]
        if all(current.high > item.high for item in left_slice + right_slice):
            highs.append(SwingPoint("HIGH", index, current.high, current.open_time))
        if all(current.low < item.low for item in left_slice + right_slice):
            lows.append(SwingPoint("LOW", index, current.low, current.open_time))
    return highs, lows


def relative_volume(candles: list[Candle], period: int = 20) -> dict[str, float | bool]:
    if not candles:
        return {"current": 0.0, "average": 0.0, "relative": 0.0, "above_average": False}
    current = candles[-1].volume
    history = [item.volume for item in candles[-period - 1:-1]]
    average = mean(history) if history else current
    relative = current / average if average else 0.0
    return {"current": current, "average": average, "relative": relative, "above_average": relative >= 1.1}


def momentum_context(candles: list[Candle]) -> dict[str, float | str | bool]:
    values = [c.close for c in candles]
    if len(values) < 3:
        return {"rsi": 50.0, "roc": 0.0, "direction": "NEUTRAL", "confirming": False}
    current = values[-1]
    previous = values[-4] if len(values) >= 4 else values[0]
    roc = ((current - previous) / previous * 100) if previous else 0.0
    rsi_value = rsi(candles)
    if roc > 0 and rsi_value >= 50:
        direction = "BULLISH"
    elif roc < 0 and rsi_value <= 50:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"
    return {"rsi": round(rsi_value, 4), "roc": round(roc, 4), "direction": direction, "confirming": direction != "NEUTRAL"}
