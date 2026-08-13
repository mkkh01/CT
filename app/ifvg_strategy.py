from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from .models import Signal


@dataclass(frozen=True)
class IFVGZone:
    id: str
    fvg_direction: str
    ifvg_direction: str
    created_at: int
    inverted_at: int
    zone_low: float
    zone_high: float
    retest_at: Optional[int]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _close(candle: dict[str, Any]) -> float:
    return float(candle["close"])


def _open_time(candle: dict[str, Any]) -> int:
    return int(candle.get("open_time", candle.get("time", 0)))


def ema(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    multiplier = 2.0 / (period + 1.0)
    for price in values[period:]:
        value += (price - value) * multiplier
    return value


def atr(candles: list[dict[str, Any]], period: int = 14) -> Optional[float]:
    if len(candles) < period:
        return None
    ranges: list[float] = []
    previous_close: Optional[float] = None
    for candle in candles:
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)) if previous_close is not None else high - low)
        previous_close = close
    value = sum(ranges[:period]) / period
    for current in ranges[period:]:
        value = ((value * (period - 1)) + current) / period
    return value


def _zone_id(index: int, direction: str, candle: dict[str, Any]) -> str:
    key = f"ifvg-zone|{_open_time(candle)}|{index}|{direction}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def detect_fvgs(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect wick-based three-candle fair-value gaps without look-ahead."""
    zones: list[dict[str, Any]] = []
    for i in range(2, len(candles)):
        first, middle, third = candles[i - 2], candles[i - 1], candles[i]
        first_high, first_low = float(first["high"]), float(first["low"])
        third_high, third_low = float(third["high"]), float(third["low"])
        if first_high < third_low:
            zones.append({
                "id": _zone_id(i, "BULLISH", middle),
                "direction": "BULLISH",
                "created_at": _open_time(third),
                "candle_1_open_time": _open_time(first),
                "candle_2_open_time": _open_time(middle),
                "candle_3_open_time": _open_time(third),
                "zone_low": first_high,
                "zone_high": third_low,
            })
        elif first_low > third_high:
            zones.append({
                "id": _zone_id(i, "BEARISH", middle),
                "direction": "BEARISH",
                "created_at": _open_time(third),
                "candle_1_open_time": _open_time(first),
                "candle_2_open_time": _open_time(middle),
                "candle_3_open_time": _open_time(third),
                "zone_low": third_high,
                "zone_high": first_low,
            })
    return zones


def _touches(candle: dict[str, Any], low: float, high: float) -> bool:
    return float(candle["high"]) >= low and float(candle["low"]) <= high


def detect_ifvgs(candles: list[dict[str, Any]], max_age_candles: int = 200) -> list[IFVGZone]:
    """Convert broken FVGs into IFVG zones and record the first confirmed retest."""
    zones = detect_fvgs(candles)
    results: list[IFVGZone] = []
    for zone in zones:
        created_index = next((i for i, candle in enumerate(candles) if _open_time(candle) == zone["created_at"]), None)
        if created_index is None:
            continue
        inverted_index: Optional[int] = None
        ifvg_direction: Optional[str] = None
        for j in range(created_index + 1, len(candles)):
            close = _close(candles[j])
            if zone["direction"] == "BULLISH" and close < zone["zone_low"]:
                inverted_index = j
                ifvg_direction = "BEARISH"
                break
            if zone["direction"] == "BEARISH" and close > zone["zone_high"]:
                inverted_index = j
                ifvg_direction = "BULLISH"
                break
        if inverted_index is None or ifvg_direction is None:
            continue
        if len(candles) - inverted_index > max_age_candles:
            continue
        retest_at: Optional[int] = None
        status = "ACTIVE"
        for j in range(inverted_index + 1, len(candles)):
            candle = candles[j]
            if not _touches(candle, zone["zone_low"], zone["zone_high"]):
                continue
            close = _close(candle)
            confirmed = (ifvg_direction == "BULLISH" and close > zone["zone_high"]) or (ifvg_direction == "BEARISH" and close < zone["zone_low"])
            failed = (ifvg_direction == "BULLISH" and close < zone["zone_low"]) or (ifvg_direction == "BEARISH" and close > zone["zone_high"])
            if confirmed:
                retest_at = _open_time(candle)
                status = "RETESTED"
            elif failed:
                status = "FAILED"
            if status in {"RETESTED", "FAILED"}:
                break
        results.append(IFVGZone(
            id=zone["id"],
            fvg_direction=zone["direction"],
            ifvg_direction=ifvg_direction,
            created_at=zone["created_at"],
            inverted_at=_open_time(candles[inverted_index]),
            zone_low=float(zone["zone_low"]),
            zone_high=float(zone["zone_high"]),
            retest_at=retest_at,
            status=status,
        ))
    return results


