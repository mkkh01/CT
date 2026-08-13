from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.ifvg_strategy import evaluate_ifvg_signal_diagnostics  # noqa: E402

BASE = "https://data-api.binance.vision/api/v3"


def fetch(symbol: str, interval: str, limit: int = 1000) -> list[dict]:
    response = requests.get(f"{BASE}/klines", params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=20)
    response.raise_for_status()
    now_ms = int(time.time() * 1000)
    rows = []
    for row in response.json():
        if int(row[6]) >= now_ms:
            continue
        rows.append({"open_time": int(row[0]), "close_time": int(row[6]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(row[5])})
    return rows


def run_symbol(symbol: str) -> dict:
    execution = fetch(symbol, "15m")
    higher = fetch(symbol, "4h")
    higher_by_time = {c["open_time"]: c for c in higher}
    trades: list[dict] = []
    used_candles: set[int] = set()
    for i in range(60, len(execution) - 2):
        current = execution[i]
        available_higher = [c for t, c in sorted(higher_by_time.items()) if t <= current["open_time"]]
        signal, diagnostics = evaluate_ifvg_signal_diagnostics(symbol, execution[: i + 1], available_higher)
        if not signal or signal.candle_open_time in used_candles:
            continue
        used_candles.add(signal.candle_open_time)
        exit_price = None
        outcome = "OPEN_AT_SAMPLE_END"
        exit_time = None
        for future in execution[i + 1 :]:
            if signal.side == "BUY":
                if future["low"] <= signal.stop_loss:
                    exit_price, outcome = signal.stop_loss, "STOP_LOSS"
                elif future["high"] >= signal.take_profit:
                    exit_price, outcome = signal.take_profit, "TAKE_PROFIT"
            else:
                if future["high"] >= signal.stop_loss:
                    exit_price, outcome = signal.stop_loss, "STOP_LOSS"
                elif future["low"] <= signal.take_profit:
                    exit_price, outcome = signal.take_profit, "TAKE_PROFIT"
            if exit_price is not None:
                exit_time = future["open_time"]
                break
        if exit_price is None:
            continue
        gross = (exit_price - signal.entry_price) if signal.side == "BUY" else (signal.entry_price - exit_price)
        notional = signal.entry_price + exit_price
        fee = notional * 0.001
        slippage = signal.entry_price * 0.0005 + exit_price * 0.0005
        net = gross - fee - slippage
        risk_distance = abs(signal.entry_price - signal.stop_loss)
        trades.append({"symbol": symbol, "side": signal.side, "signal_time": signal.candle_open_time, "exit_time": exit_time, "outcome": outcome, "entry": signal.entry_price, "exit": exit_price, "risk_reward": signal.risk_reward, "net_per_unit": net, "net_return_pct": (net / signal.entry_price) * 100 if signal.entry_price else 0.0, "r_multiple_after_costs": net / risk_distance if risk_distance else 0.0})
    wins = [t for t in trades if t["net_per_unit"] > 0]
    losses = [t for t in trades if t["net_per_unit"] <= 0]
    return {"symbol": symbol, "execution_candles": len(execution), "higher_candles": len(higher), "closed_trades": len(trades), "wins": len(wins), "losses": len(losses), "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else 0.0, "net_return_pct_sum": round(sum(t["net_return_pct"] for t in trades), 6), "r_multiple_after_costs_sum": round(sum(t["r_multiple_after_costs"] for t in trades), 6), "trades": trades}


if __name__ == "__main__":
    symbols = sys.argv[1:] or ["BTCUSDT", "ETHUSDT"]
    results = {symbol: run_symbol(symbol) for symbol in symbols}
    output = {"generated_at": datetime.now(timezone.utc).isoformat(), "source": BASE, "method": "IFVG v1, closed candles only, sample window limited to latest public klines", "results": results}
    path = ROOT / "docs" / "backtest_ifvg_sample_2026-08-13.json"
    path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({symbol: {k: v for k, v in result.items() if k != "trades"} for symbol, result in results.items()}, indent=2))
