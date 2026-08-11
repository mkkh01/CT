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
    max_bars_in_trade: int = 96

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
    }
    return rules.get(name, False)


def candidate_configs(cfg: dict) -> list[StrategyConfig]:
    bt = cfg["backtest"]
    configs: list[StrategyConfig] = []
    for name in [
        "trend_pullback", "trend_breakout", "momentum_volume",
        "liquidity_sweep_reversal", "structure_pullback", "mtf_trend_momentum",
    ]:
        for threshold in bt.get("score_thresholds", [70]):
            for stop_mult in [1.5, 2.0, 2.5]:
                for tp_r in [1.5, 2.0, 2.5]:
                    configs.append(StrategyConfig(
                        name=name, score_threshold=int(threshold),
                        atr_stop_multiplier=float(stop_mult), take_profit_r=float(tp_r),
                        max_bars_in_trade=int(bt.get("max_bars_in_trade", 96)),
                    ))
    return configs


def add_scores(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    components = df.apply(score_components, axis=1, result_type="expand")
    df[components.columns] = components
    df["score"] = components.sum(axis=1)
    return df