def _higher_context(candles: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_close(candle) for candle in candles]
    ema20, ema50 = ema(closes, 20), ema(closes, 50)
    last = closes[-1] if closes else None
    if ema20 is None or ema50 is None or last is None:
        regime = "UNAVAILABLE"
    elif ema20 > ema50 and last > ema50:
        regime = "BULLISH"
    elif ema20 < ema50 and last < ema50:
        regime = "BEARISH"
    else:
        regime = "RANGE"
    return {"regime": regime, "ema20": ema20, "ema50": ema50, "close": last}


def evaluate_ifvg_signal_diagnostics(
    symbol: str,
    execution_candles: list[dict[str, Any]],
    higher_candles: list[dict[str, Any]],
    stop_loss_pct: float = 0.015,
    take_profit_r_multiple: float = 2.0,
    min_risk_reward: float = 1.5,
) -> tuple[Optional[Signal], dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "strategy": "IFVG",
        "strategy_version": "ifvg_v1",
        "symbol": symbol.upper(),
        "timeframe": "15m",
        "filter_passed": False,
        "data_ready": False,
        "rejection_reason": None,
        "rejection_detail": None,
        "ifvg_candidates": [],
    }
    if len(execution_candles) < 60 or len(higher_candles) < 60:
        diagnostics.update({
            "rejection_reason": "DATA_NOT_READY",
            "rejection_detail": f"يلزم 60 شمعة مغلقة على الأقل (15m:{len(execution_candles)}, 4h:{len(higher_candles)})",
        })
        return None, diagnostics

    diagnostics["data_ready"] = True
    context = _higher_context(higher_candles)
    zones = detect_ifvgs(execution_candles)
    diagnostics["higher_context"] = context
    diagnostics["ifvg_candidates"] = [zone.to_dict() for zone in zones[-20:]]
    last = execution_candles[-1]
    last_time = _open_time(last)
    candidates = [zone for zone in zones if zone.status == "RETESTED" and zone.retest_at == last_time]
    if not candidates:
        diagnostics.update({
            "rejection_reason": "NO_CONFIRMED_IFVG_RETEST",
            "rejection_detail": "لا توجد إعادة اختبار مؤكدة لـIFVG على آخر شمعة مغلقة",
        })
        return None, diagnostics

    zone = candidates[-1]
    side = "BUY" if zone.ifvg_direction == "BULLISH" else "SELL"
    context_ok = (side == "BUY" and context["regime"] == "BULLISH") or (side == "SELL" and context["regime"] == "BEARISH")
    diagnostics["active_ifvg"] = zone.to_dict()
    diagnostics["side"] = side
    diagnostics["context_match"] = context_ok
    if not context_ok:
        diagnostics.update({
            "rejection_reason": "HTF_CONTEXT_MISMATCH",
            "rejection_detail": f"اتجاه IFVG={side} لا يطابق سياق 4h={context['regime']}",
        })
        return None, diagnostics

    entry = _close(last)
    volatility = atr(execution_candles, 14) or entry * stop_loss_pct
    stop_buffer = max(entry * stop_loss_pct, volatility * 0.25)
    if side == "BUY":
        stop = min(entry - stop_buffer, zone.zone_low - volatility * 0.10)
        risk = entry - stop
        target = entry + risk * take_profit_r_multiple
    else:
        stop = max(entry + stop_buffer, zone.zone_high + volatility * 0.10)
        risk = stop - entry
        target = entry - risk * take_profit_r_multiple
    rr = abs(target - entry) / risk if risk > 0 else 0.0
    if risk <= 0 or rr < min_risk_reward:
        diagnostics.update({
            "rejection_reason": "INVALID_RISK_REWARD",
            "rejection_detail": f"مخاطرة غير صالحة أو R/R أقل من {min_risk_reward:.2f}",
            "entry_price": entry,
            "stop_loss": stop,
            "take_profit": target,
            "risk_reward": rr,
        })
        return None, diagnostics

    reason = f"IFVG {side}: {zone.fvg_direction} FVG inverted at {zone.inverted_at}, confirmed retest at {zone.retest_at}; HTF={context['regime']}"
    metadata = {
        "ifvg": zone.to_dict(),
        "higher_context": context,
        "entry_candle": {"open_time": last_time, "close": entry},
    }
    diagnostics.update({
        "filter_passed": True,
        "rejection_reason": None,
        "rejection_detail": "تم اجتياز IFVG inversion + retest + HTF context",
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": target,
        "risk_reward": rr,
        "conditions": {
            "confirmed_ifvg_retest": True,
            "higher_timeframe_context": True,
            "positive_risk_distance": risk > 0,
            "minimum_risk_reward": rr >= min_risk_reward,
        },
    })
    return Signal(
        symbol=symbol.upper(),
        timeframe="15m",
        generated_at=datetime.now(timezone.utc),
        candle_open_time=last_time,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        reason=reason,
        risk_reward=rr,
        side=side,
        strategy_version="ifvg_v1",
        metadata=metadata,
    ), diagnostics
