from __future__ import annotations

from typing import Any

import pandas as pd

from crypto_research.backtesting.engine import compute_metrics, run_backtest
from crypto_research.backtesting.costs import CostModel
from crypto_research.strategies.candidates import StrategyConfig


def run_portfolio_backtest(
    universe: dict[str, pd.DataFrame],
    strategy: StrategyConfig,
    costs: CostModel,
    initial_capital: float,
    risk_per_trade: float,
    max_positions: int,
    max_total_exposure: float = 0.80,
) -> dict[str, Any]:
    candidates: list[pd.DataFrame] = []
    for symbol, frame in universe.items():
        result = run_backtest(frame, strategy, costs, initial_capital, risk_per_trade, symbol=symbol)
        if not result.trades.empty:
            candidates.append(result.trades.copy())
    if not candidates:
        return {"max_positions": max_positions, "trades": pd.DataFrame(), "metrics": compute_metrics(pd.DataFrame(), pd.DataFrame(), initial_capital)}
    all_trades = pd.concat(candidates, ignore_index=True).sort_values(["entry_timestamp", "symbol"]).reset_index(drop=True)
    active: list[tuple[pd.Timestamp, str]] = []
    accepted: list[dict[str, Any]] = []
    allocation = min(max_total_exposure / max(max_positions, 1), 1.0)
    for _, trade in all_trades.iterrows():
        entry = pd.Timestamp(trade["entry_timestamp"])
        active = [(exit, sym) for exit, sym in active if exit > entry]
        if len(active) >= max_positions:
            continue
        if any(sym == trade["symbol"] for _, sym in active):
            continue
        row = trade.to_dict()
        row["portfolio_allocation"] = allocation
        row["portfolio_pnl"] = float(row["pnl"]) * allocation
        row["pnl"] = row["portfolio_pnl"]
        accepted.append(row)
        active.append((pd.Timestamp(trade["exit_timestamp"]), str(trade["symbol"])))
    trades = pd.DataFrame(accepted)
    if trades.empty:
        metrics = compute_metrics(pd.DataFrame(), pd.DataFrame(), initial_capital)
    else:
        ordered = trades.sort_values("exit_timestamp").reset_index(drop=True)
        curve = pd.DataFrame({"timestamp": ordered["exit_timestamp"], "equity": initial_capital + ordered["pnl"].cumsum()})
        metrics = compute_metrics(ordered, curve, initial_capital)
    return {"max_positions": max_positions, "trades": trades, "metrics": metrics}
