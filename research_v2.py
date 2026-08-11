#!/usr/bin/env python3
"""Bounded, pre-registered candidate search for the v2 strategy.

Selection uses only Development and Validation. OOS rows are produced after a
single frozen candidate is chosen and are never used for selection.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from run_backtest import (
    BASE_COSTS,
    STRESS_COSTS,
    StrategyConfig,
    download_klines,
    prepare_signal_context,
    run_backtest,
    slice_period,
    utc_timestamp,
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START = utc_timestamp("2022-01-01")
END = utc_timestamp("2026-08-01")
SPLITS = {
    "development": ("2022-01-01", "2024-06-30 23:00:00"),
    "validation": ("2024-07-01", "2025-03-31 23:00:00"),
    "oos": ("2025-04-01", "2026-07-31 23:00:00"),
}


def candidates() -> list[StrategyConfig]:
    """12 economically motivated candidates fixed before reading v2 results."""
    specs = [
        ("baseline", "none", 12, 0.0, 2.0, 48),
        ("ema_s12", "ema", 12, 0.0, 2.0, 48),
        ("ema_s24", "ema", 24, 0.0, 2.0, 48),
        ("ema_v12", "ema", 12, 1.2, 2.0, 48),
        ("ema_v24", "ema", 24, 1.2, 2.0, 48),
        ("ema_r15_s12", "ema", 12, 0.0, 1.5, 24),
        ("ema_r25_s12", "ema", 12, 0.0, 2.5, 48),
        ("ema_r15_s24", "ema", 24, 0.0, 1.5, 24),
        ("ema_r25_s24", "ema", 24, 0.0, 2.5, 48),
        ("ema_v12_r15", "ema", 12, 1.2, 1.5, 24),
        ("ema_v12_r25", "ema", 12, 1.2, 2.5, 48),
        ("ema_v24_r25", "ema", 24, 1.2, 2.5, 48),
    ]
    return [
        StrategyConfig(
            name=name,
            sweep_window=window,
            volume_multiplier=volume,
            trend_filter=trend,
            cisd_atr_multiplier=1.0,
            target_r=target,
            max_bars_in_trade=max_bars,
            stop_atr_multiplier=0.25,
        )
        for name, trend, window, volume, target, max_bars in specs
    ]


def load_data(data_dir: Path) -> dict[str, pd.DataFrame]:
    return {symbol: download_klines(symbol, START, END, data_dir, force=False) for symbol in SYMBOLS}


def run_candidates(data: dict[str, pd.DataFrame], output_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    periods: dict[tuple[str, str], tuple[pd.DataFrame, Any]] = {}
    for symbol, df in data.items():
        for split_name, (split_start, split_end) in SPLITS.items():
            period = slice_period(df, split_start, split_end)
            if len(period) >= 250:
                periods[(symbol, split_name)] = (period, prepare_signal_context(period))
    for config in candidates():
        for (symbol, split_name), (period, context) in periods.items():
            for scenario, costs in (("base", BASE_COSTS), ("stress", STRESS_COSTS)):
                    result = run_backtest(period, 10_000.0, 0.01, costs, config, context)
                    row = {
                        "candidate": config.name,
                        "symbol": symbol,
                        "split": split_name,
                        "scenario": scenario,
                        **asdict(config),
                        **result.metrics,
                    }
                    rows.append(row)
        print(f"completed {config.name}")
    frame = pd.DataFrame(rows)
    frame.to_csv(output_dir / "candidate_results.csv", index=False)
    return frame


def selection_table(frame: pd.DataFrame) -> pd.DataFrame:
    train = frame[frame["split"].isin(["development", "validation"])].copy()
    grouped = train.groupby("candidate", as_index=False).agg(
        dev_base_return=("net_return", lambda s: 0.0),
    )
    records: list[dict[str, Any]] = []
    for candidate, group in train.groupby("candidate"):
        base = group[group["scenario"] == "base"]
        stress = group[group["scenario"] == "stress"]
        dev_base = base[base["split"] == "development"]
        val_base = base[base["split"] == "validation"]
        dev_stress = stress[stress["split"] == "development"]
        val_stress = stress[stress["split"] == "validation"]
        dev_val_base_return = float(base["net_return"].mean())
        dev_val_stress_return = float(stress["net_return"].mean())
        val_pf = float(val_base["profit_factor"].replace([float("inf")], pd.NA).dropna().median()) if not val_base.empty else 0.0
        val_dd = float(val_base["max_drawdown"].median()) if not val_base.empty else -1.0
        val_win = float(val_base["win_rate"].mean()) if not val_base.empty else 0.0
        # Pre-declared score: reward net return and pressure resilience, penalize drawdown.
        score = dev_val_base_return + 0.50 * dev_val_stress_return + 0.20 * val_dd
        records.append(
            {
                "candidate": candidate,
                "dev_base_return_mean": float(dev_base["net_return"].mean()),
                "validation_base_return_mean": float(val_base["net_return"].mean()),
                "dev_validation_base_return_mean": dev_val_base_return,
                "dev_validation_stress_return_mean": dev_val_stress_return,
                "validation_pf_median": val_pf,
                "validation_drawdown_median": val_dd,
                "validation_win_rate_mean": val_win,
                "score": score,
                "symbols_positive_validation": int((val_base.groupby("symbol")["net_return"].mean() > 0).sum()),
            }
        )
    return pd.DataFrame(records).sort_values(["score", "validation_base_return_mean"], ascending=False)


def write_report(raw: pd.DataFrame, ranking: pd.DataFrame, selected: str, output_dir: Path) -> None:
    selected_oos = raw[(raw["candidate"] == selected) & (raw["split"] == "oos")]
    table = selected_oos[["candidate", "symbol", "scenario", "net_return", "buy_hold_return", "max_drawdown", "trades", "win_rate", "profit_factor", "expectancy_usdt"]].copy()
    for col in ("net_return", "buy_hold_return", "max_drawdown", "win_rate"):
        table[col] = table[col].map(lambda x: f"{100*x:.2f}%")
    report = f"""# دورة التحسين v2

