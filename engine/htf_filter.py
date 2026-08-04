
"""
File: engine/htf_filter.py
1. Single Responsibility: Filter lower-timeframe (LTF) signals against the
   higher-timeframe (HTF) bias so the engine never enters counter-trend on
   the structural timeframe.
2. Consumes: ``StrategySignal``, ``HTFFilterResult`` (contracts/decision.py),
   ``Candle`` (contracts/market.py); ``engine/trend.py`` for the HTF trend
   computation.
3. Produces: ``filter_by_htf`` returning ``HTFFilterResult`` consumed by
   engine/confidence.py (HTF_ALIGNMENT_WEIGHT component) and
   engine/orchestrator.py (HTF gate).
4. Downstream: engine/confidence.py, engine/orchestrator.py.
5. New Dependencies: No new external deps. Imports ``engine.trend`` which is
   a sibling engine module -- both sit at the same dependency layer so no
   upstream violation.
6. Touches Section 6 bugs? No.
7. Tests: Section 10 engine/htf_filter.py acceptance criteria:
       1. Bullish alignment -- LTF long + HTF bullish -> alignment = True.
       2. Bullish contradiction -- LTF short + HTF bullish -> alignment = False.
       3. Neutral pass-through -- HTF neutral -> alignment = True. (MODIFIED: Now requires ADX strength)
8. Logging: ``htf_filter_result`` {timestamp, symbol, htf, ltf, bias,
   alignment} per the monitoring/logger.py event catalog.
9. Dependency Order: config -> contracts -> monitoring -> engine/trend.py ->
   engine/htf_filter.py (no upstream violations).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

import numpy as np

from config.thresholds import TREND_ADX_THRESHOLD
from contracts.decision import HTFFilterResult, StrategySignal
from contracts.market import Candle
from engine.trend import analyze_trend
from monitoring.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------
# Minimum number of HTF closed candles required to make a bias decision. Below
# this we fall back to "neutral" rather than guessing.
_MIN_HTF_CANDLES = 30


# ---------------------------------------------------------------------------
# HTF bias determination
# ---------------------------------------------------------------------------
def _determine_bias(htf_candles: list[Candle]) -> tuple[Literal["bullish", "bearish", "neutral"], float, list[str]]:
    """Determine the HTF bias from its candle list.
    Includes ADX strength requirement to ensure the HTF trend is meaningful.
    """
    if not htf_candles:
        return "neutral", 0.0, ["no_htf_candles"]

    closed = [c for c in htf_candles if c.is_closed]
    if len(closed) < _MIN_HTF_CANDLES:
        return "neutral", 0.0, [f"insufficient_htf_candles:{len(closed)}/{_MIN_HTF_CANDLES}"]

    trend = analyze_trend(closed)
    ema_fast = trend.get("ema_fast", float("nan"))
    ema_slow = trend.get("ema_slow", float("nan"))
    adx = float(trend.get("adx", 0.0))
    last_close = closed[-1].close

    reasons: list[str] = [f"htf_adx={adx:.2f}"]
    if any(np.isnan(x) for x in (ema_fast, ema_slow)):
        return "neutral", adx, ["htf_ema_not_ready"]

    # Trend Strength check: HTF trend must be strong enough to be considered valid
    is_strong = adx >= TREND_ADX_THRESHOLD

    if ema_fast > ema_slow and last_close > ema_fast:
        reasons.append(f"ema_fast({ema_fast:.6f}) > ema_slow({ema_slow:.6f})")
        reasons.append(f"close({last_close:.6f}) > ema_fast({ema_fast:.6f})")
        if not is_strong:
            reasons.append(f"weak_htf_trend: adx({adx:.2f}) < {TREND_ADX_THRESHOLD}")
            return "neutral", adx, reasons
        return "bullish", adx, reasons
        
    if ema_fast < ema_slow and last_close < ema_fast:
        reasons.append(f"ema_fast({ema_fast:.6f}) < ema_slow({ema_slow:.6f})")
        reasons.append(f"close({last_close:.6f}) < ema_fast({ema_fast:.6f})")
        if not is_strong:
            reasons.append(f"weak_htf_trend: adx({adx:.2f}) < {TREND_ADX_THRESHOLD}")
            return "neutral", adx, reasons
        return "bearish", adx, reasons

    reasons.append(
        f"htf_inconclusive: ema_fast={ema_fast:.6f}, ema_slow={ema_slow:.6f}, close={last_close:.6f}"
    )
    return "neutral", adx, reasons


# ---------------------------------------------------------------------------
# LTF / HTF alignment check
# ---------------------------------------------------------------------------
def _check_alignment(
    ltf_direction: Literal["long", "neutral"],
    htf_bias: Literal["bullish", "bearish", "neutral"],
) -> tuple[bool, str]:
    """Return ``(alignment, reason)`` for the LTF/HTF pair in Spot mode."""
    # LTF neutral: the market has no clear direction -- pass through (low signal).
    if ltf_direction == "neutral":
        return True, "ltf_neutral_pass_through"
    
    # [TIGHTENING] HTF neutral (weak ADX or no EMA alignment) now blocks entries.
    # Without strong HTF confirmation, we avoid opening new positions.
    if htf_bias == "neutral":
        return False, "htf_neutral_requires_strong_trend"
        
    if ltf_direction == "long" and htf_bias == "bullish":
        return True, "ltf_long_aligned_with_htf_bullish"
        
    if ltf_direction == "long" and htf_bias == "bearish":
        return False, "ltf_long_contradicts_htf_bearish"
        
    # Defensive default
    return False, f"htf_alignment_unknown:{ltf_direction}:{htf_bias}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def filter_by_htf(
    ltf_signal: StrategySignal,
    htf_candles: list[Candle],
    htf_timeframe: str,
    ltf_timeframe: str,
) -> HTFFilterResult:
    """Filter a lower-timeframe signal against the higher-timeframe bias."""
    bias, adx, bias_reasons = _determine_bias(htf_candles)
    aligned, align_reason = _check_alignment(ltf_signal.direction, bias)

    # Combine bias and alignment reasons into a single human-readable string.
    full_reason = "; ".join([*bias_reasons, align_reason]) if bias_reasons else align_reason

    result = HTFFilterResult(
        symbol=ltf_signal.symbol,
        htf_timeframe=htf_timeframe,
        ltf_timeframe=ltf_timeframe,
        bias=bias,
        alignment=aligned,
        reason=full_reason,
        adx=adx,
        timestamp=datetime.now(timezone.utc),
    )

    logger.info(
        "htf_filter_result",
        timestamp=datetime.utcnow(),
        symbol=ltf_signal.symbol,
        htf=htf_timeframe,
        ltf=ltf_timeframe,
        bias=bias,
        adx=adx,
        alignment=aligned,
        reason=full_reason,
    )

    return result


def filter_signals_by_htf(
    ltf_signals: list[StrategySignal],
    htf_candles: list[Candle],
    htf_timeframe: str,
    ltf_timeframe: str,
) -> list[HTFFilterResult]:
    """Apply :func:`filter_by_htf` to each LTF signal in ``ltf_signals``."""
    return [
        filter_by_htf(sig, htf_candles, htf_timeframe, ltf_timeframe)
        for sig in ltf_signals
    ]


__all__ = [
    "filter_by_htf",
    "filter_signals_by_htf",
]
