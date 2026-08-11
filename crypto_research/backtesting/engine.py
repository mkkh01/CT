from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from crypto_research.backtesting.costs import CostModel
from crypto_research.strategies.candidates import StrategyConfig, strategy_entry


@dataclass
class BacktestResult:
    symbol: str
    strategy: StrategyConfig
    costs: CostModel
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    metrics: dict[str, Any]


def run_backtest(
    frame: pd.DataFrame,
    strategy: StrategyConfig,
    costs: CostModel,
    initial_capital: float = 10_000.0,
    risk_per_trade: float = 0.005,
    symbol: str | None = None,
    same_bar_policy: str = "conservative_stop_first",
) -> BacktestResult:
    df = frame.sort_values("timestamp").reset_index(drop=True).copy()
    if df.empty:
        return BacktestResult(symbol or "UNKNOWN", strategy, costs, pd.DataFrame(), pd.DataFrame(), empty_metrics(initial_capital))

    trades: list[dict[str, Any]] = []
    equity = float(initial_capital)
    curve: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    last_exit_i = -1

    for i in range(1, len(df)):
        bar = df.iloc[i]
        prev = df.iloc[i - 1]
        exited_this_bar = False

        if position is not None:
            exit_raw, reason = _exit_decision(position, bar, i, same_bar_policy)
            if exit_raw is not None:
                exit_exec = costs.sell_price(exit_raw)
                exit_notional = exit_exec * position["quantity"]
                exit_fee = costs.fee(exit_notional)
                pnl = (exit_exec - position["entry_exec"]) * position["quantity"] - position["entry_fee"] - exit_fee
                equity_before = position["equity_before"]
                equity += pnl
                trade = {
                    "symbol": position["symbol"], "strategy": strategy.name,
                    "score_threshold": strategy.score_threshold,
                    "entry_timestamp": position["entry_timestamp"], "exit_timestamp": bar["timestamp"],
                    "entry_raw": position["entry_raw"], "entry_price": position["entry_exec"],
                    "exit_raw": exit_raw, "exit_price": exit_exec,
                    "stop_raw": position["stop_raw"], "target_raw": position["target_raw"],
                    "quantity": position["quantity"], "entry_fee": position["entry_fee"], "exit_fee": exit_fee,
                    "slippage_bps": costs.slippage_bps, "spread_bps": costs.spread_bps, "fee_bps": costs.fee_bps,
                    "pnl": pnl, "return_pct": pnl / max(equity_before, 1e-12),
                    "risk_r": pnl / max(position["risk_amount"], 1e-12),
                    "bars_held": i - position["entry_i"], "exit_reason": reason,
                    "entry_score": position["entry_score"], "equity_after": equity,
                }
                trades.append(trade)
                position = None
                last_exit_i = i
                exited_this_bar = True

        if position is None and not exited_this_bar and i > last_exit_i and strategy_entry(strategy.name, prev, strategy.score_threshold):
            position = _open_position(df, i, prev, strategy, costs, equity, risk_per_trade, symbol or str(bar.get("symbol", "UNKNOWN")))

        mark = equity
        if position is not None:
            mark = equity + (float(bar["close"]) - position["entry_exec"]) * position["quantity"] - position["entry_fee"]
        curve.append({"timestamp": bar["timestamp"], "equity": mark, "realized_equity": equity, "in_position": position is not None})

    if position is not None:
        bar = df.iloc[-1]
        exit_raw = float(bar["close"])
        exit_exec = costs.sell_price(exit_raw)
        exit_fee = costs.fee(exit_exec * position["quantity"])
        pnl = (exit_exec - position["entry_exec"]) * position["quantity"] - position["entry_fee"] - exit_fee
        equity_before = position["equity_before"]
        equity += pnl
        trades.append({
            "symbol": position["symbol"], "strategy": strategy.name,
            "score_threshold": strategy.score_threshold,
            "entry_timestamp": position["entry_timestamp"], "exit_timestamp": bar["timestamp"],
            "entry_raw": position["entry_raw"], "entry_price": position["entry_exec"],
            "exit_raw": exit_raw, "exit_price": exit_exec,
            "stop_raw": position["stop_raw"], "target_raw": position["target_raw"],
            "quantity": position["quantity"], "entry_fee": position["entry_fee"], "exit_fee": exit_fee,
            "slippage_bps": costs.slippage_bps, "spread_bps": costs.spread_bps, "fee_bps": costs.fee_bps,
            "pnl": pnl, "return_pct": pnl / max(equity_before, 1e-12),
            "risk_r": pnl / max(position["risk_amount"], 1e-12),
            "bars_held": len(df) - 1 - position["entry_i"], "exit_reason": "end_of_data",
            "entry_score": position["entry_score"], "equity_after": equity,
        })
        if curve:
            curve[-1]["equity"] = equity
            curve[-1]["realized_equity"] = equity
            curve[-1]["in_position"] = False

    trades_df = pd.DataFrame(trades)
    curve_df = pd.DataFrame(curve)
    metrics = compute_metrics(trades_df, curve_df, initial_capital)
    return BacktestResult(symbol or "UNKNOWN", strategy, costs, trades_df, curve_df, metrics)


