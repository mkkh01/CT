"""
File: engine/confidence.py
1. Single Responsibility: Aggregate all component signals and indicator
   scores into a single confidence value in ``[0, 1]`` and gate it against
   the configured threshold.
2. Consumes: ``StrategySignal``, ``HTFFilterResult`` (contracts/decision.py),
   ``RegimeState`` (contracts/market.py); thresholds from
   config/thresholds.py (HTF_ALIGNMENT_WEIGHT, STRUCTURE_WEIGHT,
   MOMENTUM_WEIGHT, LIQUIDITY_WEIGHT, SESSION_WEIGHT, CONFIDENCE_THRESHOLD,
   REGIME_MODIFIER_*).
3. Produces: ``calculate_confidence``, ``confidence_gate``,
   ``aggregate_score`` consumed by engine/orchestrator.py.
4. Downstream: engine/orchestrator.py (the only caller that combines the
   confidence value with risk assessment to produce a final verdict).
5. New Dependencies: No new external deps.
6. Touches Section 6 bugs? No.
7. Tests: Section 10 engine/confidence.py acceptance criteria:
       1. Weight validation -- the sum of all component weights must equal
          1.0 (+/-0.001). Validated at module load via ``_WEIGHT_SUM``.
       2. Threshold gate -- a final confidence below
          ``CONFIDENCE_THRESHOLD`` results in ``final_verdict = False``.
       3. High confidence pass -- a final confidence above
          ``CONFIDENCE_THRESHOLD`` with all checks passed results in
          ``final_verdict = True``.
8. Logging: ``confidence_calculated`` {timestamp, symbol, confidence,
   regime_modifier} per the monitoring/logger.py event catalog.
9. Dependency Order: config -> contracts -> monitoring -> engine/confidence.py
   (no upstream violations).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from dataclasses import dataclass

from config.thresholds import (
    CONTRADICTION_PENALTY_MULTIPLIER,
    CONFIDENCE_THRESHOLD,
    HTF_ALIGNMENT_WEIGHT,
    LIQUIDITY_WEIGHT,
    MOMENTUM_WEIGHT,
    REGIME_MODIFIER_RANGING,
    REGIME_MODIFIER_TRENDING,
    REGIME_MODIFIER_VOLATILE,
    SESSION_WEIGHT,
    STRUCTURE_WEIGHT,
)
from contracts.decision import HTFFilterResult, StrategySignal
from contracts.market import RegimeState
from monitoring.logger import get_logger


def normalize_direction(value: Any) -> str:
    """Standardise direction strings to 'long', 'short', or 'neutral'."""
    if value is None:
        return "neutral"
    normalized = str(value).strip().lower()
    if normalized in {"bullish", "up", "long", "buy", "long_bias"}:
        return "long"
    if normalized in {"bearish", "down", "short", "sell", "short_bias"}:
        return "short"
    return "neutral"

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Weight-sum validation (Section 10 criterion 1 -- sum MUST equal 1.0 ±0.001)
# ---------------------------------------------------------------------------
_WEIGHT_SUM = (
    HTF_ALIGNMENT_WEIGHT
    + STRUCTURE_WEIGHT
    + MOMENTUM_WEIGHT
    + LIQUIDITY_WEIGHT
    + SESSION_WEIGHT
)
_WEIGHT_TOLERANCE = 0.001

if abs(_WEIGHT_SUM - 1.0) > _WEIGHT_TOLERANCE:
    # Section 10 acceptance criterion 1 is non-negotiable. We raise at import
    # time so any misconfiguration is caught immediately by the test suite
    # rather than producing silently-miscalibrated confidence scores in
    # production.
    raise AssertionError(
        "confidence weight sum must equal 1.0 +/-0.001; "
        f"got {_WEIGHT_SUM:.6f} "
        f"(HTF={HTF_ALIGNMENT_WEIGHT}, STRUCTURE={STRUCTURE_WEIGHT}, "
        f"MOMENTUM={MOMENTUM_WEIGHT}, LIQUIDITY={LIQUIDITY_WEIGHT}, "
        f"SESSION={SESSION_WEIGHT})"
    )


# ---------------------------------------------------------------------------
# Regime modifier lookup
# ---------------------------------------------------------------------------
_REGIME_MODIFIERS: dict[RegimeState, float] = {
    RegimeState.TRENDING: REGIME_MODIFIER_TRENDING,
    RegimeState.RANGING: REGIME_MODIFIER_RANGING,
    RegimeState.VOLATILE: REGIME_MODIFIER_VOLATILE,
}


def _regime_modifier(regime: RegimeState) -> float:
    """Return the confidence multiplier for ``regime``.

    Defaults to ``REGIME_MODIFIER_RANGING`` for any unknown regime value
    (defensive -- the enum is closed but the lookup should never raise).
    """
    return _REGIME_MODIFIERS.get(regime, REGIME_MODIFIER_RANGING)


@dataclass(frozen=True)
class ScoreBreakdown:
    htf: float
    structure: float
    momentum: float
    liquidity: float
    session: float
    contradiction_penalty: float
    final_score: float


def directional_contribution(
    signal_direction: str,
    trade_direction: str,
    strength: float,
    contradiction_penalty: float = CONTRADICTION_PENALTY_MULTIPLIER,
) -> float:
    """Calculate the contribution of a signal based on its alignment with the trade."""
    strength = max(0.0, min(1.0, float(strength)))

    if signal_direction == trade_direction:
        return strength

    if signal_direction == "neutral":
        return 0.0

    # Signal contradicts the trade direction
    return -strength * contradiction_penalty


# ---------------------------------------------------------------------------
# Score aggregation
# ---------------------------------------------------------------------------
def aggregate_score(signals: list[StrategySignal]) -> float:
    """Return the mean ``raw_score`` of ``signals`` in ``[0, 1]``.

    Used by the orchestrator to produce the ``score`` field on
    :class:`DecisionResult` -- a single number summarising the conviction of
    all contributing component signals.

    Args:
        signals: Component signals from the engine modules. May be empty.

    Returns:
        Mean of ``raw_score`` clamped to ``[0, 1]``. Returns ``0.0`` when
        ``signals`` is empty (conservative -- no signals means no conviction).
    """
    if not signals:
        return 0.0
    scores = [max(0.0, min(1.0, float(s.raw_score))) for s in signals]
    return sum(scores) / len(scores)


# ---------------------------------------------------------------------------
# Confidence calculation
# ---------------------------------------------------------------------------
def _safe_read(obj: Any, key: str, default: Any = None) -> Any:
    """Safely read an attribute or dict key from ``obj``.

    Works with both Pydantic models (attribute access) and plain dicts
    (key lookup), returning ``default`` when the key/attribute is absent.
    """
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_signal_direction(
    signals: list[StrategySignal],
    strategy_name: str,
    timeframe: str,
) -> str:
    """Find the direction of a specific strategy signal on a given timeframe.

    Returns ``'neutral'`` when no matching signal is found.
    """
    for s in signals:
        if s.strategy_name == strategy_name and s.timeframe == timeframe:
            return s.direction
    return "neutral"


def _volume_direction(volume_dict: dict) -> str:
    """Derive a volume/bias direction from the volume analysis dict.

    Uses ``cvd_slope`` and ``delta``: rising/buying → ``'long'``,
    falling/selling → ``'short'``, otherwise ``'neutral'``.
    """
    cvd_slope = float(_safe_read(volume_dict, "cvd_slope", 0.0) or 0.0)
    delta = float(_safe_read(volume_dict, "delta", 0.0) or 0.0)
    if cvd_slope > 0 or delta > 0:
        return "long"
    if cvd_slope < 0 or delta < 0:
        return "short"
    return "neutral"


# Keep backwards-compatible alias
_norm = lambda x: max(0.0, min(1.0, float(x) if x is not None else 0.0))


def calculate_confidence(
    signals: list[StrategySignal],
    htf_result: HTFFilterResult,
    regime: RegimeState,
    trend_strength: float,
    momentum_score: float,
    volume_confirmation: float,
    session_score: float,
    symbol: Optional[str] = None,
    trade_direction: str = "long",
) -> float:
    """Aggregate all component scores into a final confidence (Setup Score).

    Algorithm (v3 -- true directional scoring):
      1. Extract each component's *direction* from the signals list.
      2. Compute *signed* directional contributions via
         :func:`directional_contribution`.
      3. Weighted sum (contributions can be negative).
      4. Apply regime modifier.
      5. Clamp to [0, 1].
    """
    # Normalise all components to [0, 1] for the weighted sum.
    def _norm(x: float) -> float:
        if x is None:
            return 0.0
        try:
            v = float(x)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, v))

    # --- Extract directions for each component ---
    ltf_tf = htf_result.ltf_timeframe if hasattr(htf_result, "ltf_timeframe") else ""
    htf_dir = normalize_direction(
        _safe_read(htf_result, "bias", "neutral") if hasattr(htf_result, "bias") else "neutral"
    )
    struct_dir = _extract_signal_direction(signals, "structure", ltf_tf)
    mom_dir = _extract_signal_direction(signals, "momentum", ltf_tf)
    # Volume direction must be derived from the volume dict in the orchestrator;
    # we use the signals list as fallback.
    vol_dir = _extract_signal_direction(signals, "volume", ltf_tf)

    # --- Signed directional contributions ---
    # HTF: alignment is binary (1.0 or 0.0); penalize if bias contradicts trade
    htf_dir_normalized = htf_dir  # already 'long'/'short'/'neutral'
    htf_contrib = 1.0 if htf_result.alignment else 0.0
    # But also apply directional penalty if HTF bias contradicts
    if htf_dir_normalized != "neutral" and htf_dir_normalized != trade_direction:
        htf_contrib = -1.0 * CONTRADICTION_PENALTY_MULTIPLIER

    struct_score = directional_contribution(
        signal_direction=struct_dir,
        trade_direction=trade_direction,
        strength=trend_strength,
    )

    mom_score = directional_contribution(
        signal_direction=mom_dir,
        trade_direction=trade_direction,
        strength=momentum_score,
    )

    liq_score = directional_contribution(
        signal_direction=vol_dir,
        trade_direction=trade_direction,
        strength=volume_confirmation,
    )

    # Session is always neutral/positive (time-of-day signal)
    sess_score = _norm(session_score)

    # --- Count aligned components (must have >= 3 of 5 aligned) ---
    _components = [
        htf_contrib,
        struct_score,
        mom_score,
        liq_score,
        sess_score,
    ]
    _aligned_count = sum(1 for c in _components if c > 0.0)

    # --- Weighted sum (contributions can be negative) ---
    raw_score = (
        htf_contrib * HTF_ALIGNMENT_WEIGHT
        + struct_score * STRUCTURE_WEIGHT
        + mom_score * MOMENTUM_WEIGHT
        + liq_score * LIQUIDITY_WEIGHT
        + sess_score * SESSION_WEIGHT
    )

    # --- Hard gate: if fewer than 3 components agree, score drops to 0 ---
    if _aligned_count < 3:
        raw_score = 0.0
        logger.info(
            "setup_score_rejected_insufficient_alignment",
            timestamp=datetime.utcnow(),
            symbol=symbol or "",
            aligned_count=_aligned_count,
            required=3,
        )

    # --- Apply regime modifier ---
    modifier = _regime_modifier(regime)
    final_score = raw_score * modifier
    final_score = max(0.0, min(1.0, float(final_score)))

    log_symbol = symbol
    if log_symbol is None:
        log_symbol = signals[0].symbol if signals else ""

    logger.info(
        "setup_score_calculated",
        timestamp=datetime.utcnow(),
        symbol=log_symbol,
        setup_score=round(final_score, 6),
        raw_score=round(raw_score, 6),
        htf_contrib=round(htf_contrib, 6),
        struct_contrib=round(struct_score, 6),
        mom_contrib=round(mom_score, 6),
        liq_contrib=round(liq_score, 6),
        regime_modifier=modifier,
        regime=regime.value if isinstance(regime, RegimeState) else str(regime),
        trade_direction=trade_direction,
    )

    return final_score


# ---------------------------------------------------------------------------
# Confidence gate
# ---------------------------------------------------------------------------
def confidence_gate(confidence: float) -> bool:
    """Return True iff ``confidence`` is at or above ``CONFIDENCE_THRESHOLD``.

    This is the gate the orchestrator uses to decide whether to proceed to
    risk assessment. Per Section 10 criterion 2, a confidence below the
    threshold MUST result in ``final_verdict = False``.
    """
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return False
    return c >= CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Bonus: explain a confidence value for debugging / bot-facing messages
# ---------------------------------------------------------------------------
def explain_confidence(
    htf_result: HTFFilterResult,
    regime: RegimeState,
    trend_strength: float,
    momentum_score: float,
    volume_confirmation: float,
    session_score: float,
    confidence: float,
) -> list[str]:
    """Return a list of human-readable reasons explaining ``confidence``.

    Used by the orchestrator to populate ``DecisionResult.component_signals``
    or to surface in bot messages. Each item is a single line of explanation
    covering one component's contribution.
    """
    htf_component = 1.0 if htf_result.alignment else 0.0
    modifier = _regime_modifier(regime)
    lines = [
        f"final_confidence={confidence:.4f}",
        f"htf_alignment={htf_component:.2f} * weight={HTF_ALIGNMENT_WEIGHT:.2f} "
        f"= {htf_component * HTF_ALIGNMENT_WEIGHT:.4f}",
        f"trend_strength={trend_strength:.2f} * weight={STRUCTURE_WEIGHT:.2f} "
        f"= {trend_strength * STRUCTURE_WEIGHT:.4f}",
        f"momentum_score={momentum_score:.2f} * weight={MOMENTUM_WEIGHT:.2f} "
        f"= {momentum_score * MOMENTUM_WEIGHT:.4f}",
        f"volume_confirmation={volume_confirmation:.2f} * weight={LIQUIDITY_WEIGHT:.2f} "
        f"= {volume_confirmation * LIQUIDITY_WEIGHT:.4f}",
        f"session_score={session_score:.2f} * weight={SESSION_WEIGHT:.2f} "
        f"= {session_score * SESSION_WEIGHT:.4f}",
        f"regime={regime.value if isinstance(regime, RegimeState) else str(regime)} "
        f"modifier={modifier:.2f}",
        f"threshold={CONFIDENCE_THRESHOLD:.2f} -> "
        f"{'PASS' if confidence_gate(confidence) else 'FAIL'}",
    ]
    return lines


__all__ = [
    "calculate_confidence",
    "confidence_gate",
    "aggregate_score",
    "directional_contribution",
    "explain_confidence",
]
