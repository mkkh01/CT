from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    score_threshold: int = 70
    atr_stop_multiplier: float = 2.0
    take_profit_r: float = 2.0
    swing_buffer_atr: float = 0.20
    stop_method: str = "atr"
    max_bars_in_trade: int = 96
    breakeven_trigger_r: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def score_components(row: pd.Series) -> dict[str, float]:
    trend = 20.0 if bool(row.get("trend_filter", False)) else 0.0
    structure = 20.0 if bool(row.get("bullish_structure", False)) else 0.0
    momentum = 15.0 if bool(row.get("momentum_confirmed", False)) else 0.0
    volume = 15.0 if bool(row.get("volume_confirmed", False)) else 0.0
    liquidity = 10.0 if bool(row.get("breakout_up", False)) or bool(row.get("pullback_to_fast", False)) else 0.0
    volatility = 10.0 if 0.001 <= float(row.get("atr_pct", 0.0) or 0.0) <= 0.08 else 0.0
    entry_quality = 10.0 if bool(row.get("bullish_candle", False)) else 0.0
    return {"trend": trend, "structure": structure, "momentum": momentum, "volume": volume, "liquidity": liquidity, "volatility": volatility, "entry_quality": entry_quality}


def score_row(row: pd.Series) -> float:
    return float(sum(score_components(row).values()))


def strategy_entry(name: str, row: pd.Series, score_threshold: int) -> bool:
    if not bool(row.get("valid_features", False)):
        return False
    score = score_row(row)
    if score < score_threshold:
        return False
    trend = bool(row.get("trend_filter", False))
    momentum = bool(row.get("momentum_confirmed", False))
    volume = bool(row.get("volume_confirmed", False))
    pullback = bool(row.get("pullback_to_fast", False))
    breakout = bool(row.get("breakout_up", False))
    structure = bool(row.get("bullish_structure", False))
    rsi = float(row.get("rsi", 50.0))
    adx = float(row.get("adx", 0.0) or 0.0)
    low = float(row.get("low", 0.0))
    previous_low = float(row.get("previous_low", 0.0) or 0.0)
    close = float(row.get("close", 0.0))

    rules: dict[str, bool] = {
        "trend_pullback": trend and pullback and momentum,
        "trend_breakout": trend and breakout and momentum and volume,
        "momentum_volume": trend and momentum and volume and rsi >= 55,
        "liquidity_sweep_reversal": trend and previous_low > 0 and low < previous_low and close > previous_low and rsi >= 45,
        "structure_pullback": trend and structure and pullback and 48 <= rsi <= 72,
        "mtf_trend_momentum": trend and adx >= 15 and momentum and volume,
        "bollinger_reversion": bool(row.get("bb_reversion_long", False)) and close > float(row.get("ema_slow", close)) * 0.95 and rsi <= 52,
        "ema_cross_momentum": trend and bool(row.get("ema_cross_up", False)) and momentum and volume,
        "mean_reversion_reclaim": bool(row.get("bb_reversion_long", False)) and rsi <= 48 and close > float(row.get("open", close)),
        "trend_retest_precision": trend and pullback and bool(row.get("bullish_candle", False)) and 48 <= rsi <= 65 and float(row.get("relative_volume", 0.0) or 0.0) >= 0.8,
        "range_reversion": bool(row.get("bb_reversion_long", False)) and rsi <= 42 and float(row.get("atr_pct", 0.0) or 0.0) <= 0.05,
        "high_confidence_reclaim": bool(row.get("bb_reversion_long", False)) and rsi <= 40 and bool(row.get("bullish_candle", False)) and close > float(row.get("ema_fast", close)) and float(row.get("relative_volume", 0.0) or 0.0) >= 1.1,
    }
    return rules.get(name, False)


def candidate_configs(cfg: dict) -> list[StrategyConfig]:
    bt = cfg["backtest"]
    configs: list[StrategyConfig] = []
    names = cfg.get("research", {}).get("enabled_strategies") or [
        "trend_pullback", "trend_breakout", "momentum_volume",
        "liquidity_sweep_reversal", "structure_pullback", "mtf_trend_momentum",
    ]
    high_win_names = {"bollinger_reversion", "mean_reversion_reclaim", "range_reversion", "trend_retest_precision", "high_confidence_reclaim"}
    for name in names:
        thresholds = bt.get("score_thresholds_high_win", [35, 45, 55, 65]) if name in high_win_names else bt.get("score_thresholds", [70])
        target_rs = [0.25, 0.40, 0.50, 0.75, 1.0, 1.5, 2.0] if name in high_win_names else [1.0, 1.5, 2.0, 2.5]
        for threshold in thresholds:
            for stop_mult in [1.5, 2.0, 2.5]:
                for tp_r in target_rs:
                    for stop_method in ["atr", "swing"]:
                        configs.append(StrategyConfig(
                            name=name, score_threshold=int(threshold),
                            atr_stop_multiplier=float(stop_mult), take_profit_r=float(tp_r),
                            stop_method=stop_method,
                            max_bars_in_trade=int(bt.get("max_bars_in_trade", 96)),
                            breakeven_trigger_r=float(0.25 if name in high_win_names else 0.0),
                        ))
    return configs


def add_scores(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    components = df.apply(score_components, axis=1, result_type="expand")
    df[components.columns] = components
    df["score"] = components.sum(axis=1)
    return df
