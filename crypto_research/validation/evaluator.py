from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

import numpy as np
import pandas as pd

from crypto_research.backtesting.costs import CostModel
from crypto_research.backtesting.engine import compute_metrics, run_backtest
from crypto_research.strategies.candidates import StrategyConfig


def evaluate_strategy(
    universe: dict[str, pd.DataFrame],
    strategy: StrategyConfig,
    costs: CostModel,
    initial_capital: float,
    risk_per_trade: float,
) -> dict:
    all_trades: list[pd.DataFrame] = []
    per_coin: list[dict] = []
    for symbol, frame in universe.items():
        result = run_backtest(frame, strategy, costs, initial_capital, risk_per_trade, symbol=symbol)
        if not result.trades.empty:
            all_trades.append(result.trades)
        row = {"symbol": symbol, **result.metrics, **strategy.to_dict(), **costs.to_dict()}
        per_coin.append(row)
    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    metrics = _portfolio_like_metrics(trades, initial_capital)
    robustness = cross_coin_stability(pd.DataFrame(per_coin))
    return {
        "strategy": strategy.to_dict(), "costs": costs.to_dict(),
        "metrics": metrics, "cross_coin": robustness, "per_coin": per_coin,
        "trades": trades,
    }


def _portfolio_like_metrics(trades: pd.DataFrame, initial_capital: float) -> dict:
    if trades.empty:
        return compute_metrics(pd.DataFrame(), pd.DataFrame(), initial_capital)
    ordered = trades.sort_values("exit_timestamp").reset_index(drop=True)
    equity = initial_capital + ordered["pnl"].cumsum()
    curve = pd.DataFrame({"timestamp": ordered["exit_timestamp"], "equity": equity})
    return compute_metrics(ordered, curve, initial_capital)


def cross_coin_stability(per_coin: pd.DataFrame) -> dict:
    if per_coin.empty:
        return {"coins": 0, "positive_expectancy_share": 0.0, "median_win_rate": 0.0, "median_profit_factor": 0.0, "win_rate_std": 0.0}
    active = per_coin[per_coin["trades"] > 0]
    return {
        "coins": int(len(active)),
        "positive_expectancy_share": float((active["expectancy"] > 0).mean()) if len(active) else 0.0,
        "median_win_rate": float(active["win_rate"].median()) if len(active) else 0.0,
        "median_profit_factor": float(active["profit_factor"].replace(np.inf, np.nan).median()) if len(active) else 0.0,
        "win_rate_std": float(active["win_rate"].std(ddof=0)) if len(active) else 0.0,
    }


def rank_score(result: dict, min_trades: int = 30) -> float:
    m = result["metrics"]
    c = result["cross_coin"]
    if m["trades"] < min_trades or m["expectancy"] <= 0:
        return -1e9
    pf = min(float(m["profit_factor"]), 10.0)
    dd_penalty = abs(float(m["max_drawdown"]))
    trade_support = min(1.0, m["trades"] / 500.0)
    stability = c["positive_expectancy_share"] * max(0.0, 1.0 - c["win_rate_std"])
    return (2.5 * m["expectancy"] / max(1.0, abs(result["metrics"].get("average_loss", 1.0)))
            + 1.5 * m["win_rate"] + 0.6 * pf + 0.8 * stability + 0.4 * trade_support - 1.5 * dd_penalty)


def result_row(result: dict) -> dict:
    return {**result["strategy"], **result["costs"], **result["metrics"], **{f"cross_{k}": v for k, v in result["cross_coin"].items()}, "rank_score": rank_score(result)}
