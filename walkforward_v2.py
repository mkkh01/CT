#!/usr/bin/env python3
"""Unseen-window test for the frozen v2 candidate."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research_v2 import END, START, SYMBOLS, candidates
from run_backtest import BASE_COSTS, STRESS_COSTS, download_klines, run_backtest, slice_period

WINDOWS = {
    "oos_1": ("2025-04-01", "2025-08-31 23:00:00"),
    "oos_2": ("2025-09-01", "2026-01-31 23:00:00"),
    "oos_3": ("2026-02-01", "2026-07-31 23:00:00"),
}


def main() -> None:
    root = Path("results/v2")
    selected_name = json.loads((root / "selection.json").read_text(encoding="utf-8"))["selected_candidate"]
    config = next(c for c in candidates() if c.name == selected_name)
    rows: list[dict] = []
    for symbol in SYMBOLS:
        df = download_klines(symbol, START, END, Path("data"), force=False)
        for window, (start, end) in WINDOWS.items():
            period = slice_period(df, start, end)
            for scenario, costs in (("base", BASE_COSTS), ("stress", STRESS_COSTS)):
                result = run_backtest(period, 10_000.0, 0.01, costs, config)
                rows.append({"candidate": selected_name, "symbol": symbol, "window": window, "scenario": scenario, **result.metrics})
    frame = pd.DataFrame(rows)
    frame.to_csv(root / "walkforward.csv", index=False)
    base = frame[frame["scenario"] == "base"]
    stress = frame[frame["scenario"] == "stress"]
    positive_windows = int((base.groupby("window")["net_return"].mean() > 0).sum())
    positive_symbols = int((base.groupby("symbol")["net_return"].mean() > 0).sum())
    report = f"""# اختبار Walk-Forward v2

المرشح المجمد: `{selected_name}`. لم تُستخدم هذه النوافذ لاختيار المرشح.

| النافذة | المتوسط الصافي أساس | متوسط PF أساس | المتوسط الصافي ضغط | متوسط PF ضغط |
|---|---:|---:|---:|---:|
"""
    for window in WINDOWS:
        b = base[base["window"] == window]
        s = stress[stress["window"] == window]
        report += f"| {window} | {b['net_return'].mean():.2%} | {b['profit_factor'].replace([float('inf')], pd.NA).dropna().mean():.2f} | {s['net_return'].mean():.2%} | {s['profit_factor'].replace([float('inf')], pd.NA).dropna().mean():.2f} |\n"
    report += f"""

عدد النوافذ ذات المتوسط الموجب في الأساس: `{positive_windows}` من `{len(WINDOWS)}`. وعدد الرموز ذات المتوسط الموجب: `{positive_symbols}` من `{len(SYMBOLS)}`. هذه النتيجة تشخيصية خارج العينة؛ لا يجوز إعادة اختيار المرشح بعدها دون اعتبار هذه النوافذ جزءاً من التطوير وإنشاء OOS جديدة.
"""
    (root / "walkforward_report.md").write_text(report, encoding="utf-8")
    print(frame[["symbol", "window", "scenario", "net_return", "profit_factor", "max_drawdown", "trades"]].to_string(index=False))
    print(f"positive_windows={positive_windows}/{len(WINDOWS)} positive_symbols={positive_symbols}/{len(SYMBOLS)}")


if __name__ == "__main__":
    main()
