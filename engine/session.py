
"""
File: engine/session.py
1. Single Responsibility: Wrap market/session.py with engine-level filtering
   and signal construction -- classify the active trading session, score its
   quality for the given symbol, and decide whether a candidate signal is
   allowed to fire in this session.
2. Consumes: ``Candle``, ``StrategySignal`` (contracts/market.py,
   contracts/decision.py); ``market/session.py``; config/thresholds;
   monitoring.logger.
3. Produces: ``classify_session``, ``session_quality_score``,
   ``filter_by_session``, ``build_session_signal`` consumed by
   engine/confidence.py and engine/orchestrator.py.
4. Downstream: engine/confidence.py (SESSION_WEIGHT component),
   engine/orchestrator.py (session gating).
5. New Dependencies: No new external deps. Imports ``market.session`` which
   is one layer upstream of engine -- this is allowed because engine sits
   above market in the §1 dependency order (config -> contracts -> storage
   -> ingest/data -> market -> engine -> simulation -> ...).
6. Touches Section 6 bugs? No.
7. Tests: indirectly covered by Section 10 market/session.py tests (which
   exercise the underlying classifier). The wrappers here add only filtering
   and signal construction.
8. Logging: ``session_classified`` {timestamp, symbol, session,
   quality_score} -- already emitted by market/session.py; this module
   additionally emits ``session_filter_result`` and ``session_signal_built``
   for traceability.
9. Dependency Order: config -> contracts -> monitoring -> market/session.py
   -> engine/session.py (no upstream violations).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from contracts.decision import StrategySignal
from contracts.market import Candle
from market.session import (
    SessionName,
    classify_and_log,
    get_current_session,
    session_quality_score as _market_session_quality_score,
)
from config.thresholds import LONDON_START_UTC, NY_START_UTC
from monitoring.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal scoring constants
# ---------------------------------------------------------------------------
# Minimum session-quality score below which a signal is filtered out. This is
# a scoring coefficient (not a trading threshold) -- it determines how strict
# the session gate is. The Asian session for majors scores ~0.45 and would be
# filtered out under this default; alt-coins in Asian score 0.55 and pass.
# Tunable but kept private to avoid cluttering config/thresholds.py with
# non-threshold knobs.
_MIN_SESSION_QUALITY = 0.40

# Score at or above which we label a session "favourable" -- purely cosmetic,
# used in reason strings.
_FAVOURABLE_SESSION_SCORE = 0.70

# Blackout Zone: First 15 minutes of London and NY openings are high-risk due to 
# opening volatility and potential stop hunts.
_BLACKOUT_MINUTES = 15


# ---------------------------------------------------------------------------
# Thin wrappers around market/session.py
# ---------------------------------------------------------------------------
def classify_session(timestamp: datetime) -> SessionName:
    """Classify the trading session for ``timestamp`` (interpreted as UTC).
    Thin wrapper around :func:`market.session.get_current_session`.
    """
    return get_current_session(timestamp)


def session_quality_score(session: str, symbol: str) -> float:
    """Return a quality score in ``[0.0, 1.0]`` for ``session`` / ``symbol``.
    Thin wrapper around :func:`market.session.session_quality_score`.
    """
    if not session:
        return 0.0
    try:
        return _market_session_quality_score(session, symbol)  # type: ignore[arg-type]
    except (KeyError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Engine-level session filter
# ---------------------------------------------------------------------------
def filter_by_session(
    signal: StrategySignal,
    timestamp: datetime,
    symbol: str,
) -> tuple[bool, float, str]:
    """Decide whether ``signal`` is allowed to fire in the current session.
    Includes a Blackout Zone check for session openings.
    """
    if timestamp is None:
        return False, 0.0, "missing_timestamp"
    if not symbol:
        return False, 0.0, "missing_symbol"

    # Normalize to UTC for reliable opening-hour checks
    if timestamp.tzinfo is not None:
        ts_utc = timestamp.astimezone(tz=timezone.utc)
    else:
        ts_utc = timestamp.replace(tzinfo=timezone.utc)

    # Blackout Zone check: First 15 minutes of London or NY opening
    hour = ts_utc.hour
    minute = ts_utc.minute
    
    is_london_open = (hour == LONDON_START_UTC and minute < _BLACKOUT_MINUTES)
    is_ny_open = (hour == NY_START_UTC and minute < _BLACKOUT_MINUTES)
    
    if is_london_open or is_ny_open:
        reason = f"session_blackout_zone: {hour:02d}:{minute:02d} UTC (Opening Volatility)"
        logger.info(
            "session_filter_blackout", 
            symbol=symbol, 
            timestamp=ts_utc.isoformat(), 
            reason=reason
        )
        return False, 0.0, reason

    session = classify_session(ts_utc)
    score = session_quality_score(session, symbol)

    logger.info(
        "session_filter_result",
        timestamp=datetime.utcnow(),
        symbol=symbol,
        session=session,
        quality_score=round(score, 4),
        signal_direction=signal.direction,
        allowed=score >= _MIN_SESSION_QUALITY,
    )

    if score >= _MIN_SESSION_QUALITY:
        return True, score, ""

    return (
        False,
        score,
        f"low_quality_session:{session}:{score:.3f}",
    )


# ---------------------------------------------------------------------------
# Build a StrategySignal from a single candle
# ---------------------------------------------------------------------------
def build_session_signal(
    candle: Candle,
    symbol: str,
    volume_ratio: float = 1.0,
) -> StrategySignal:
    """Construct a ``StrategySignal`` representing the session-quality score.
    Includes a volume-based dynamic adjustment to the session score.
    """
    sym = symbol or candle.symbol
    timestamp = candle.open_time
    if timestamp is None:
        return StrategySignal(
            symbol=sym,
            timeframe=candle.timeframe,
            strategy_name="session",
            direction="long",
            raw_score=0.5,
            reasons=["missing_open_time"],
            timestamp=datetime.now(timezone.utc),
            source_candle_open_time=datetime.now(timezone.utc),
        )

    session = classify_session(timestamp)
    base_score = session_quality_score(session, sym)
    
    # Dynamic adjustment: Boost score if volume is above average (volume_ratio > 1.0)
    # A volume_ratio of 2.0 adds 0.2 to the score; 0.5 subtracts 0.1.
    volume_mod = (volume_ratio - 1.0) * 0.2
    raw_score = max(0.0, min(1.0, float(base_score + volume_mod)))

    direction: Literal["long", "neutral"]
    reasons: list[str] = [
        f"session={session}", 
        f"base_quality={base_score:.3f}",
        f"volume_ratio={volume_ratio:.2f}",
        f"final_score={raw_score:.3f}"
    ]

    if raw_score >= _FAVOURABLE_SESSION_SCORE:
        direction = "long"
        reasons.append("favourable_session: long bias")
    else:
        direction = "neutral"
        reasons.append("low_quality_session: neutral bias (gated by confidence)")

    logger.info(
        "session_signal_built",
        timestamp=datetime.utcnow(),
        symbol=sym,
        timeframe=candle.timeframe,
        session=session,
        quality_score=raw_score,
        direction=direction,
    )

    return StrategySignal(
        symbol=sym,
        timeframe=candle.timeframe,
        strategy_name="session",
        direction=direction,
        raw_score=raw_score,
        reasons=reasons,
        timestamp=datetime.now(timezone.utc),
        source_candle_open_time=candle.open_time,
    )


def classify_and_log_session(
    timestamp: datetime,
    symbol: str,
) -> tuple[SessionName, float]:
    """Classify the session, log via ``classify_and_log``, and return the
    (session, quality_score) pair.
    """
    session, score = classify_and_log(timestamp, symbol)
    return session, float(score)


__all__ = [
    "classify_session",
    "session_quality_score",
    "filter_by_session",
    "build_session_signal",
    "classify_and_log_session",
]
