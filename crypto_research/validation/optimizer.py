from __future__ import annotations

import random
from typing import Any

import pandas as pd

from crypto_research.backtesting.costs import CostModel
from crypto_research.strategies.candidates import StrategyConfig, candidate_configs
from crypto_research.validation.evaluator import evaluate_strategy, rank_score, result_row


def optimize_candidates(
    train_universe: dict[str, pd.DataFrame],
    validation_universe: dict[str, pd.DataFrame],
    cfg: dict,
    costs: CostModel,
    initial_capital: float,
    risk_per_trade: float,
    max_trials: int = 48,
    top_k: int = 8,
    seed: int = 42,
) -> dict[str, Any]:
    candidates = candidate_configs(cfg)
    rng = random.Random(seed)
    if len(candidates) > max_trials:
        groups: dict[str, list[StrategyConfig]] = {}
        for candidate in candidates:
            groups.setdefault(candidate.name, []).append(candidate)
        quota = max(1, max_trials // max(len(groups), 1))
        selected: list[StrategyConfig] = []
        remainder: list[StrategyConfig] = []
        for group in groups.values():
            rng.shuffle(group)
            selected.extend(group[:quota])
            remainder.extend(group[quota:])
        if len(selected) < max_trials:
            selected.extend(rng.sample(remainder, min(max_trials - len(selected), len(remainder))))
        candidates = selected[:max_trials]
    train_results = [evaluate_strategy(train_universe, candidate, costs, initial_capital, risk_per_trade) for candidate in candidates]
    train_rows = pd.DataFrame([result_row(r) for r in train_results]).sort_values("rank_score", ascending=False)
    selected_indices = train_rows.index[:top_k].tolist()
    validation_results = [evaluate_strategy(validation_universe, train_results[int(i)]["strategy_config"] if "strategy_config" in train_results[int(i)] else _config_from_dict(train_rows.loc[i]), costs, initial_capital, risk_per_trade) for i in selected_indices]
    # `train_results` is aligned with candidate order; use a deterministic validation ranking.
    if validation_results:
        validation_rows = pd.DataFrame([result_row(r) for r in validation_results]).sort_values("rank_score", ascending=False)
        best_pos = int(validation_rows.index[0])
        best = validation_results[best_pos]
    else:
        best = train_results[int(train_rows.index[0])] if len(train_rows) else None
        validation_rows = pd.DataFrame()
    return {"best": best, "train_rows": train_rows.reset_index(drop=True), "validation_rows": validation_rows.reset_index(drop=True), "trials": len(candidates)}


def _config_from_dict(row: pd.Series) -> StrategyConfig:
    return StrategyConfig(
        name=str(row["name"]), score_threshold=int(row["score_threshold"]),
        atr_stop_multiplier=float(row["atr_stop_multiplier"]),
        take_profit_r=float(row["take_profit_r"]), swing_buffer_atr=float(row.get("swing_buffer_atr", 0.2)),
        stop_method=str(row.get("stop_method", "atr")),
        max_bars_in_trade=int(row.get("max_bars_in_trade", 96)),
    )
