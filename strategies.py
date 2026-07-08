from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from ta.momentum import RSIIndicator
    from ta.trend import ADXIndicator, EMAIndicator, MACD
    from ta.volatility import AverageTrueRange
except Exception:  # pragma: no cover - fallback for minimal runtimes
    class EMAIndicator:
        def __init__(self, close, window=14):
            self.close = pd.Series(close).astype(float)
            self.window = int(window)

        def ema_indicator(self):
            return self.close.ewm(span=self.window, adjust=False).mean()

    class RSIIndicator:
        def __init__(self, close, window=14):
            self.close = pd.Series(close).astype(float)
            self.window = int(window)

        def rsi(self):
            delta = self.close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(alpha=1 / self.window, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / self.window, adjust=False).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            return rsi.fillna(50.0)

    class MACD:
        def __init__(self, close, window_slow=26, window_fast=12, window_sign=9):
            self.close = pd.Series(close).astype(float)
            self.window_slow = int(window_slow)
            self.window_fast = int(window_fast)
            self.window_sign = int(window_sign)

        def macd_diff(self):
            fast = self.close.ewm(span=self.window_fast, adjust=False).mean()
            slow = self.close.ewm(span=self.window_slow, adjust=False).mean()
            macd = fast - slow
            signal = macd.ewm(span=self.window_sign, adjust=False).mean()
            return macd - signal

    class AverageTrueRange:
        def __init__(self, high, low, close, window=14):
            self.high = pd.Series(high).astype(float)
            self.low = pd.Series(low).astype(float)
            self.close = pd.Series(close).astype(float)
            self.window = int(window)

        def average_true_range(self):
            prev_close = self.close.shift(1)
            tr = pd.concat([
                (self.high - self.low).abs(),
                (self.high - prev_close).abs(),
                (self.low - prev_close).abs(),
            ], axis=1).max(axis=1)
            return tr.rolling(self.window, min_periods=1).mean()

    class ADXIndicator:
        def __init__(self, high, low, close, window=14):
            self.high = pd.Series(high).astype(float)
            self.low = pd.Series(low).astype(float)
            self.close = pd.Series(close).astype(float)
            self.window = int(window)

        def adx(self):
            up_move = self.high.diff()
            down_move = -self.low.diff()
            plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
            minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
            prev_close = self.close.shift(1)
            tr = pd.concat([
                (self.high - self.low).abs(),
                (self.high - prev_close).abs(),
                (self.low - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(self.window, min_periods=1).mean().replace(0, np.nan)
            plus_di = 100 * pd.Series(plus_dm).rolling(self.window, min_periods=1).mean() / atr
            minus_di = 100 * pd.Series(minus_dm).rolling(self.window, min_periods=1).mean() / atr
            dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
            return dx.rolling(self.window, min_periods=1).mean().fillna(0.0)

import config

logger = logging.getLogger("CT_System")


class _DecisionConfigProxy:
    """Compatibility layer that keeps the strategy engine working even when
    config.py does not expose a rich DECISION_CONFIG object.

    Missing values fall back to conservative defaults so the engine prefers
    skipping trades over entering weak setups.
    """

    DEFAULTS = {
        "score_max": 100.0,
        "score_min": 0.0,
        "neutral_score": 50.0,
        "epsilon": 1e-9,
        "adx_min_trend": 20.0,
        "min_candles_ltf": 120,
        "min_candles_htf": 120,
        "rr_min": 2.0,
        "required_data_quality": 100.0,
        "data_quality_required_for_entry": 100.0,
        "trend_confidence_min": 75.0,
        "confidence_floor": 0.0,
        "confidence_ceiling": 100.0,
        "probability_floor": 0.0,
        "probability_ceiling": 100.0,
        "htf_missing_policy": getattr(config, "HTF_MODE", "SKIP"),
        "htf_missing_confidence_penalty": 30.0,
        "htf_missing_probability_penalty": 35.0,
        "htf_conflict_confidence_penalty": 55.0,
        "htf_conflict_probability_penalty": 60.0,
        "equal_level_tolerance_atr": 0.15,
        "sweep_volume_multiplier": 1.25,
        "sweep_wick_ratio_min": 0.55,
        "min_break_distance_atr": 0.50,
        "min_close_beyond_atr": 0.20,
        "confirmation_closes": 2,
        "ob_lookback": 20,
        "fvg_min_gap_atr": 0.25,
        "atr_stop_multiplier": 1.5,
        "swing_stop_buffer_atr": 0.20,
        "volume_lookback": 20,
        "volume_session_boost": {
            "ASIA": 0.95,
            "LONDON": 1.10,
            "NEW_YORK": 1.15,
            "OVERLAP": 1.20,
            "OFF_HOURS": 0.85,
        },
        "volume_rel_threshold": 1.20,
        "volume_high_threshold": 1.50,
        "volume_percentile_threshold": 70.0,
        "volume_zscore_threshold": 1.0,
        "rsi_neutral": 50.0,
        "rsi_band": 10.0,
        "macd_scale_atr_mult": 0.50,
        "swing_left": 3,
        "swing_right": 2,
        "trend_persistence_lookback": 5,
        "ema_fast": 20,
        "ema_mid": 50,
        "ema_slow": 100,
        "ema_anchor": 200,
        "slope_lookback": 5,
        "ema_entanglement_ratio": 0.004,
        "confidence_weights": {
            "data_quality": 0.20,
            "trend_quality": 0.20,
            "momentum_quality": 0.15,
            "smc_quality": 0.20,
            "htf_quality": 0.10,
            "volume_quality": 0.10,
            "regime_stability": 0.05,
        },
        "probability_weights": {
            "trend_strength": 0.20,
            "regime": 0.15,
            "momentum": 0.15,
            "volume": 0.10,
            "htf": 0.10,
            "smc": 0.15,
            "risk": 0.10,
            "historical_performance": 0.05,
        },
        "momentum_weights": {
            "rsi": 0.35,
            "macd": 0.35,
            "trend": 0.30,
        },
        "asia_session": (0, 7),
        "london_session": (7, 13),
        "new_york_session": (13, 21),
        "overlap_session": (13, 16),
    }

    def __init__(self, base: Any = None):
        self._base = base

    def __getattr__(self, item: str):
        if self._base is not None and hasattr(self._base, item):
            return getattr(self._base, item)
        if item in self.DEFAULTS:
            return self.DEFAULTS[item]
        raise AttributeError(item)


@dataclass(frozen=True)
class SMCComponent:
    name: str
    confirmed: bool
    score: float
    weight: float
    details: Dict[str, Any]


class InstitutionalStrategies:
    """
    Conservative institutional decision engine.

    The design goal is not trade frequency. The design goal is to avoid low-quality
    entries by making every layer explicit, configurable, and explainable.
    """

    def __init__(self, decision_config: Optional[config.DecisionConfig] = None):
        base_cfg = decision_config if decision_config is not None else getattr(config, "DECISION_CONFIG", None)
        self.cfg = _DecisionConfigProxy(base_cfg)

        # Backwards-compatible dictionaries for older code paths.
        self.thresholds = {
            "adx": self.cfg.adx_min_trend,
            "volatility_min": 0.3,
            "ema_distance_pct": 7,
            "rsi_buy": (30, 65),
            "rsi_sell": (35, 70),
            "min_candles": self.cfg.min_candles_ltf,
            "rr_min": self.cfg.rr_min,
            "min_score": 80,
            "htf_mode": self.cfg.htf_missing_policy,
        }

        self.weights = {
            "trend": 20,
            "momentum": 15,
            "volume": 15,
            "volatility": 10,
            "smc": 25,
            "risk_context": 10,
            "htf": 5,
        }

        self.smc_weights = {
            "liquidity_sweep": 18,
            "bos": 18,
            "choch": 16,
            "fvg": 12,
            "order_block": 12,
            "breaker_block": 8,
            "mitigation_block": 8,
            "equal_highs_lows": 4,
            "inducement": 4,
            "premium_discount": 4,
            "volume_confirmation": 10,
        }

        self._last_regime = "Sideways/Neutral"

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return float(max(low, min(high, value)))

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or (isinstance(value, float) and np.isnan(value)):
                return default
            return float(value)
        except Exception:
            return default

    def _pct(self, value: float) -> float:
        return value * self.cfg.score_max

    def _normalize(self, value: float, low: float, high: float) -> float:
        if high <= low:
            return self.cfg.neutral_score
        return self._clamp((value - low) / (high - low), 0.0, 1.0) * self.cfg.score_max

    def _series_last(self, series: pd.Series, default: float = 0.0) -> float:
        if series is None or series.empty:
            return default
        return self._safe_float(series.iloc[-1], default)

    def _series_prev(self, series: pd.Series, offset: int = 2, default: float = 0.0) -> float:
        if series is None or len(series) < offset:
            return default
        return self._safe_float(series.iloc[-offset], default)

    def _timestamp_to_utc(self, value: Any) -> datetime:
        if isinstance(value, pd.Timestamp):
            ts = value
            if ts.tzinfo is None:
                return ts.to_pydatetime().replace(tzinfo=timezone.utc)
            return ts.to_pydatetime().astimezone(timezone.utc)
        try:
            return pd.to_datetime(value, unit="ms", utc=True).to_pydatetime()
        except Exception:
            try:
                return pd.to_datetime(value, utc=True).to_pydatetime()
            except Exception:
                return datetime.now(timezone.utc)

    def _clean_df(self, df: pd.DataFrame) -> pd.DataFrame:
        required = {"open", "high", "low", "close", "volume"}
        if df is None or df.empty:
            raise ValueError("Empty dataframe")

        frame = df.copy()
        if "timestamp" in frame.columns:
            frame = frame.sort_values("timestamp")
            frame = frame.drop_duplicates(subset=["timestamp"], keep="last")
        else:
            frame = frame.sort_index()
            frame = frame[~frame.index.duplicated(keep="last")]

        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        for col in ["open", "high", "low", "close", "volume"]:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

        if "timestamp" in frame.columns:
            frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce")

        frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
        frame = frame.reset_index(drop=True)
        return frame

    def _data_quality_report(self, df: pd.DataFrame) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        score = self.cfg.score_max

        if df is None or df.empty:
            return {
                "score": 0.0,
                "required": self.cfg.required_data_quality,
                "issues": [{"name": "empty_data", "current": 0, "required": 1, "impact": 100.0, "suggested_fix": "Load fresh OHLCV data."}],
                "valid": False,
            }

        frame = df.copy()
        columns = ["open", "high", "low", "close", "volume"]
        total_cells = len(frame) * len(columns)
        nan_count = int(frame[columns].isna().sum().sum()) if set(columns).issubset(frame.columns) else total_cells
        duplicate_ts = int(frame["timestamp"].duplicated().sum()) if "timestamp" in frame.columns else 0
        zero_or_negative = int(((frame[columns] <= 0).sum().sum())) if set(columns).issubset(frame.columns) else total_cells
        min_rows = self.cfg.min_candles_ltf

        if len(frame) < min_rows:
            penalty = self._clamp((min_rows - len(frame)) / max(min_rows, 1) * 35.0, 0.0, 35.0)
            score -= penalty
            issues.append({
                "name": "insufficient_ltf_candles",
                "current": len(frame),
                "required": min_rows,
                "impact": round(penalty, 2),
                "suggested_fix": f"Fetch at least {min_rows} candles before analysis.",
            })

        if nan_count > 0:
            penalty = self._clamp((nan_count / max(total_cells, 1)) * 50.0, 5.0, 50.0)
            score -= penalty
            issues.append({
                "name": "nan_values",
                "current": nan_count,
                "required": 0,
                "impact": round(penalty, 2),
                "suggested_fix": "Clean NaN values and refetch corrupted candles.",
            })

        if duplicate_ts > 0:
            penalty = self._clamp(duplicate_ts * 4.0, 4.0, 20.0)
            score -= penalty
            issues.append({
                "name": "duplicate_candles",
                "current": duplicate_ts,
                "required": 0,
                "impact": round(penalty, 2),
                "suggested_fix": "Deduplicate candles by timestamp before analysis.",
            })

        if zero_or_negative > 0:
            penalty = self._clamp(zero_or_negative * 2.0, 4.0, 40.0)
            score -= penalty
            issues.append({
                "name": "invalid_price_volume_values",
                "current": zero_or_negative,
                "required": 0,
                "impact": round(penalty, 2),
                "suggested_fix": "Reject candles with non-positive prices or volume.",
            })

        if "timestamp" in frame.columns and frame["timestamp"].isna().any():
            penalty = 10.0
            score -= penalty
            issues.append({
                "name": "invalid_timestamp",
                "current": int(frame["timestamp"].isna().sum()),
                "required": 0,
                "impact": penalty,
                "suggested_fix": "Normalize timestamps and keep millisecond precision.",
            })

        valid = score >= self.cfg.required_data_quality and not issues
        score = self._clamp(score, self.cfg.score_min, self.cfg.score_max)
        return {
            "score": round(score, 2),
            "required": self.cfg.required_data_quality,
            "issues": issues,
            "valid": valid,
        }

    def _session_from_timestamp(self, ts: Optional[Any]) -> str:
        if ts is None:
            dt = datetime.now(timezone.utc)
        else:
            dt = self._timestamp_to_utc(ts)

        hour = dt.hour
        asia_start, asia_end = self.cfg.asia_session
        london_start, london_end = self.cfg.london_session
        ny_start, ny_end = self.cfg.new_york_session
        overlap_start, overlap_end = self.cfg.overlap_session

        if overlap_start <= hour < overlap_end:
            return "OVERLAP"
        if asia_start <= hour < asia_end:
            return "ASIA"
        if london_start <= hour < london_end:
            return "LONDON"
        if ny_start <= hour < ny_end:
            return "NEW_YORK"
        return "OFF_HOURS"

    def _percentile_rank(self, values: pd.Series, current: float) -> float:
        if values is None or values.empty:
            return 0.0
        vals = pd.to_numeric(values, errors="coerce").dropna().astype(float)
        if vals.empty:
            return 0.0
        rank = float((vals <= current).sum()) / float(len(vals))
        return self._clamp(rank * self.cfg.score_max, self.cfg.score_min, self.cfg.score_max)

    def _slope(self, series: pd.Series, lookback: int) -> float:
        if series is None or len(series) <= lookback:
            return 0.0
        start = self._safe_float(series.iloc[-lookback - 1])
        end = self._safe_float(series.iloc[-1])
        return (end - start) / max(lookback, 1)

    def _pivot_points(self, df: pd.DataFrame, left: Optional[int] = None, right: Optional[int] = None) -> Dict[str, List[Tuple[int, float]]]:
        left = left or self.cfg.swing_left
        right = right or self.cfg.swing_right
        highs: List[Tuple[int, float]] = []
        lows: List[Tuple[int, float]] = []

        if len(df) < left + right + 1:
            return {"highs": highs, "lows": lows}

        for i in range(left, len(df) - right):
            high_window = df["high"].iloc[i - left : i + right + 1]
            low_window = df["low"].iloc[i - left : i + right + 1]
            high = self._safe_float(df["high"].iloc[i])
            low = self._safe_float(df["low"].iloc[i])

            if high == float(high_window.max()) and (high_window == high).sum() == 1:
                highs.append((i, high))
            if low == float(low_window.min()) and (low_window == low).sum() == 1:
                lows.append((i, low))

        return {"highs": highs, "lows": lows}

    def _structure_from_swings(self, swings: Dict[str, List[Tuple[int, float]]]) -> Dict[str, Any]:
        highs = swings["highs"]
        lows = swings["lows"]
        hh = len(highs) >= 2 and highs[-1][1] > highs[-2][1]
        lh = len(highs) >= 2 and highs[-1][1] < highs[-2][1]
        hl = len(lows) >= 2 and lows[-1][1] > lows[-2][1]
        ll = len(lows) >= 2 and lows[-1][1] < lows[-2][1]
        return {
            "higher_highs": hh,
            "higher_lows": hl,
            "lower_highs": lh,
            "lower_lows": ll,
            "last_swing_high": highs[-1][1] if highs else None,
            "last_swing_low": lows[-1][1] if lows else None,
            "previous_swing_high": highs[-2][1] if len(highs) >= 2 else None,
            "previous_swing_low": lows[-2][1] if len(lows) >= 2 else None,
        }

    def _trend_persistence(self, df: pd.DataFrame, ema_mid: pd.Series, ema_anchor: pd.Series, side: str) -> float:
        lookback = min(self.cfg.trend_persistence_lookback, len(df))
        if lookback <= 0:
            return 0.0

        closes = df["close"].iloc[-lookback:]
        mid = ema_mid.iloc[-lookback:]
        anchor = ema_anchor.iloc[-lookback:]

        if side == "BULLISH":
            above = ((closes > mid) & (closes > anchor)).sum()
            return self._clamp(above / lookback, 0.0, 1.0)
        if side == "BEARISH":
            below = ((closes < mid) & (closes < anchor)).sum()
            return self._clamp(below / lookback, 0.0, 1.0)
        return 0.0

    # ------------------------------------------------------------------
    # Market regime engine
    # ------------------------------------------------------------------
    def classify_market(self, df: pd.DataFrame) -> dict:
        try:
            frame = self._clean_df(df)
        except Exception as exc:
            return {
                "state": "Invalid Data",
                "bias": "NEUTRAL",
                "confidence": 0.0,
                "trend_strength": 0.0,
                "reason": str(exc),
                "values": {},
                "metrics": {"valid": False},
            }

        if len(frame) < self.cfg.min_candles_ltf:
            return {
                "state": "Low Data",
                "bias": "NEUTRAL",
                "confidence": 0.0,
                "trend_strength": 0.0,
                "reason": f"Insufficient data ({len(frame)} < {self.cfg.min_candles_ltf})",
                "values": {"candles": len(frame)},
                "metrics": {"valid": False},
            }

        close = frame["close"]
        high = frame["high"]
        low = frame["low"]

        ema_fast = EMAIndicator(close, window=self.cfg.ema_fast).ema_indicator()
        ema_mid = EMAIndicator(close, window=self.cfg.ema_mid).ema_indicator()
        ema_slow = EMAIndicator(close, window=self.cfg.ema_slow).ema_indicator()
        ema_anchor = EMAIndicator(close, window=self.cfg.ema_anchor).ema_indicator()

        e_fast = self._safe_float(ema_fast.iloc[-1])
        e_mid = self._safe_float(ema_mid.iloc[-1])
        e_slow = self._safe_float(ema_slow.iloc[-1])
        e_anchor = self._safe_float(ema_anchor.iloc[-1])

        adx = self._safe_float(ADXIndicator(high, low, close).adx().iloc[-1])
        atr = self._safe_float(AverageTrueRange(high, low, close).average_true_range().iloc[-1])
        atr_pct = (atr / max(self._safe_float(close.iloc[-1]), self.cfg.epsilon)) * self.cfg.score_max

        slope_fast = self._slope(ema_fast, self.cfg.slope_lookback)
        slope_mid = self._slope(ema_mid, self.cfg.slope_lookback)
        slope_anchor = self._slope(ema_anchor, self.cfg.slope_lookback)

        ema_values = [e_fast, e_mid, e_slow, e_anchor]
        ema_spread_ratio = (max(ema_values) - min(ema_values)) / max(abs(e_anchor), self.cfg.epsilon)
        ema_compression = self._clamp(1.0 - (ema_spread_ratio / max(self.cfg.ema_entanglement_ratio, self.cfg.epsilon)), 0.0, 1.0)

        bullish_alignment = e_fast > e_mid > e_slow > e_anchor
        bearish_alignment = e_fast < e_mid < e_slow < e_anchor

        swings = self._pivot_points(frame)
        structure = self._structure_from_swings(swings)
        hhs = structure["higher_highs"]
        hls = structure["higher_lows"]
        lhs = structure["lower_highs"]
        lls = structure["lower_lows"]

        bullish_structure = hhs and hls
        bearish_structure = lhs and lls

        close_last = self._safe_float(close.iloc[-1])
        close_prev = self._safe_float(close.iloc[-2]) if len(close) >= 2 else close_last

        if bullish_alignment or bullish_structure:
            bias = "BULLISH"
        elif bearish_alignment or bearish_structure:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        persistence = self._trend_persistence(frame, ema_mid, ema_anchor, bias)
        adx_strength = self._normalize(adx, 0.0, max(self.cfg.adx_min_trend * 2.0, self.cfg.epsilon))
        slope_score = self._normalize(abs(slope_mid) + abs(slope_anchor), 0.0, max(abs(close_last) * 0.002, self.cfg.epsilon))
        compression_score = self._pct(ema_compression)
        persistence_score = persistence * self.cfg.score_max

        if bias == "BULLISH":
            alignment_score = self.cfg.score_max if bullish_alignment else self._pct(0.60 if bullish_structure else 0.35)
            structure_score = self._pct(0.85 if bullish_structure else 0.55 if bullish_alignment else 0.20)
        elif bias == "BEARISH":
            alignment_score = self.cfg.score_max if bearish_alignment else self._pct(0.60 if bearish_structure else 0.35)
            structure_score = self._pct(0.85 if bearish_structure else 0.55 if bearish_alignment else 0.20)
        else:
            alignment_score = self._pct(0.15)
            structure_score = self._pct(0.15)

        trend_strength = (
            alignment_score * 0.26
            + adx_strength * 0.18
            + slope_score * 0.16
            + persistence_score * 0.18
            + structure_score * 0.16
            + compression_score * 0.06
        )
        trend_strength = self._clamp(trend_strength, self.cfg.score_min, self.cfg.score_max)

        if compression_score < self._pct(0.20) or adx < self.cfg.adx_min_trend * 0.75:
            state = "Choppy/Sideways"
            bias = "NEUTRAL" if not (bullish_alignment or bearish_alignment) else bias
            reason = "Compression is high and directional persistence is weak."
        elif bias == "BULLISH":
            if trend_strength >= 80:
                state = "Strong Uptrend"
                reason = "EMA alignment, persistence, and structure are strongly bullish."
            elif trend_strength >= 65:
                state = "Uptrend"
                reason = "Bullish structure is present but not fully explosive."
            else:
                state = "Weak Uptrend"
                reason = "Bullish bias exists, but confirmation is not strong enough."
        elif bias == "BEARISH":
            if trend_strength >= 80:
                state = "Strong Downtrend"
                reason = "EMA alignment, persistence, and structure are strongly bearish."
            elif trend_strength >= 65:
                state = "Downtrend"
                reason = "Bearish structure is present but not fully explosive."
            else:
                state = "Weak Downtrend"
                reason = "Bearish bias exists, but confirmation is not strong enough."
        else:
            state = "Transition/Range"
            reason = "Direction is not clean enough to classify as a tradeable trend."

        if "Trend" in self._last_regime and "Trend" not in state:
            if adx >= self.cfg.adx_min_trend and ((self._last_regime == "Strong Uptrend" and close_last > e_mid) or (self._last_regime == "Strong Downtrend" and close_last < e_mid)):
                state = self._last_regime
                reason = f"Hysteresis retained {state} to avoid regime flapping."

        self._last_regime = state

        confidence = (
            trend_strength * 0.55
            + adx_strength * 0.18
            + persistence_score * 0.14
            + compression_score * 0.13
        )
        confidence = self._clamp(confidence, self.cfg.confidence_floor, self.cfg.confidence_ceiling)

        return {
            "state": state,
            "bias": bias,
            "confidence": round(confidence, 2),
            "trend_strength": round(trend_strength, 2),
            "reason": reason,
            "values": {
                "EMA20": round(e_fast, 6),
                "EMA50": round(e_mid, 6),
                "EMA100": round(e_slow, 6),
                "EMA200": round(e_anchor, 6),
                "ADX": round(adx, 2),
                "ATR%": round(atr_pct, 4),
                "EMA_Spread_Ratio": round(ema_spread_ratio, 6),
                "EMA_Compression": round(compression_score, 2),
                "Slope20": round(slope_fast, 8),
                "Slope50": round(slope_mid, 8),
                "Slope200": round(slope_anchor, 8),
                "Trend_Persistence": round(persistence_score, 2),
                "Structure": structure,
            },
            "metrics": {
                "bullish_alignment": bullish_alignment,
                "bearish_alignment": bearish_alignment,
                "bullish_structure": bullish_structure,
                "bearish_structure": bearish_structure,
                "ema_compression": round(compression_score, 2),
                "trend_strength": round(trend_strength, 2),
                "valid": True,
            },
        }

    # ------------------------------------------------------------------
    # Volume / momentum / indicator engine
    # ------------------------------------------------------------------
    def _volume_context(self, frame: pd.DataFrame, atr_pct: float) -> Dict[str, Any]:
        volume = frame["volume"]
        current = self._safe_float(volume.iloc[-1])
        window = volume.iloc[-min(self.cfg.volume_lookback, len(volume)) :]
        mean = self._safe_float(window.mean())
        std = self._safe_float(window.std())
        rel = current / max(mean, self.cfg.epsilon)
        z = (current - mean) / max(std, self.cfg.epsilon) if std > self.cfg.epsilon else 0.0
        percentile = self._percentile_rank(window, current)

        ts = frame["timestamp"].iloc[-1] if "timestamp" in frame.columns else None
        session = self._session_from_timestamp(ts)
        session_boost = self.cfg.volume_session_boost.get(session, 1.0)
        dynamic_threshold = self.cfg.volume_rel_threshold * session_boost
        high_threshold = self.cfg.volume_high_threshold * session_boost
        status = rel >= dynamic_threshold and percentile >= self.cfg.volume_percentile_threshold and z >= self.cfg.volume_zscore_threshold

        if atr_pct > 1.5 * self.thresholds["volatility_min"]:
            # Dynamic adjustment during higher volatility.
            dynamic_threshold *= 1.05
            high_threshold *= 1.05

        return {
            "current": round(rel, 2),
            "relative": round(rel, 4),
            "z_score": round(z, 2),
            "percentile": round(percentile, 2),
            "threshold": round(dynamic_threshold, 2),
            "high_threshold": round(high_threshold, 2),
            "status": bool(status),
            "session": session,
            "session_boost": round(session_boost, 2),
            "mean": round(mean, 4),
            "std": round(std, 4),
        }

    def _momentum_side_score(self, rsi: float, macd_value: float, trend_bias: str, side: str, atr: float, close_price: float) -> float:
        rsi_direction = (rsi - self.cfg.rsi_neutral) / max(self.cfg.rsi_band, self.cfg.epsilon)
        if side == "SELL":
            rsi_direction *= -1.0

        macd_scale = max(abs(atr) * self.cfg.macd_scale_atr_mult, abs(close_price) * self.cfg.epsilon, self.cfg.epsilon)
        macd_direction = np.tanh(macd_value / macd_scale)
        if side == "SELL":
            macd_direction *= -1.0

        if trend_bias == "BULLISH" and self._last_regime == "Strong Uptrend":
            trend_direction = 1.0 if side == "BUY" else -1.0
        elif trend_bias == "BEARISH" and self._last_regime == "Strong Downtrend":
            trend_direction = 1.0 if side == "SELL" else -1.0
        else:
            trend_direction = 0.0

        raw = (
            self.cfg.momentum_weights["rsi"] * self._clamp(rsi_direction, -1.0, 1.0)
            + self.cfg.momentum_weights["macd"] * self._clamp(macd_direction, -1.0, 1.0)
            + self.cfg.momentum_weights["trend"] * self._clamp(trend_direction, -1.0, 1.0)
        )
        score = self.cfg.neutral_score + (raw * self.cfg.neutral_score)
        return self._clamp(score, self.cfg.score_min, self.cfg.score_max)

    def get_indicators_data(self, df: pd.DataFrame) -> dict:
        frame = self._clean_df(df)
        close = frame["close"]
        high = frame["high"]
        low = frame["low"]
        volume = frame["volume"]

        rsi = self._safe_float(RSIIndicator(close).rsi().iloc[-1])
        macd = self._safe_float(MACD(close).macd_diff().iloc[-1])
        atr = self._safe_float(AverageTrueRange(high, low, close).average_true_range().iloc[-1])
        close_last = self._safe_float(close.iloc[-1])
        atr_pct = (atr / max(close_last, self.cfg.epsilon)) * self.cfg.score_max

        vol_context = self._volume_context(frame, atr_pct)
        session = vol_context["session"]

        bull_momentum = self._momentum_side_score(rsi, macd, "BULLISH", "BUY", atr, close_last)
        bear_momentum = self._momentum_side_score(rsi, macd, "BEARISH", "SELL", atr, close_last)
        momentum_score = max(bull_momentum, bear_momentum)
        momentum_direction = "BUY" if bull_momentum > bear_momentum else "SELL" if bear_momentum > bull_momentum else "NEUTRAL"

        rsi_buy = self.thresholds["rsi_buy"][0] <= rsi <= self.thresholds["rsi_buy"][1]
        rsi_sell = self.thresholds["rsi_sell"][0] <= rsi <= self.thresholds["rsi_sell"][1]
        macd_buy = macd >= -self.cfg.epsilon
        macd_sell = macd <= self.cfg.epsilon

        return {
            "RSI": {
                "current": round(rsi, 2),
                "status_buy": bool(rsi_buy),
                "status_sell": bool(rsi_sell),
                "neutral_band": self.cfg.rsi_band,
            },
            "MACD": {
                "current": round(macd, 6),
                "status_buy": bool(macd_buy),
                "status_sell": bool(macd_sell),
                "scale": round(max(abs(atr) * self.cfg.macd_scale_atr_mult, abs(close_last) * self.cfg.epsilon, self.cfg.epsilon), 8),
            },
            "Momentum": {
                "current": round(momentum_score, 2),
                "direction": momentum_direction,
                "bullish_score": round(bull_momentum, 2),
                "bearish_score": round(bear_momentum, 2),
                "continuous": True,
            },
            "Volume": {
                **vol_context,
                "session": session,
            },
            "ATR%": {
                "current": round(atr_pct, 4),
                "status": atr_pct > self.thresholds["volatility_min"],
            },
        }

    # ------------------------------------------------------------------
    # HTF engine
    # ------------------------------------------------------------------
    def _htf_filter(self, df_higher: Optional[pd.DataFrame], candidate_side: str, ltf_regime: Dict[str, Any]) -> Dict[str, Any]:
        policy = (self.cfg.htf_missing_policy or "SKIP").upper()

        if df_higher is None:
            return {
                "supported": False,
                "status": policy if policy in {"UNKNOWN", "IGNORE_WITH_PENALTY", "SKIP"} else "SKIP",
                "decision_state": "MISSING",
                "aligned": False,
                "bias": "NEUTRAL",
                "confidence_penalty": self.cfg.htf_missing_confidence_penalty,
                "probability_penalty": self.cfg.htf_missing_probability_penalty,
                "reason": "HTF data missing.",
                "required_candles": self.cfg.min_candles_htf,
                "available_candles": 0,
                "valid": False,
            }

        try:
            htf_frame = self._clean_df(df_higher)
        except Exception as exc:
            return {
                "supported": False,
                "status": "SKIP",
                "decision_state": "INVALID",
                "aligned": False,
                "bias": "NEUTRAL",
                "confidence_penalty": self.cfg.htf_missing_confidence_penalty,
                "probability_penalty": self.cfg.htf_missing_probability_penalty,
                "reason": f"HTF invalid: {exc}",
                "required_candles": self.cfg.min_candles_htf,
                "available_candles": 0,
                "valid": False,
            }

        if len(htf_frame) < self.cfg.min_candles_htf:
            status = policy if policy in {"UNKNOWN", "IGNORE_WITH_PENALTY", "SKIP"} else "SKIP"
            return {
                "supported": False,
                "status": status,
                "decision_state": "INSUFFICIENT",
                "aligned": False,
                "bias": "NEUTRAL",
                "confidence_penalty": self.cfg.htf_missing_confidence_penalty,
                "probability_penalty": self.cfg.htf_missing_probability_penalty,
                "reason": f"HTF candles below requirement ({len(htf_frame)} < {self.cfg.min_candles_htf}).",
                "required_candles": self.cfg.min_candles_htf,
                "available_candles": len(htf_frame),
                "valid": False,
            }

        htf_regime = self.classify_market(htf_frame)
        bias = htf_regime["bias"]
        aligned = (
            candidate_side == "BUY" and bias == "BULLISH"
        ) or (
            candidate_side == "SELL" and bias == "BEARISH"
        )

        if aligned:
            return {
                "supported": True,
                "status": "PASS",
                "decision_state": "ALIGNED",
                "aligned": True,
                "bias": bias,
                "confidence_penalty": 0.0,
                "probability_penalty": 0.0,
                "reason": htf_regime["reason"],
                "state": htf_regime["state"],
                "confidence": htf_regime["confidence"],
                "required_candles": self.cfg.min_candles_htf,
                "available_candles": len(htf_frame),
                "valid": True,
            }

        return {
            "supported": False,
            "status": "SKIP",
            "decision_state": "CONFLICT",
            "aligned": False,
            "bias": bias,
            "confidence_penalty": self.cfg.htf_conflict_confidence_penalty,
            "probability_penalty": self.cfg.htf_conflict_probability_penalty,
            "reason": f"HTF conflict: HTF bias {bias} opposes candidate side {candidate_side}.",
            "state": htf_regime["state"],
            "confidence": htf_regime["confidence"],
            "required_candles": self.cfg.min_candles_htf,
            "available_candles": len(htf_frame),
            "valid": True,
        }

    # ------------------------------------------------------------------
    # Smart money engine
    # ------------------------------------------------------------------
    def _liquidity_sweep_side(self, frame: pd.DataFrame, side: str, atr: float, vol: Dict[str, Any], swings: Dict[str, List[Tuple[int, float]]]) -> Dict[str, Any]:
        highs = swings["highs"]
        lows = swings["lows"]
        last = frame.iloc[-1]
        body = abs(self._safe_float(last["close"]) - self._safe_float(last["open"]))
        candle_range = max(self._safe_float(last["high"]) - self._safe_float(last["low"]), self.cfg.epsilon)
        wick_up = self._safe_float(last["high"]) - max(self._safe_float(last["open"]), self._safe_float(last["close"]))
        wick_down = min(self._safe_float(last["open"]), self._safe_float(last["close"])) - self._safe_float(last["low"])
        wick_ratio = max(wick_up, wick_down) / candle_range

        tolerance = max(atr * self.cfg.equal_level_tolerance_atr, self.cfg.epsilon)
        equal_lows = []
        equal_highs = []

        for points, collector in ((lows, equal_lows), (highs, equal_highs)):
            for i in range(1, len(points)):
                if abs(points[i][1] - points[i - 1][1]) <= tolerance:
                    collector.append((points[i - 1][1] + points[i][1]) / 2.0)

        if side == "BUY":
            level = equal_lows[-1] if equal_lows else (swings["lows"][-1][1] if swings["lows"] else None)
            if level is None:
                return {"confirmed": False, "score": 0.0, "details": {"reason": "No sell-side liquidity pool found."}}
            swept = self._safe_float(last["low"]) < level - tolerance
            recovered = self._safe_float(last["close"]) > level
            volume_ok = vol["relative"] >= self.cfg.sweep_volume_multiplier and vol["status"]
            wick_ok = wick_down / candle_range >= self.cfg.sweep_wick_ratio_min
            confirmed = bool(swept and recovered and volume_ok and wick_ok and body > 0)
            return {
                "confirmed": confirmed,
                "score": self._clamp(
                    (self.cfg.score_max if swept else 0.0) * 0.35
                    + (self.cfg.score_max if recovered else 0.0) * 0.25
                    + (self.cfg.score_max if volume_ok else 0.0) * 0.20
                    + (self.cfg.score_max if wick_ok else 0.0) * 0.20,
                    0.0,
                    self.cfg.score_max,
                ),
                "details": {
                    "level": round(level, 6),
                    "swept": swept,
                    "recovered": recovered,
                    "volume_ok": volume_ok,
                    "wick_ratio": round(wick_down / candle_range, 4),
                    "equal_lows": [round(x, 6) for x in equal_lows],
                },
            }

        level = equal_highs[-1] if equal_highs else (swings["highs"][-1][1] if swings["highs"] else None)
        if level is None:
            return {"confirmed": False, "score": 0.0, "details": {"reason": "No buy-side liquidity pool found."}}
        swept = self._safe_float(last["high"]) > level + tolerance
        recovered = self._safe_float(last["close"]) < level
        volume_ok = vol["relative"] >= self.cfg.sweep_volume_multiplier and vol["status"]
        wick_ok = wick_up / candle_range >= self.cfg.sweep_wick_ratio_min
        confirmed = bool(swept and recovered and volume_ok and wick_ok and body > 0)
        return {
            "confirmed": confirmed,
            "score": self._clamp(
                (self.cfg.score_max if swept else 0.0) * 0.35
                + (self.cfg.score_max if recovered else 0.0) * 0.25
                + (self.cfg.score_max if volume_ok else 0.0) * 0.20
                + (self.cfg.score_max if wick_ok else 0.0) * 0.20,
                0.0,
                self.cfg.score_max,
            ),
            "details": {
                "level": round(level, 6),
                "swept": swept,
                "recovered": recovered,
                "volume_ok": volume_ok,
                "wick_ratio": round(wick_up / candle_range, 4),
                "equal_highs": [round(x, 6) for x in equal_highs],
            },
        }

    def _structure_break_side(self, frame: pd.DataFrame, side: str, regime: Dict[str, Any], atr: float, vol: Dict[str, Any], swings: Dict[str, List[Tuple[int, float]]]) -> Dict[str, Any]:
        close = frame["close"]
        last_close = self._safe_float(close.iloc[-1])
        prev_close = self._safe_float(close.iloc[-2]) if len(close) >= 2 else last_close
        body = abs(self._safe_float(frame["close"].iloc[-1]) - self._safe_float(frame["open"].iloc[-1]))
        candle_range = max(self._safe_float(frame["high"].iloc[-1]) - self._safe_float(frame["low"].iloc[-1]), self.cfg.epsilon)

        last_swing_high = swings["highs"][-1][1] if swings["highs"] else None
        last_swing_low = swings["lows"][-1][1] if swings["lows"] else None

        if side == "BUY":
            if last_swing_high is None:
                return {"bos": False, "choch": False, "confirmed": False, "details": {"reason": "No swing high available."}}
            min_distance = max(atr * self.cfg.min_break_distance_atr, last_swing_high * self.cfg.epsilon)
            close_beyond = last_close >= last_swing_high + max(atr * self.cfg.min_close_beyond_atr, self.cfg.epsilon)
            prev_inside = prev_close <= last_swing_high + max(atr * self.cfg.min_close_beyond_atr, self.cfg.epsilon)
            confirmation_closes = (close.iloc[-min(self.cfg.confirmation_closes, len(close)) :] > last_swing_high).sum()
            atr_confirmation = body >= atr * 0.5 if atr > self.cfg.epsilon else body > 0
            volume_confirmation = vol["relative"] >= self.cfg.sweep_volume_multiplier and vol["status"]
            false_breakout_filter = close_beyond and prev_inside and confirmation_closes >= self.cfg.confirmation_closes and atr_confirmation and volume_confirmation
            bos = bool(close_beyond and false_breakout_filter and last_close - last_swing_high >= min_distance)
            choch = bool(bos and regime["bias"] == "BEARISH")
            return {
                "bos": bos,
                "choch": choch,
                "confirmed": bos or choch,
                "details": {
                    "level": round(last_swing_high, 6),
                    "close": round(last_close, 6),
                    "prev_close": round(prev_close, 6),
                    "close_beyond": close_beyond,
                    "confirmation_closes": int(confirmation_closes),
                    "atr_confirmation": atr_confirmation,
                    "volume_confirmation": volume_confirmation,
                    "min_distance": round(min_distance, 6),
                    "false_breakout_filter": false_breakout_filter,
                },
            }

        if last_swing_low is None:
            return {"bos": False, "choch": False, "confirmed": False, "details": {"reason": "No swing low available."}}
        min_distance = max(atr * self.cfg.min_break_distance_atr, last_swing_low * self.cfg.epsilon)
        close_beyond = last_close <= last_swing_low - max(atr * self.cfg.min_close_beyond_atr, self.cfg.epsilon)
        prev_inside = prev_close >= last_swing_low - max(atr * self.cfg.min_close_beyond_atr, self.cfg.epsilon)
        confirmation_closes = (close.iloc[-min(self.cfg.confirmation_closes, len(close)) :] < last_swing_low).sum()
        atr_confirmation = body >= atr * 0.5 if atr > self.cfg.epsilon else body > 0
        volume_confirmation = vol["relative"] >= self.cfg.sweep_volume_multiplier and vol["status"]
        false_breakout_filter = close_beyond and prev_inside and confirmation_closes >= self.cfg.confirmation_closes and atr_confirmation and volume_confirmation
        bos = bool(close_beyond and false_breakout_filter and last_swing_low - last_close >= min_distance)
        choch = bool(bos and regime["bias"] == "BULLISH")
        return {
            "bos": bos,
            "choch": choch,
            "confirmed": bos or choch,
            "details": {
                "level": round(last_swing_low, 6),
                "close": round(last_close, 6),
                "prev_close": round(prev_close, 6),
                "close_beyond": close_beyond,
                "confirmation_closes": int(confirmation_closes),
                "atr_confirmation": atr_confirmation,
                "volume_confirmation": volume_confirmation,
                "min_distance": round(min_distance, 6),
                "false_breakout_filter": false_breakout_filter,
            },
        }

    def _order_block_side(self, frame: pd.DataFrame, side: str, atr: float, vol: Dict[str, Any], structure_break: Dict[str, Any]) -> Dict[str, Any]:
        lookback = min(self.cfg.ob_lookback, len(frame) - 1)
        if lookback <= 1:
            return {"valid": False, "retested": False, "reaction_strength": 0.0, "zone": None, "details": {"reason": "Not enough candles for OB."}}

        current = frame.iloc[-1]
        zone = None
        ob_index = None

        search = frame.iloc[-(lookback + 1) : -1]
        if side == "BUY":
            candidates = search[search["close"] < search["open"]]
            if not candidates.empty:
                ob_index = int(candidates.index[-1])
                candle = candidates.iloc[-1]
                zone = {
                    "low": round(self._safe_float(min(candle["open"], candle["close"], candle["low"])), 6),
                    "high": round(self._safe_float(max(candle["open"], candle["close"], candle["high"])), 6),
                }
            if zone is None:
                return {"valid": False, "retested": False, "reaction_strength": 0.0, "zone": None, "details": {"reason": "No bullish OB candidate found."}}

            retested = self._safe_float(current["low"]) <= zone["high"] and self._safe_float(current["close"]) > zone["high"]
            reaction_strength = self._clamp((self._safe_float(current["close"]) - zone["high"]) / max(atr, self.cfg.epsilon), 0.0, self.cfg.score_max) / self.cfg.score_max
            breaker = bool(structure_break["confirmed"] and self._safe_float(current["close"]) > zone["high"])
            mitigation = bool(retested and breaker and vol["status"])
            valid = bool(retested and structure_break["confirmed"] and vol["status"])
            return {
                "valid": valid,
                "retested": retested,
                "reaction_strength": round(reaction_strength, 4),
                "zone": zone,
                "breaker_block": breaker,
                "mitigation_block": mitigation,
                "details": {
                    "ob_index": ob_index,
                    "volume_ok": vol["status"],
                    "zone_touch": retested,
                },
            }

        candidates = search[search["close"] > search["open"]]
        if candidates.empty:
            return {"valid": False, "retested": False, "reaction_strength": 0.0, "zone": None, "details": {"reason": "No bearish OB candidate found."}}

        ob_index = int(candidates.index[-1])
        candle = candidates.iloc[-1]
        zone = {
            "low": round(self._safe_float(min(candle["open"], candle["close"], candle["low"])), 6),
            "high": round(self._safe_float(max(candle["open"], candle["close"], candle["high"])), 6),
        }
        retested = self._safe_float(current["high"]) >= zone["low"] and self._safe_float(current["close"]) < zone["low"]
        reaction_strength = self._clamp((zone["low"] - self._safe_float(current["close"])) / max(atr, self.cfg.epsilon), 0.0, self.cfg.score_max) / self.cfg.score_max
        breaker = bool(structure_break["confirmed"] and self._safe_float(current["close"]) < zone["low"])
        mitigation = bool(retested and breaker and vol["status"])
        valid = bool(retested and structure_break["confirmed"] and vol["status"])
        return {
            "valid": valid,
            "retested": retested,
            "reaction_strength": round(reaction_strength, 4),
            "zone": zone,
            "breaker_block": breaker,
            "mitigation_block": mitigation,
            "details": {
                "ob_index": ob_index,
                "volume_ok": vol["status"],
                "zone_touch": retested,
            },
        }

    def _fvg_side(self, frame: pd.DataFrame, side: str, atr: float) -> Dict[str, Any]:
        if len(frame) < 3:
            return {"valid": False, "gap_size": 0.0, "details": {"reason": "Not enough candles for FVG."}}

        c1 = frame.iloc[-3]
        c2 = frame.iloc[-2]
        c3 = frame.iloc[-1]

        if side == "BUY":
            gap = self._safe_float(c3["low"]) - self._safe_float(c1["high"])
            valid = gap > max(atr * self.cfg.fvg_min_gap_atr, self.cfg.epsilon)
            return {
                "valid": valid,
                "gap_size": round(gap, 6),
                "details": {
                    "high_prev": round(self._safe_float(c1["high"]), 6),
                    "low_current": round(self._safe_float(c3["low"]), 6),
                    "middle_body": round(abs(self._safe_float(c2["close"]) - self._safe_float(c2["open"])), 6),
                },
            }

        gap = self._safe_float(c1["low"]) - self._safe_float(c3["high"])
        valid = gap > max(atr * self.cfg.fvg_min_gap_atr, self.cfg.epsilon)
        return {
            "valid": valid,
            "gap_size": round(gap, 6),
            "details": {
                "low_prev": round(self._safe_float(c1["low"]), 6),
                "high_current": round(self._safe_float(c3["high"]), 6),
                "middle_body": round(abs(self._safe_float(c2["close"]) - self._safe_float(c2["open"])), 6),
            },
        }

    def _premium_discount(self, frame: pd.DataFrame, side: str, swings: Dict[str, List[Tuple[int, float]]]) -> Dict[str, Any]:
        last_close = self._safe_float(frame["close"].iloc[-1])
        swing_high = swings["highs"][-1][1] if swings["highs"] else self._safe_float(frame["high"].max())
        swing_low = swings["lows"][-1][1] if swings["lows"] else self._safe_float(frame["low"].min())
        midpoint = (swing_high + swing_low) / 2.0 if swing_high > swing_low else last_close
        if side == "BUY":
            in_discount = last_close <= midpoint
            return {
                "valid": in_discount,
                "zone": "DISCOUNT" if in_discount else "PREMIUM",
                "midpoint": round(midpoint, 6),
                "current": round(last_close, 6),
            }
        in_premium = last_close >= midpoint
        return {
            "valid": in_premium,
            "zone": "PREMIUM" if in_premium else "DISCOUNT",
            "midpoint": round(midpoint, 6),
            "current": round(last_close, 6),
        }

    def _evaluate_smc_side(self, frame: pd.DataFrame, side: str, regime: Dict[str, Any], indicators: Dict[str, Any]) -> Dict[str, Any]:
        close = frame["close"]
        high = frame["high"]
        low = frame["low"]
        volume = frame["volume"]

        atr = self._safe_float(AverageTrueRange(high, low, close).average_true_range().iloc[-1])
        swings = self._pivot_points(frame)
        vol = indicators["Volume"]

        liquidity = self._liquidity_sweep_side(frame, side, atr, vol, swings)
        structure_break = self._structure_break_side(frame, side, regime, atr, vol, swings)
        fvg = self._fvg_side(frame, side, atr)
        ob = self._order_block_side(frame, side, atr, vol, structure_break)
        premium_discount = self._premium_discount(frame, side, swings)

        equal_levels_valid = bool(swings["highs"]) or bool(swings["lows"])
        inducement = False
        if len(frame) >= 10:
            recent = frame.iloc[-10:-1]
            if side == "BUY":
                inducement = self._safe_float(frame["low"].iloc[-1]) < self._safe_float(recent["low"].min()) and self._safe_float(frame["close"].iloc[-1]) > self._safe_float(recent["low"].min())
            else:
                inducement = self._safe_float(frame["high"].iloc[-1]) > self._safe_float(recent["high"].max()) and self._safe_float(frame["close"].iloc[-1]) < self._safe_float(recent["high"].max())

        volume_confirmation = bool(vol["status"])
        reaction_strength = ob["reaction_strength"] if isinstance(ob, dict) else 0.0

        essential = {
            "liquidity_sweep": liquidity["confirmed"],
            "structure_break": structure_break["confirmed"],
            "fvg_or_ob": fvg["valid"] or ob["valid"],
            "retest": ob["retested"] if isinstance(ob, dict) else False,
            "volume": volume_confirmation,
        }
        institutional_grade = all(essential.values())

        components = [
            SMCComponent("liquidity_sweep", liquidity["confirmed"], self.smc_weights["liquidity_sweep"] if liquidity["confirmed"] else 0.0, self.smc_weights["liquidity_sweep"], liquidity),
            SMCComponent("bos", structure_break["bos"], self.smc_weights["bos"] if structure_break["bos"] else 0.0, self.smc_weights["bos"], structure_break),
            SMCComponent("choch", structure_break["choch"], self.smc_weights["choch"] if structure_break["choch"] else 0.0, self.smc_weights["choch"], structure_break),
            SMCComponent("fvg", fvg["valid"], self.smc_weights["fvg"] if fvg["valid"] else 0.0, self.smc_weights["fvg"], fvg),
            SMCComponent("order_block", ob["valid"], self.smc_weights["order_block"] if ob["valid"] else 0.0, self.smc_weights["order_block"], ob),
            SMCComponent("breaker_block", bool(ob.get("breaker_block")), self.smc_weights["breaker_block"] if ob.get("breaker_block") else 0.0, self.smc_weights["breaker_block"], ob),
            SMCComponent("mitigation_block", bool(ob.get("mitigation_block")), self.smc_weights["mitigation_block"] if ob.get("mitigation_block") else 0.0, self.smc_weights["mitigation_block"], ob),
            SMCComponent("premium_discount", premium_discount["valid"], self.smc_weights["premium_discount"] if premium_discount["valid"] else 0.0, self.smc_weights["premium_discount"], premium_discount),
            SMCComponent("volume_confirmation", volume_confirmation, self.smc_weights["volume_confirmation"] if volume_confirmation else 0.0, self.smc_weights["volume_confirmation"], vol),
            SMCComponent("equal_highs_lows", equal_levels_valid, self.smc_weights["equal_highs_lows"] if equal_levels_valid else 0.0, self.smc_weights["equal_highs_lows"], {"equal_highs": len(swings["highs"]), "equal_lows": len(swings["lows"])}),
            SMCComponent("inducement", inducement, self.smc_weights["inducement"] if inducement else 0.0, self.smc_weights["inducement"], {"inducement": inducement}),
        ]

        total_weight = sum(component.weight for component in components)
        score = sum(component.score for component in components)
        confidence = self._clamp((score / max(total_weight, self.cfg.epsilon)) * self.cfg.score_max if total_weight else 0.0, 0.0, 100.0)

        detected_structures = []
        if liquidity["confirmed"]:
            detected_structures.append("Liquidity Sweep")
        if structure_break["bos"]:
            detected_structures.append("BOS")
        if structure_break["choch"]:
            detected_structures.append("CHOCH")
        if fvg["valid"]:
            detected_structures.append("FVG")
        if ob["valid"]:
            detected_structures.append("Order Block")
        if ob.get("breaker_block"):
            detected_structures.append("Breaker Block")
        if ob.get("mitigation_block"):
            detected_structures.append("Mitigation Block")
        if inducement:
            detected_structures.append("Inducement")

        reasons = [component.name for component in components if component.confirmed]

        return {
            "direction": side,
            "strength": round(score, 2),
            "confidence": round(confidence, 2),
            "reasons": reasons,
            "detected_structures": detected_structures,
            "institutional_grade": institutional_grade,
            "components": [component.__dict__ for component in components],
            "details": {
                "has_liq_sweep": liquidity["confirmed"],
                "has_structure": structure_break["confirmed"],
                "has_retest": ob["retested"],
                "has_volume": volume_confirmation,
                "has_ob_or_fvg": fvg["valid"] or ob["valid"],
                "reaction_strength": round(reaction_strength, 4),
                "premium_discount": premium_discount,
                "liquidity": liquidity,
                "structure_break": structure_break,
                "fvg": fvg,
                "order_block": ob,
            },
            "bullish_score": round(score if side == "BUY" else 0.0, 2),
            "bearish_score": round(score if side == "SELL" else 0.0, 2),
        }

    def get_smc_data(self, df: pd.DataFrame) -> dict:
        frame = self._clean_df(df)
        regime = self.classify_market(frame)
        indicators = self.get_indicators_data(frame)

        bull = self._evaluate_smc_side(frame, "BUY", regime, indicators)
        bear = self._evaluate_smc_side(frame, "SELL", regime, indicators)

        if bull["strength"] > bear["strength"]:
            direction = "BUY"
            active = bull
        elif bear["strength"] > bull["strength"]:
            direction = "SELL"
            active = bear
        else:
            direction = "NEUTRAL"
            active = bull if regime["bias"] == "BULLISH" else bear if regime["bias"] == "BEARISH" else bull

        return {
            "direction": direction,
            "strength": round(active["strength"], 2),
            "confidence": round(active["confidence"], 2),
            "reasons": active["reasons"],
            "detected_structures": active["detected_structures"],
            "institutional_grade": active["institutional_grade"],
            "bullish_score": round(bull["strength"], 2),
            "bearish_score": round(bear["strength"], 2),
            "components": {"BUY": bull["components"], "SELL": bear["components"]},
            "details": {
                "has_liq_sweep": bull["details"]["has_liq_sweep"] or bear["details"]["has_liq_sweep"],
                "has_structure": bull["details"]["has_structure"] or bear["details"]["has_structure"],
                "has_retest": bull["details"]["has_retest"] or bear["details"]["has_retest"],
                "has_volume": bull["details"]["has_volume"] or bear["details"]["has_volume"],
                "has_ob_or_fvg": bull["details"]["has_ob_or_fvg"] or bear["details"]["has_ob_or_fvg"],
                "active_side": direction,
                "buy": bull["details"],
                "sell": bear["details"],
            },
        }

    # ------------------------------------------------------------------
    # Risk engine
    # ------------------------------------------------------------------
    def analyze_risk(self, df: pd.DataFrame, side: str) -> Dict[str, Any]:
        frame = self._clean_df(df)
        side = (side or "BUY").upper()
        if side not in {"BUY", "SELL"}:
            return {
                "entry": self._safe_float(frame["close"].iloc[-1]),
                "atr_stop": None,
                "swing_stop": None,
                "selected_stop": None,
                "target": None,
                "risk_pct": 0.0,
                "rr": 0.0,
                "required": self.cfg.rr_min,
                "valid": False,
                "reason": "Invalid side.",
            }

        entry = self._safe_float(frame["close"].iloc[-1])
        high = frame["high"]
        low = frame["low"]
        close = frame["close"]
        atr = self._safe_float(AverageTrueRange(high, low, close).average_true_range().iloc[-1])
        swings = self._pivot_points(frame)
        last_swing_high = swings["highs"][-1][1] if swings["highs"] else None
        last_swing_low = swings["lows"][-1][1] if swings["lows"] else None

        if side == "BUY":
            atr_stop = entry - (atr * self.cfg.atr_stop_multiplier)
            swing_stop = (last_swing_low - (atr * self.cfg.swing_stop_buffer_atr)) if last_swing_low is not None else atr_stop
            selected_stop = min(atr_stop, swing_stop)
            risk = abs(entry - selected_stop)
            target = entry + (risk * self.cfg.rr_min)
        else:
            atr_stop = entry + (atr * self.cfg.atr_stop_multiplier)
            swing_stop = (last_swing_high + (atr * self.cfg.swing_stop_buffer_atr)) if last_swing_high is not None else atr_stop
            selected_stop = max(atr_stop, swing_stop)
            risk = abs(selected_stop - entry)
            target = entry - (risk * self.cfg.rr_min)

        rr = abs(target - entry) / max(abs(entry - selected_stop), self.cfg.epsilon)
        risk_pct = abs(entry - selected_stop) / max(entry, self.cfg.epsilon) * self.cfg.score_max

        return {
            "entry": round(entry, 8),
            "atr_stop": round(atr_stop, 8),
            "swing_stop": round(swing_stop, 8) if swing_stop is not None else None,
            "selected_stop": round(selected_stop, 8),
            "target": round(target, 8),
            "risk_pct": round(risk_pct, 4),
            "rr": round(rr, 4),
            "required": self.cfg.rr_min,
            "valid": rr >= self.cfg.rr_min,
            "atr": round(atr, 8),
            "swing_high": round(last_swing_high, 8) if last_swing_high is not None else None,
            "swing_low": round(last_swing_low, 8) if last_swing_low is not None else None,
        }

    # ------------------------------------------------------------------
    # Decision helpers
    # ------------------------------------------------------------------
    def _reason(self, name: str, current: Any, required: Any, impact: float, suggested_fix: str) -> Dict[str, Any]:
        return {
            "name": name,
            "current_value": current,
            "required_value": required,
            "impact": round(float(impact), 2),
            "suggested_fix": suggested_fix,
        }

    def _rejection_from_condition(self, condition: Dict[str, Any]) -> Dict[str, Any]:
        return self._reason(
            condition["name"],
            condition.get("current_value"),
            condition.get("required_value"),
            condition.get("impact", 0.0),
            condition.get("suggested_fix", "Review the related input and threshold."),
        )

    def _condition(self, name: str, status: bool, current_value: Any, required_value: Any, impact: float, suggested_fix: str) -> Dict[str, Any]:
        return {
            "name": name,
            "status": bool(status),
            "current_value": current_value,
            "required_value": required_value,
            "impact": round(float(impact), 2),
            "suggested_fix": suggested_fix,
        }

    def _score_breakdown(self, regime: Dict[str, Any], indicators: Dict[str, Any], smc: Dict[str, Any], htf: Dict[str, Any], risk: Dict[str, Any], data_quality: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        momentum_score = indicators["Momentum"]["current"]
        volume_score = self._clamp(indicators["Volume"]["current"] / max(indicators["Volume"]["threshold"], self.cfg.epsilon) * self.cfg.score_max, 0.0, 100.0)
        smc_score = smc["confidence"]
        trend_score = regime["trend_strength"]
        htf_score = self.cfg.score_max if htf["supported"] else 0.0
        risk_score = self._clamp((risk["rr"] / self.cfg.rr_min) * self.cfg.score_max, 0.0, 100.0) if risk["rr"] else 0.0
        data_score = data_quality["score"]

        return {
            "Data Quality": {"score": round(data_score, 2), "max": self.cfg.score_max, "reason": "Structural data health and completeness."},
            "Trend": {"score": round(trend_score, 2), "max": self.cfg.score_max, "reason": regime["reason"]},
            "Momentum": {"score": round(momentum_score, 2), "max": self.cfg.score_max, "reason": f"RSI={indicators['RSI']['current']}, MACD={indicators['MACD']['current']}"},
            "Volume": {"score": round(volume_score, 2), "max": self.cfg.score_max, "reason": f"Session={indicators['Volume']['session']} | Z={indicators['Volume']['z_score']}"},
            "SMC": {"score": round(smc_score, 2), "max": self.cfg.score_max, "reason": ", ".join(smc["detected_structures"]) or "No structure"},
            "HTF": {"score": round(htf_score, 2), "max": self.cfg.score_max, "reason": htf["reason"]},
            "Risk Context": {"score": round(risk_score, 2), "max": self.cfg.score_max, "reason": f"RR={risk['rr']} | Risk%={risk['risk_pct']}"},
        }

    def calculate_combined_score(self, df: pd.DataFrame, df_higher: Optional[pd.DataFrame] = None, historical_performance: Optional[Dict[str, Any]] = None) -> dict:
        start_ts = datetime.now(timezone.utc)

        frame = self._clean_df(df)
        data_quality = self._data_quality_report(frame)
        regime = self.classify_market(frame)
        indicators = self.get_indicators_data(frame)
        smc = self.get_smc_data(frame)

        candidate_side = smc["direction"]
        if candidate_side == "NEUTRAL":
            candidate_side = regime["bias"]
        if candidate_side == "NEUTRAL":
            candidate_side = "BUY" if regime["trend_strength"] >= self.cfg.trend_confidence_min else "SELL" if regime["bias"] == "BEARISH" else "NEUTRAL"

        htf = self._htf_filter(df_higher, candidate_side, regime)
        risk = self.analyze_risk(frame, candidate_side if candidate_side in {"BUY", "SELL"} else "BUY")
        score_data = {"total": 0, "breakdown": {}}
        quality_data = {"total": 0, "breakdown": {}}
        validation_conditions: List[Dict[str, Any]] = []
        rejections: List[Dict[str, Any]] = []

        # Hard gate calculations
        data_ok = data_quality["valid"] and data_quality["score"] >= self.cfg.required_data_quality
        trend_ok = regime["confidence"] >= self.cfg.trend_confidence_min and regime["bias"] in {"BULLISH", "BEARISH"}
        structure_ok = smc["details"]["has_structure"] and smc["details"]["has_liq_sweep"]
        smc_grade_ok = smc["institutional_grade"]
        volume_ok = indicators["Volume"]["status"]
        htf_ok = htf["supported"]
        regime_ok = regime["state"] not in {"Choppy/Sideways", "Transition/Range", "Low Data", "Invalid Data"}
        rr_ok = risk["rr"] >= self.cfg.rr_min
        side_ok = candidate_side in {"BUY", "SELL"}

        validation_conditions.extend([
            self._condition("Data Quality 100%", data_ok, data_quality["score"], self.cfg.required_data_quality, 100.0 - data_quality["score"], "Clean the dataset and reload at least the minimum candle count."),
            self._condition("Directional Trend", trend_ok, regime["confidence"], self.cfg.trend_confidence_min, max(self.cfg.trend_confidence_min - regime["confidence"], 0.0), "Wait for a stronger aligned trend."),
            self._condition("BOS/CHOCH Confirmed", smc["details"].get("has_structure", False), smc["details"].get("structure_break", {}).get("confirmed", False), True, 20.0 if not smc["details"].get("has_structure", False) else 0.0, "Wait for a real swing break."),
            self._condition("Liquidity Sweep", smc["details"].get("has_liq_sweep", False), True, True, 20.0 if not smc["details"].get("has_liq_sweep", False) else 0.0, "Require a real sweep of equal highs/lows."),
            self._condition("Order Block / FVG", smc["details"].get("has_ob_or_fvg", False), True, True, 20.0 if not smc["details"].get("has_ob_or_fvg", False) else 0.0, "Require a validated institutional zone."),
            self._condition("Retest", smc["details"].get("has_retest", False), True, True, 20.0 if not smc["details"].get("has_retest", False) else 0.0, "Wait for a clean retest and rejection."),
            self._condition("Volume Confirmation", volume_ok, indicators["Volume"]["current"], indicators["Volume"]["threshold"], max(indicators["Volume"]["threshold"] - indicators["Volume"]["current"], 0.0), "Wait for volume expansion beyond the dynamic threshold."),
            self._condition("HTF Alignment", htf_ok, htf["status"], "PASS", 20.0 if not htf_ok else 0.0, "Wait until higher timeframe confirms the direction."),
            self._condition("Regime Not Sideways", regime_ok, regime["state"], "Strong Trend", 20.0 if not regime_ok else 0.0, "Avoid choppy or transition regimes."),
            self._condition("RR >= 2.0", rr_ok, risk["rr"], self.cfg.rr_min, max(self.cfg.rr_min - risk["rr"], 0.0) * 50.0, "Improve entry or stop placement to raise RR."),
        ])

        # Build detailed rejection reasons
        for condition in validation_conditions:
            if not condition["status"]:
                rejections.append(self._rejection_from_condition(condition))

        if htf["status"] in {"UNKNOWN", "IGNORE_WITH_PENALTY", "SKIP"} and not htf_ok:
            rejections.append(self._reason(
                "HTF Policy",
                htf["status"],
                "PASS",
                self.cfg.htf_missing_confidence_penalty,
                "HTF data is required for institutional-grade entries.",
            ))

        if not side_ok:
            rejections.append(self._reason("Side Selection", candidate_side, "BUY or SELL", 100.0, "Wait for a clear directional bias."))

        # Score / quality computations
        score_breakdown = self._score_breakdown(regime, indicators, smc, htf, risk, data_quality)
        score_data["breakdown"] = score_breakdown
        score_data["total"] = round(sum(item["score"] for item in score_breakdown.values()) / len(score_breakdown), 2)

        quality_breakdown = {
            "data_quality": data_quality["score"],
            "trend_quality": regime["trend_strength"],
            "momentum_quality": indicators["Momentum"]["current"],
            "smc_quality": smc["confidence"],
            "htf_quality": 100.0 if htf["supported"] else max(0.0, 100.0 - htf.get("confidence_penalty", 0.0)),
            "volume_quality": self._clamp((indicators["Volume"]["current"] / max(indicators["Volume"]["threshold"], self.cfg.epsilon)) * self.cfg.score_max, 0.0, 100.0),
            "regime_stability": regime["confidence"],
        }
        quality_total = sum(quality_breakdown.values()) / len(quality_breakdown)
        quality_data = {"total": round(quality_total, 2), "breakdown": {k: round(v, 2) for k, v in quality_breakdown.items()}}

        # Confidence is independent from the score.
        confidence = (
            data_quality["score"] * self.cfg.confidence_weights["data_quality"]
            + regime["confidence"] * self.cfg.confidence_weights["trend_quality"]
            + indicators["Momentum"]["current"] * self.cfg.confidence_weights["momentum_quality"]
            + smc["confidence"] * self.cfg.confidence_weights["smc_quality"]
            + (100.0 if htf["supported"] else max(0.0, 100.0 - htf.get("confidence_penalty", 0.0))) * self.cfg.confidence_weights["htf_quality"]
            + quality_breakdown["volume_quality"] * self.cfg.confidence_weights["volume_quality"]
            + regime["confidence"] * self.cfg.confidence_weights["regime_stability"]
        )

        if htf["status"] in {"UNKNOWN", "IGNORE_WITH_PENALTY", "SKIP"}:
            confidence -= htf.get("confidence_penalty", 0.0)

        confidence = self._clamp(confidence, self.cfg.confidence_floor, self.cfg.confidence_ceiling)

        # Probability is independent from score too.
        historical_score = 50.0
        if historical_performance:
            if "win_rate" in historical_performance:
                historical_score = self._clamp(self._safe_float(historical_performance["win_rate"]), 0.0, 100.0)
            elif "expectancy" in historical_performance:
                historical_score = self._clamp(50.0 + self._safe_float(historical_performance["expectancy"]) * 10.0, 0.0, 100.0)

        momentum_score = indicators["Momentum"]["current"]
        volume_score = quality_breakdown["volume_quality"]
        htf_score = 100.0 if htf["supported"] else max(0.0, 100.0 - htf.get("probability_penalty", 0.0))
        risk_score = self._clamp((risk["rr"] / self.cfg.rr_min) * 100.0, 0.0, 100.0) if risk["rr"] else 0.0
        probability = (
            regime["trend_strength"] * self.cfg.probability_weights["trend_strength"]
            + regime["confidence"] * self.cfg.probability_weights["regime"]
            + momentum_score * self.cfg.probability_weights["momentum"]
            + volume_score * self.cfg.probability_weights["volume"]
            + htf_score * self.cfg.probability_weights["htf"]
            + smc["confidence"] * self.cfg.probability_weights["smc"]
            + risk_score * self.cfg.probability_weights["risk"]
            + historical_score * self.cfg.probability_weights["historical_performance"]
        )

        if not data_quality["valid"]:
            probability = 0.0

        probability = self._clamp(probability, self.cfg.score_min if data_quality["valid"] else 0.0, self.cfg.probability_ceiling)
        if data_quality["valid"]:
            probability = max(self.cfg.probability_floor, probability)

        # Final verdict
        all_required = all(cond["status"] for cond in validation_conditions)
        verdict = candidate_side if candidate_side in {"BUY", "SELL"} and all_required else "SKIP"

        if not all_required and not rejections:
            rejections.append(self._reason("Composite Gate", "FAILED", "ALL_REQUIRED", 100.0, "One or more mandatory conditions failed."))

        decision_path = [cond["name"] for cond in validation_conditions]
        execution_time = (datetime.now(timezone.utc) - start_ts).total_seconds()

        final_reason_text = " | ".join(f"{r['name']}: {r['current_value']} -> {r['required_value']}" for r in rejections) if rejections else "All mandatory conditions satisfied."
        final_reasons = rejections if verdict == "SKIP" else smc["reasons"]

        return {
            "total_score": int(round(score_data["total"])),
            "verdict": verdict,
            "reasons": final_reasons,
            "reason": final_reason_text,
            "regime_data": regime,
            "indicators_data": indicators,
            "smc_data": smc,
            "htf_data": htf,
            "confidence": int(round(confidence)),
            "probability": int(round(probability)),
            "score_data": score_data,
            "quality_data": quality_data,
            "rejection_data": {"reasons": rejections},
            "validation_data": {"conditions": validation_conditions},
            "risk_data": risk,
            "debug_report": {
                "inputs": {
                    "ltf_candles": len(frame),
                    "htf_candles": len(df_higher) if df_higher is not None else 0,
                    "candidate_side": candidate_side,
                },
                "intermediate": {
                    "data_quality": data_quality,
                    "regime": regime,
                    "indicators": indicators,
                    "smc": smc,
                    "htf": htf,
                    "risk": risk,
                },
                "thresholds": {
                    "trend_confidence_min": self.cfg.trend_confidence_min,
                    "rr_min": self.cfg.rr_min,
                    "data_quality_required": self.cfg.data_quality_required_for_entry,
                    "htf_policy": self.cfg.htf_missing_policy,
                    "volume_threshold": self.cfg.volume_rel_threshold,
                    "volume_zscore_threshold": self.cfg.volume_zscore_threshold,
                },
                "weights": {
                    "confidence": self.cfg.confidence_weights,
                    "probability": self.cfg.probability_weights,
                    "smc": self.smc_weights,
                },
                "decision_path": decision_path,
                "execution_time_seconds": round(execution_time, 6),
            },
        }

    def get_trade_params(self, df: pd.DataFrame, side: str = "BUY") -> dict:
        risk = self.analyze_risk(df, side)
        return {
            "entry": risk["entry"],
            "sl": risk["selected_stop"] if risk["selected_stop"] is not None else risk["entry"],
            "tp": risk["target"] if risk["target"] is not None else risk["entry"],
            "risk_pct": risk["risk_pct"],
            "rr": risk["rr"],
        }