> هذه الدراسة تستخدم بحثاً محدوداً مسبق التسجيل، ولا تستهدف نسبة فوز 70% على حساب الصدق الإحصائي.

## المنهج

جرت مقارنة 12 مرشحاً محدداً قبل قراءة نتائج v2. شملت التغييرات فلتر EMA، نافذة Sweep، شرط حجم نسبي، هدف R، ومدة الاحتفاظ. استُخدمت Development وValidation فقط للاختيار. بعد التجميد، حُسبت نتيجة OOS للمرشح `{selected}` دون إعادة اختيار.

يستخدم كل تشغيل رسوم الأساس `{BASE_COSTS.fill_bps:.0f}` نقطة أساس لكل جهة تقريباً، وتكاليف الضغط `{STRESS_COSTS.fill_bps:.0f}` نقطة أساس لكل جهة تقريباً، مع تنفيذ في الشمعة التالية وسياسة وقف أولاً عند تعارض الهدف والوقف.

## نتيجة الاختيار

```text
{ranking.head(10).to_string(index=False)}
```

## OOS للمرشح المجمد

{table.to_markdown(index=False)}

## معيار القرار

نسبة الفوز ليست معياراً مستقلاً؛ يلزم عائد صافٍ موجب، Profit Factor أعلى من 1.15 في الأساس وأعلى من 1.05 تحت الضغط، هبوط مقبول، وثبات بين الرموز والنوافذ. إذا لم تتحقق هذه الشروط، فالقرار هو `NO ROBUST EDGE FOUND` حتى لو تجاوزت نسبة الفوز 70% في جزء من التاريخ.

## مراجع

[1]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints "Binance Spot API: market-data endpoints"
[2]: https://data.binance.vision/ "Binance public market-data archive"
"""
    (output_dir / "research_v2_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    data_dir = Path("data")
    output_dir = Path("results/v2")
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_file = output_dir / "candidate_results.csv"
    if candidate_file.exists():
        raw = pd.read_csv(candidate_file)
    else:
        data = load_data(data_dir)
        raw = run_candidates(data, output_dir)
    ranking = selection_table(raw)
    ranking.to_csv(output_dir / "candidate_ranking.csv", index=False)
    selected = str(ranking.iloc[0]["candidate"])
    selected_oos = raw[(raw["candidate"] == selected) & (raw["split"] == "oos")].copy()
    selected_oos.to_csv(output_dir / "frozen_oos.csv", index=False)
    (output_dir / "selection.json").write_text(json.dumps({"selected_candidate": selected, "candidate_count": len(candidates()), "selection_data": ["development", "validation"], "oos_frozen": True}, indent=2), encoding="utf-8")
    write_report(raw, ranking, selected, output_dir)
    print(f"selected={selected}")
    print(ranking.head(5).to_string(index=False))
    print(selected_oos[["symbol", "scenario", "net_return", "profit_factor", "max_drawdown", "trades"]].to_string(index=False))


if __name__ == "__main__":
    main()
