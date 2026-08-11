#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research_v2 import END, START, SYMBOLS, candidates
from run_backtest import CostModel, download_klines, run_backtest, slice_period

COSTS = {
    "low": CostModel(5.0, 1.0, 1.0),
    "base": CostModel(10.0, 2.0, 2.0),
    "high": CostModel(15.0, 5.0, 4.0),
    "stress": CostModel(20.0, 8.0, 6.0),
}


def main() -> None:
    root = Path("results/v2")
    selected = json.loads((root / "selection.json").read_text(encoding="utf-8"))["selected_candidate"]
    config = next(c for c in candidates() if c.name == selected)
    rows = []
    for symbol in SYMBOLS:
        df = download_klines(symbol, START, END, Path("data"), force=False)
        period = slice_period(df, "2025-04-01", "2026-07-31 23:00:00")
        for scenario, costs in COSTS.items():
            result = run_backtest(period, 10_000.0, 0.01, costs, config)
            rows.append({"candidate": selected, "symbol": symbol, "scenario": scenario, "fill_bps": costs.fill_bps, **result.metrics})
    frame = pd.DataFrame(rows)
    frame.to_csv(root / "cost_sensitivity.csv", index=False)
    print(frame[["symbol", "scenario", "fill_bps", "net_return", "profit_factor", "max_drawdown", "trades", "win_rate"]].to_string(index=False))


if __name__ == "__main__":
    main()