def _open_position(df: pd.DataFrame, i: int, signal_bar: pd.Series, strategy: StrategyConfig, costs: CostModel, equity: float, risk_per_trade: float, symbol: str) -> dict[str, Any] | None:
    raw_entry = float(df.iloc[i]["open"])
    if not np.isfinite(raw_entry) or raw_entry <= 0:
        return None
    entry_exec = costs.buy_price(raw_entry)
    atr = float(signal_bar.get("atr", np.nan))
    swing_low = float(signal_bar.get("swing_low", np.nan))
    if not np.isfinite(atr) or atr <= 0:
        return None
    stop_raw = swing_low - strategy.swing_buffer_atr * atr if np.isfinite(swing_low) else raw_entry - strategy.atr_stop_multiplier * atr
    if stop_raw >= raw_entry:
        stop_raw = raw_entry - strategy.atr_stop_multiplier * atr
    risk_per_unit = entry_exec - stop_raw
    if risk_per_unit <= 0:
        return None
    risk_amount = max(equity, 0.0) * risk_per_trade
    quantity = min(risk_amount / risk_per_unit, max(equity / entry_exec, 0.0))
    if quantity <= 0:
        return None
    target_raw = raw_entry + strategy.take_profit_r * (raw_entry - stop_raw)
    entry_fee = costs.fee(entry_exec * quantity)
    return {
        "symbol": symbol, "entry_i": i, "entry_timestamp": df.iloc[i]["timestamp"],
        "entry_raw": raw_entry, "entry_exec": entry_exec, "stop_raw": stop_raw,
        "target_raw": target_raw, "quantity": quantity, "entry_fee": entry_fee,
        "risk_amount": max(risk_per_unit * quantity, 1e-12), "equity_before": equity,
        "max_bars_in_trade": strategy.max_bars_in_trade,
        "entry_score": float(signal_bar.get("score", np.nan)),
    }


def _exit_decision(position: dict[str, Any], bar: pd.Series, i: int, policy: str) -> tuple[float | None, str | None]:
    low, high = float(bar["low"]), float(bar["high"])
    stop, target = position["stop_raw"], position["target_raw"]
    stop_hit, target_hit = low <= stop, high >= target
    if stop_hit and target_hit:
        if policy == "conservative_stop_first":
            return stop, "stop_and_target_same_bar_stop_first"
        return stop, "stop_and_target_same_bar"
    if stop_hit:
        return stop, "stop_loss"
    if target_hit:
        return target, "take_profit"
    if i - position["entry_i"] >= position.get("max_bars_in_trade", 10**9):
        return float(bar["close"]), "time_exit"
    return None, None


def compute_metrics(trades: pd.DataFrame, curve: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    if trades.empty:
        return empty_metrics(initial_capital)
    pnl = trades["pnl"].astype(float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    gross_profit, gross_loss = float(wins.sum()), float(-losses.sum())
    returns = trades["return_pct"].astype(float)
    equity = curve["equity"].astype(float) if not curve.empty else pd.Series([initial_capital])
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    expectancy = float(pnl.mean())
    sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(len(returns))) if len(returns) > 1 and returns.std(ddof=1) > 0 else 0.0
    downside = returns[returns < 0].std(ddof=1) if len(returns[returns < 0]) > 1 else 0.0
    sortino = float(returns.mean() / downside * np.sqrt(len(returns))) if downside > 0 else 0.0
    net_profit = float(pnl.sum())
    calmar = float(net_profit / max(abs(max_dd * initial_capital), 1e-12)) if max_dd < 0 else 0.0
    return {
        "trades": int(len(trades)), "winning_trades": int(len(wins)), "losing_trades": int(len(losses)),
        "win_rate": float(len(wins) / len(trades)), "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        "gross_profit": gross_profit, "gross_loss": gross_loss, "net_profit": net_profit,
        "average_trade": expectancy, "expectancy": expectancy, "average_win": avg_win, "average_loss": avg_loss,
        "max_drawdown": max_dd, "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "recovery_factor": float(net_profit / max(abs(max_dd * initial_capital), 1e-12)),
        "final_equity": float(equity.iloc[-1]) if len(equity) else initial_capital,
        "worst_trade": float(pnl.min()), "best_trade": float(pnl.max()),
    }


def empty_metrics(initial_capital: float) -> dict[str, Any]:
    return {"trades": 0, "winning_trades": 0, "losing_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "gross_profit": 0.0, "gross_loss": 0.0, "net_profit": 0.0, "average_trade": 0.0,
            "expectancy": 0.0, "average_win": 0.0, "average_loss": 0.0, "max_drawdown": 0.0,
            "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0, "recovery_factor": 0.0,
            "final_equity": initial_capital, "worst_trade": 0.0, "best_trade": 0.0}
