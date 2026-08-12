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


CANDLE_LABELS = {
    "BULLISH_MARUBOZU": "صاعدة قوية بلا ظلال تقريباً",
    "BEARISH_MARUBOZU": "هابطة قوية بلا ظلال تقريباً",
    "BULLISH_ENGULFING": "ابتلاع صاعد",
    "BEARISH_ENGULFING": "ابتلاع هابط",
    "HAMMER": "مطرقة / رفض هابط",
    "SHOOTING_STAR": "نجمة ساقطة / رفض صاعد",
    "DOJI": "دوجي / تردد",
    "SPINNING_TOP": "جسم صغير وظلال متوازنة",
    "BULLISH": "شمعة صاعدة",
    "BEARISH": "شمعة هابطة",
    "NEUTRAL": "شمعة محايدة",
}

REGIME_LABELS = {
    "UPTREND": "اتجاه صاعد",
    "DOWNTREND": "اتجاه هابط",
    "SIDEWAYS": "سوق عرضي",
    "HIGH_VOLATILITY": "تذبذب مرتفع",
    "UNAVAILABLE": "غير متاح",
}


def classify_candle(candle: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify one closed candle using body, wick, and two-candle context."""
    open_price = float(candle["open"])
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])
    candle_range = max(high - low, 1e-12)
    body = abs(close - open_price)
    upper_wick = max(0.0, high - max(open_price, close))
    lower_wick = max(0.0, min(open_price, close) - low)
    body_ratio = body / candle_range
    upper_wick_ratio = upper_wick / candle_range
    lower_wick_ratio = lower_wick / candle_range
    direction = "BULLISH" if close > open_price else ("BEARISH" if close < open_price else "NEUTRAL")
    pattern = direction

    if previous:
        previous_open = float(previous["open"])
        previous_close = float(previous["close"])
        previous_body_high = max(previous_open, previous_close)
        previous_body_low = min(previous_open, previous_close)
        current_body_high = max(open_price, close)
        current_body_low = min(open_price, close)
        if previous_close < previous_open and close > open_price and current_body_high >= previous_body_high and current_body_low <= previous_body_low:
            pattern = "BULLISH_ENGULFING"
        elif previous_close > previous_open and close < open_price and current_body_high >= previous_body_high and current_body_low <= previous_body_low:
            pattern = "BEARISH_ENGULFING"

    if pattern in ("BULLISH", "BEARISH", "NEUTRAL"):
        if body_ratio <= 0.10:
            pattern = "DOJI"
            direction = "NEUTRAL"
        elif body_ratio >= 0.75 and upper_wick_ratio <= 0.12 and lower_wick_ratio <= 0.12:
            pattern = "BULLISH_MARUBOZU" if direction == "BULLISH" else "BEARISH_MARUBOZU"
        elif lower_wick_ratio >= 0.50 and upper_wick_ratio <= 0.20 and body_ratio <= 0.40:
            pattern = "HAMMER"
        elif upper_wick_ratio >= 0.50 and lower_wick_ratio <= 0.20 and body_ratio <= 0.40:
            pattern = "SHOOTING_STAR"
        elif body_ratio <= 0.30 and upper_wick_ratio >= 0.25 and lower_wick_ratio >= 0.25:
            pattern = "SPINNING_TOP"

    return {
        "pattern": pattern,
        "pattern_label": CANDLE_LABELS.get(pattern, pattern),
        "direction": direction,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "range": candle_range,
        "body": body,
        "body_ratio": body_ratio,
        "upper_wick_ratio": upper_wick_ratio,
        "lower_wick_ratio": lower_wick_ratio,
    }


def regime_label(regime: str | None) -> str:
    return REGIME_LABELS.get(regime or "UNAVAILABLE", regime or "غير متاح")


def _true_ranges(candles: list[dict[str, Any]]) -> list[float]:
    if not candles:
        return []
    ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        ranges.append(true_range)
        previous_close = close
    return ranges


def atr(candles: list[dict[str, Any]], period: int = 14) -> Optional[float]:
    """Return Wilder-smoothed ATR for the supplied closed candles."""
    if len(candles) < period:
        return None
    ranges = _true_ranges(candles)
    value = sum(ranges[:period]) / period
    for true_range in ranges[period:]:
        value = ((value * (period - 1)) + true_range) / period
    return value


def adx_dmi(candles: list[dict[str, Any]], period: int = 14) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return Wilder ADX, +DI, and -DI from closed candles."""
    if len(candles) < period * 2 + 1:
        return None, None, None

    true_ranges: list[float] = []
    plus_moves: list[float] = []
    minus_moves: list[float] = []
    for previous, current in zip(candles[:-1], candles[1:]):
        previous_close = float(previous["close"])
        high = float(current["high"])
        low = float(current["low"])
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        up_move = high - float(previous["high"])
        down_move = float(previous["low"]) - low
        plus_moves.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_moves.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    smoothed_true_range = sum(true_ranges[:period])
    smoothed_plus = sum(plus_moves[:period])
    smoothed_minus = sum(minus_moves[:period])
    dx_values: list[float] = []
    last_plus_di: float | None = None
    last_minus_di: float | None = None

    for index in range(period, len(true_ranges)):
        if index > period:
            smoothed_true_range = smoothed_true_range - (smoothed_true_range / period) + true_ranges[index]
            smoothed_plus = smoothed_plus - (smoothed_plus / period) + plus_moves[index]
            smoothed_minus = smoothed_minus - (smoothed_minus / period) + minus_moves[index]
        if smoothed_true_range == 0:
            last_plus_di = 0.0
            last_minus_di = 0.0
            dx_values.append(0.0)
            continue
        last_plus_di = 100 * smoothed_plus / smoothed_true_range
        last_minus_di = 100 * smoothed_minus / smoothed_true_range
        denominator = last_plus_di + last_minus_di
        dx_values.append(100 * abs(last_plus_di - last_minus_di) / denominator if denominator else 0.0)

    if len(dx_values) < period or last_plus_di is None or last_minus_di is None:
        return None, last_plus_di, last_minus_di
    adx_value = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx_value = ((adx_value * (period - 1)) + dx) / period
    return adx_value, last_plus_di, last_minus_di


def bollinger_bands_squeeze(candles: list[dict[str, Any]], period: int = 20, std_dev: float = 2.0) -> dict[str, Any]:
    """Calculate Bollinger Bands and check for Volatility Squeeze."""
    closes = _closes(candles)
    if len(closes) < period:
        return {"squeeze": False, "bandwidth": 0.0}
    sma = sum(closes[-period:]) / period
    variance = sum((x - sma) ** 2 for x in closes[-period:]) / period
    std = variance ** 0.5
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    bandwidth = (upper - lower) / sma if sma else 0.0
    # Squeeze defined when bandwidth is at its lowest relative to recent history (e.g. 20 periods)
    if len(closes) >= period * 2:
        historical_bandwidths = []
        for i in range(period, len(closes)):
            sub_closes = closes[i-period:i]
            sub_sma = sum(sub_closes) / period
            sub_var = sum((x - sub_sma) ** 2 for x in sub_closes) / period
            sub_std = sub_var ** 0.5
            sub_bw = ((sub_sma + (std_dev * sub_std)) - (sub_sma - (std_dev * sub_std))) / sub_sma if sub_sma else 0.0
            historical_bandwidths.append(sub_bw)
        min_bw = min(historical_bandwidths) if historical_bandwidths else bandwidth
        is_squeeze = bandwidth <= min_bw * 1.15
    else:
        is_squeeze = bandwidth < 0.04 # fallback threshold for crypto
    return {"squeeze": is_squeeze, "bandwidth": bandwidth, "upper": upper, "lower": lower, "sma": sma}


def detect_market_structure(candles: list[dict[str, Any]], lookback: int = 5) -> str:
    """Detect Market Structure (Higher Highs / Higher Lows or Lower Highs / Lower Lows)."""
    if len(candles) < lookback * 2:
        return "RANGE"
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    
    # Check recent swing highs and lows
    recent_highs = highs[-lookback*2:]
    recent_lows = lows[-lookback*2:]
    
    mid = len(recent_highs) // 2
    first_half_high = max(recent_highs[:mid])
    second_half_high = max(recent_highs[mid:])
    
    first_half_low = min(recent_lows[:mid])
    second_half_low = min(recent_lows[mid:])
    
    if second_half_high > first_half_high and second_half_low > first_half_low:
        return "BULLISH_STRUCTURE" # Higher Highs & Higher Lows
    elif second_half_high < first_half_high and second_half_low < first_half_low:
        return "BEARISH_STRUCTURE" # Lower Highs & Lower Lows
    return "CONSOLIDATION"


def market_filter_diagnostics(
    candles: list[dict[str, Any]],
    adx_period: int = 14,
    adx_min: float = 25.0,
    atr_period: int = 14,
    atr_min_pct: float = 0.003,
    atr_max_pct: float = 0.08,
) -> dict[str, Any]:
    """Classify the execution market before allowing a long breakout."""
    close = float(candles[-1]["close"]) if candles else 0.0
    atr_value = atr(candles, atr_period)
    adx_value, plus_di, minus_di = adx_dmi(candles, adx_period)
    atr_pct = (atr_value / close) if atr_value is not None and close > 0 else None
    metrics: dict[str, Any] = {
        "market_regime": "UNAVAILABLE",
        "adx": adx_value,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "atr": atr_value,
        "atr_pct": atr_pct,
        "adx_period": adx_period,
        "adx_min": adx_min,
        "atr_period": atr_period,
        "atr_min_pct": atr_min_pct,
        "atr_max_pct": atr_max_pct,
        "filter_passed": False,
        "rejection_reason": "INDICATOR_NOT_READY",
        "rejection_detail": "ADX أو ATR غير متاحين بعد",
    }
    if adx_value is None or plus_di is None or minus_di is None or atr_pct is None:
        return metrics
    if adx_value < adx_min:
        metrics.update({
            "market_regime": "SIDEWAYS",
            "rejection_reason": "SIDEWAYS_ADX_LOW",
            "rejection_detail": f"ADX {adx_value:.2f} أقل من الحد {adx_min:.2f}",
        })
        return metrics
    if plus_di <= minus_di:
        metrics.update({
            "market_regime": "DOWNTREND",
            "rejection_reason": "BEARISH_DIRECTIONAL_MOVEMENT",
            "rejection_detail": f"+DI {plus_di:.2f} ليس أعلى من -DI {minus_di:.2f}",
        })
        return metrics
    if atr_pct < atr_min_pct:
        metrics.update({
            "market_regime": "SIDEWAYS",
            "rejection_reason": "SIDEWAYS_ATR_LOW",
            "rejection_detail": f"ATR/السعر {atr_pct * 100:.3f}% أقل من الحد {atr_min_pct * 100:.3f}%",
        })
        return metrics
    if atr_pct > atr_max_pct:
        metrics.update({
            "market_regime": "HIGH_VOLATILITY",
            "rejection_reason": "VOLATILITY_TOO_HIGH",
            "rejection_detail": f"ATR/السعر {atr_pct * 100:.3f}% أعلى من الحد {atr_max_pct * 100:.3f}%",
        })
        return metrics
    metrics.update({
        "market_regime": "UPTREND",
        "filter_passed": True,
        "rejection_reason": None,
        "rejection_detail": "قوة الاتجاه والتذبذب مناسبان للاختراق",
    })
    return metrics


def classify_chart(
    execution_candles: list[dict[str, Any]],
    higher_candles: list[dict[str, Any]],
    adx_period: int = 14,
    adx_min: float = 25.0,
    atr_period: int = 14,
    atr_min_pct: float = 0.003,
    atr_max_pct: float = 0.08,
) -> dict[str, Any]:
    """Return chart regime, latest candle classification, and indicator context."""
    if not execution_candles or not higher_candles:
        return {
            "chart_regime": "UNAVAILABLE",
            "chart_regime_label": regime_label("UNAVAILABLE"),
            "candle": None,
            "rejection_reason": "DATA_NOT_READY",
        }
    previous = execution_candles[-2] if len(execution_candles) >= 2 else None
    higher_previous = higher_candles[-2] if len(higher_candles) >= 2 else None
    candle = classify_candle(execution_candles[-1], previous)
    higher_candle = classify_candle(higher_candles[-1], higher_previous)
    market = market_filter_diagnostics(
        execution_candles,
        adx_period=adx_period,
        adx_min=adx_min,
        atr_period=atr_period,
        atr_min_pct=atr_min_pct,
        atr_max_pct=atr_max_pct,
    )
    higher_market = market_filter_diagnostics(
        higher_candles,
        adx_period=adx_period,
        adx_min=adx_min,
        atr_period=atr_period,
        atr_min_pct=atr_min_pct,
        atr_max_pct=atr_max_pct,
    )
    exec_closes = _closes(execution_candles)
    higher_closes = _closes(higher_candles)
    ema20_1h = ema(exec_closes, 20)
    ema50_1h = ema(exec_closes, 50)
    ema20_4h = ema(higher_closes, 20)
    ema50_4h = ema(higher_closes, 50)
    regime = market.get("market_regime", "UNAVAILABLE")
    if regime == "UPTREND" and ema20_1h is not None and ema50_1h is not None and ema20_1h <= ema50_1h:
        regime = "SIDEWAYS"
    if regime == "DOWNTREND" and ema20_1h is not None and ema50_1h is not None and ema20_1h >= ema50_1h:
        regime = "SIDEWAYS"
    if regime == "SIDEWAYS" and market.get("filter_passed"):
        market["filter_passed"] = False
        market["rejection_reason"] = "EMA_ALIGNMENT_SIDEWAYS"
        market["rejection_detail"] = "ADX/ATR مقبولان لكن EMA20 وEMA50 لا يؤكدان اتجاهاً واضحاً"
    higher_regime = higher_market.get("market_regime", "UNAVAILABLE")
    if higher_regime == "UPTREND" and ema20_4h is not None and ema50_4h is not None and ema20_4h <= ema50_4h:
        higher_regime = "SIDEWAYS"
    if higher_regime == "DOWNTREND" and ema20_4h is not None and ema50_4h is not None and ema20_4h >= ema50_4h:
        higher_regime = "SIDEWAYS"
    return {
        **market,
        "chart_regime": regime,
        "chart_regime_label": regime_label(regime),
        "chart_regime_1h": regime,
        "chart_regime_1h_label": regime_label(regime),
        "chart_regime_4h": higher_regime,
        "chart_regime_4h_label": regime_label(higher_regime),
        "candle": candle,
        "candle_1h": candle,
        "candle_4h": higher_candle,
        "ema20_1h": ema20_1h,
        "ema50_1h": ema50_1h,
        "ema20_4h": ema20_4h,
        "ema50_4h": ema50_4h,
    }


def evaluate_signal_diagnostics(
    symbol: str,
    execution_candles: list[dict[str, Any]],
    higher_candles: list[dict[str, Any]],
    stop_loss_pct: float = 0.015,
    take_profit_r_multiple: float = 2.0,
    adx_period: int = 14,
    adx_min: float = 25.0,
    atr_period: int = 14,
    atr_min_pct: float = 0.003,
    atr_max_pct: float = 0.08,
) -> tuple[Optional[Signal], dict[str, Any]]:
    """Evaluate the long breakout and return a machine-readable reason when it fails."""
    exec_len = len(execution_candles) if execution_candles else 0
    high_len = len(higher_candles) if higher_candles else 0
    
    if exec_len < 55 or high_len < 55:
        return None, {
            "market_regime": "UNAVAILABLE",
            "filter_passed": False,
            "rejection_reason": "DATA_NOT_READY",
            "rejection_detail": f"أقل من 55 شمعة مغلقة (1h:{exec_len}, 4h:{high_len})",
        }

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
    chart = classify_chart(
        execution_candles,
        higher_candles,
        adx_period=adx_period,
        adx_min=adx_min,
        atr_period=atr_period,
        atr_min_pct=atr_min_pct,
        atr_max_pct=atr_max_pct,
    )

    diagnostics = {
        **chart,
        "market_regime": chart.get("chart_regime"),
        "candle_pattern": (chart.get("candle") or {}).get("pattern"),
        "candle_pattern_label": (chart.get("candle") or {}).get("pattern_label"),
        "candle_direction": (chart.get("candle") or {}).get("direction"),
        "candle_1h": chart.get("candle_1h"),
        "candle_4h": chart.get("candle_4h"),
        "candle_pattern_1h": (chart.get("candle_1h") or {}).get("pattern"),
        "candle_pattern_label_1h": (chart.get("candle_1h") or {}).get("pattern_label"),
        "candle_direction_1h": (chart.get("candle_1h") or {}).get("direction"),
        "candle_pattern_4h": (chart.get("candle_4h") or {}).get("pattern"),
        "candle_pattern_label_4h": (chart.get("candle_4h") or {}).get("pattern_label"),
        "candle_direction_4h": (chart.get("candle_4h") or {}).get("direction"),
        "rsi": last_rsi,
        "average_volume": avg_vol,
        "close": float(last["close"]),
        "ema20_1h": exec_ema20,
        "ema50_1h": exec_ema50,
        "ema20_4h": htf_ema20,
        "ema50_4h": htf_ema50,
    }
    if None in (htf_ema20, htf_ema50, exec_ema20, exec_ema50, last_rsi, avg_vol):
        diagnostics.update({
            "rejection_reason": "INDICATOR_NOT_READY",
            "rejection_detail": "مؤشر EMA أو RSI أو متوسط الحجم غير متاح",
            "filter_passed": False,
        })
        return None, diagnostics
    if not chart["filter_passed"]:
        return None, diagnostics

    close = float(last["close"])
    previous_high = float(previous["high"])
    volume = float(last["volume"])
    candle_1h = chart.get("candle_1h") or {}
    
    # Advanced Institutional Filters
    structure = detect_market_structure(execution_candles)
    bb = bollinger_bands_squeeze(execution_candles)
    diagnostics["market_structure"] = structure
    diagnostics["bb_squeeze"] = bb.get("squeeze")
    diagnostics["bb_bandwidth"] = bb.get("bandwidth")

    accepted_candle_patterns = {"BULLISH", "BULLISH_MARUBOZU", "BULLISH_ENGULFING", "HAMMER"}
    conditions = {
        "bullish_trend_4h": close > float(htf_ema50) and float(htf_ema20) > float(htf_ema50),
        "ema_alignment_1h": close > float(exec_ema20) > float(exec_ema50),
        "market_structure_bullish": structure == "BULLISH_STRUCTURE" or structure == "CONSOLIDATION",
        "breakout_above_previous_high": close > previous_high,
        "volume_confirmation": volume >= float(avg_vol) * 0.8,
        "not_overbought": float(last_rsi) <= 70.0,
        "bullish_body": close > float(last["open"]),
        "candle_pattern_confirmation": candle_1h.get("pattern") in accepted_candle_patterns and candle_1h.get("direction") == "BULLISH",
    }
    diagnostics["conditions"] = conditions
    failed = [name for name, passed in conditions.items() if not passed]
    if failed:
        diagnostics.update({
            "rejection_reason": "NO_SIGNAL",
            "rejection_detail": "الشروط غير المكتملة: " + ", ".join(failed) + f" | شمعة 1H: {candle_1h.get('pattern_label', 'غير متاح')}",
            "filter_passed": True,
        })
        return None, diagnostics

    stop_loss = close * (1 - stop_loss_pct)
    risk_per_unit = close - stop_loss
    take_profit = close + risk_per_unit * take_profit_r_multiple
    risk_reward = (take_profit - close) / risk_per_unit if risk_per_unit else 0.0
    if risk_reward < 1.5:
        diagnostics.update({
            "rejection_reason": "RISK_REWARD_TOO_LOW",
            "rejection_detail": f"Risk/Reward {risk_reward:.2f} أقل من 1.50",
            "filter_passed": True,
        })
        return None, diagnostics

    diagnostics.update({
        "rejection_reason": None,
        "rejection_detail": "تم اجتياز فلتر ADX/ATR وكل شروط الاختراق",
        "filter_passed": True,
    })
    return Signal(
        symbol=symbol.upper(),
        timeframe="1h",
        generated_at=datetime.now(timezone.utc),
        candle_open_time=int(last["open_time"]),
        entry_price=close,
        stop_loss=stop_loss,
        take_profit=take_profit,
        reason="4H uptrend + 1H EMA alignment + ADX/ATR regime filter + closed-candle breakout + volume confirmation",
        risk_reward=risk_reward,
    ), diagnostics


def evaluate_signal(
    symbol: str,
    execution_candles: list[dict[str, Any]],
    higher_candles: list[dict[str, Any]],
    stop_loss_pct: float = 0.015,
    take_profit_r_multiple: float = 2.0,
) -> Optional[Signal]:
    signal, _ = evaluate_signal_diagnostics(
        symbol,
        execution_candles,
        higher_candles,
        stop_loss_pct=stop_loss_pct,
        take_profit_r_multiple=take_profit_r_multiple,
    )
    return signal
