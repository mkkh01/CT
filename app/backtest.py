from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .analysis import AnalysisEngine
from .config import Settings
from .models import Candle, Signal


@dataclass
class BacktestTrade:
    symbol: str
    timeframe: str
    direction: str
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    entry_time: int | None
    exit_time: int | None
    outcome: str
    pnl_r: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _event_for_candle(signal: Signal, candle: Candle) -> tuple[str, float] | None:
    if signal.direction == "BUY":
        hit_sl = candle.low <= signal.stop_loss
        hit_tp1 = candle.high >= signal.tp1
    else:
        hit_sl = candle.high >= signal.stop_loss
        hit_tp1 = candle.low <= signal.tp1
    if hit_sl and hit_tp1:
        return "SL_HIT", -1.0
    if hit_sl:
        return "SL_HIT", -1.0
    if hit_tp1:
        return "TP1_HIT", signal.risk_reward["tp1"]
    return None


def run_backtest(candles: list[Candle], settings: Settings) -> dict[str, Any]:
    if len(candles) < max(50, settings.atr_period + settings.swing_left + settings.swing_right + 5):
        return {"status": "INSUFFICIENT_HISTORY", "total_signals": 0, "trades": []}
    engine = AnalysisEngine(settings)
    trades: list[BacktestTrade] = []
    total_signals = 0
    for index in range(50, len(candles) - 1):
        history = candles[:index + 1]
        _, result = engine.analyze(candles[index].symbol, candles[index].timeframe, history, history, history, data_fresh=True)
        if not isinstance(result, Signal):
            continue
        total_signals += 1
        outcome = "EXPIRED"
        pnl_r = 0.0
        exit_time: int | None = None
        activated_at: int | None = None
        for pending_index, future in enumerate(candles[index + 1:], start=1):
            if activated_at is None:
                reached_entry = future.low <= result.entry <= future.high
                if reached_entry:
                    activated_at = future.open_time
                elif pending_index >= settings.max_pending_candles:
                    break
                else:
                    continue
            event = _event_for_candle(result, future)
            if event:
                outcome, pnl_r = event
                exit_time = future.close_time
                break
            if pending_index >= settings.max_pending_candles and activated_at is None:
                break
        if activated_at is not None and outcome == "EXPIRED":
            outcome = "OPEN"
        trades.append(BacktestTrade(result.symbol, result.timeframe, result.direction, result.entry, result.stop_loss, result.tp1, result.tp2, activated_at, exit_time, outcome, pnl_r))
    activated = sum(item.entry_time is not None for item in trades)
    tp1_hits = sum(item.outcome == "TP1_HIT" for item in trades)
    tp2_hits = sum(item.outcome == "TP2_HIT" for item in trades)
    sl_hits = sum(item.outcome == "SL_HIT" for item in trades)
    wins = sum(item.pnl_r > 0 for item in trades)
    losses = sum(item.pnl_r < 0 for item in trades)
    total_r = sum(item.pnl_r for item in trades)
    gross_profit = sum(item.pnl_r for item in trades if item.pnl_r > 0)
    gross_loss = abs(sum(item.pnl_r for item in trades if item.pnl_r < 0))
    equity = peak = max_drawdown = 0.0
    losing_streak = winning_streak = longest_losing = longest_winning = 0
    for item in trades:
        equity += item.pnl_r
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if item.pnl_r > 0:
            winning_streak += 1; losing_streak = 0
        elif item.pnl_r < 0:
            losing_streak += 1; winning_streak = 0
        else:
            winning_streak = losing_streak = 0
        longest_winning = max(longest_winning, winning_streak)
        longest_losing = max(longest_losing, losing_streak)
    return {
        "status": "OK",
        "symbol": candles[-1].symbol,
        "timeframe": candles[-1].timeframe,
        "total_signals": total_signals,
        "activated_trades": activated,
        "expired_signals": sum(item.outcome == "EXPIRED" for item in trades),
        "tp1_hits": tp1_hits,
        "tp2_hits": 0,
        "sl_hits": sl_hits,
        "win_rate": wins / activated if activated else 0.0,
        "loss_rate": losses / activated if activated else 0.0,
        "tp1_rate": tp1_hits / activated if activated else 0.0,
        "tp2_rate": 0.0,
        "average_r": total_r / activated if activated else 0.0,
        "total_r": total_r,
        "maximum_drawdown": max_drawdown,
        "profit_factor": gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0),
        "longest_losing_streak": longest_losing,
        "longest_winning_streak": longest_winning,
        "trades": [item.to_dict() for item in trades],
    }
