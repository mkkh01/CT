from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from crypto_research.backtesting.costs import CostModel
from crypto_research.backtesting.engine import compute_metrics
from crypto_research.strategies.candidates import StrategyConfig
from crypto_research.validation.evaluator import evaluate_strategy


def bootstrap_metrics(trades: pd.DataFrame, n_bootstrap: int = 2000, seed: int = 42) -> dict[str, Any]:
    if trades.empty:
        return {"n": 0, "probability_positive_return": 0.0, "win_rate_ci_95": [0.0, 0.0], "return_ci_95": [0.0, 0.0]}
    returns = trades["return_pct"].astype(float).to_numpy()
    rng = np.random.default_rng(seed)
    samples = rng.choice(returns, size=(n_bootstrap, len(returns)), replace=True)
    total_returns = np.prod(1.0 + samples, axis=1) - 1.0
    win_rates = (samples > 0).mean(axis=1)
    return {
        "n": int(len(returns)),
        "probability_positive_return": float((total_returns > 0).mean()),
        "return_ci_95": [float(np.quantile(total_returns, 0.025)), float(np.quantile(total_returns, 0.975))],
        "win_rate_ci_95": [float(np.quantile(win_rates, 0.025)), float(np.quantile(win_rates, 0.975))],
        "median_return": float(np.median(total_returns)),
        "p05_return": float(np.quantile(total_returns, 0.05)),
    }


def monte_carlo_ruin(trades: pd.DataFrame, initial_capital: float, n_paths: int = 2000, ruin_fraction: float = 0.5, seed: int = 42) -> dict[str, Any]:
    if trades.empty:
        return {"n_paths": 0, "probability_of_ruin": 0.0, "probability_positive": 0.0}
    returns = trades["return_pct"].astype(float).to_numpy()
    rng = np.random.default_rng(seed)
    samples = rng.choice(returns, size=(n_paths, len(returns)), replace=True)
    paths = initial_capital * np.cumprod(1.0 + samples, axis=1)
    terminal = paths[:, -1]
    ruin = (paths.min(axis=1) <= initial_capital * ruin_fraction)
    return {
        "n_paths": int(n_paths), "ruin_fraction": ruin_fraction,
        "probability_of_ruin": float(ruin.mean()),
        "probability_positive": float((terminal > initial_capital).mean()),
        "terminal_p05": float(np.quantile(terminal, 0.05)),
        "terminal_median": float(np.median(terminal)),
        "terminal_p95": float(np.quantile(terminal, 0.95)),
    }


def stress_matrix(
    universe: dict[str, pd.DataFrame],
    strategy: StrategyConfig,
    cost_profiles: dict[str, CostModel],
    initial_capital: float,
    risk_per_trade: float,
    seed: int = 42,
) -> pd.DataFrame:
    rows = []
    base = evaluate_strategy(universe, strategy, cost_profiles["normal"], initial_capital, risk_per_trade)
    base_trades = base["trades"]
    rows.append({"stress": "normal", **base["metrics"]})
    for name, costs in cost_profiles.items():
        if name == "normal":
            continue
        result = evaluate_strategy(universe, strategy, costs, initial_capital, risk_per_trade)
        rows.append({"stress": name, **result["metrics"]})
    for noise in (0.001, 0.0025, 0.005):
        if base_trades.empty:
            rows.append({"stress": f"trade_return_noise_{noise:.4f}", **{k: 0 for k in ["trades", "win_rate", "profit_factor", "net_profit", "expectancy", "max_drawdown"]}})
            continue
        noisy = base_trades.copy()
        rng = np.random.default_rng(seed)
        noisy["pnl"] = noisy["pnl"] + rng.normal(0, noise, len(noisy)) * noisy["entry_price"] * noisy["quantity"]
        noisy["return_pct"] = noisy["pnl"] / noisy["equity_after"].shift(1).fillna(initial_capital)
        rows.append({"stress": f"trade_return_noise_{noise:.4f}", **_quick_metrics(noisy, initial_capital)})
    return pd.DataFrame(rows)


def _quick_metrics(trades: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    ordered = trades.sort_values("exit_timestamp").reset_index(drop=True)
    curve = pd.DataFrame({"timestamp": ordered["exit_timestamp"], "equity": initial_capital + ordered["pnl"].cumsum()})
    return compute_metrics(ordered, curve, initial_capital)


def deflated_sharpe_proxy(trials: pd.DataFrame, observed_sharpe: float) -> float:
    """Conservative proxy: reports a rank-adjusted Sharpe, not the full Bailey-López de Prado DSR."""
    if trials.empty or "sharpe" not in trials:
        return 0.0
    values = pd.to_numeric(trials["sharpe"], errors="coerce").dropna()
    if values.empty:
        return 0.0
    return float((values <= observed_sharpe).mean())
