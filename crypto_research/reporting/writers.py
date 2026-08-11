from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def save_json(path: str | Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_jsonable(payload), fh, ensure_ascii=False, indent=2)


def save_frame(frame: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def write_final_report(
    path: str | Path,
    metadata: dict[str, Any],
    best_strategy: dict[str, Any] | None,
    oos: dict[str, Any] | None,
    coin_table: pd.DataFrame,
    walk_forward: pd.DataFrame,
    stress: pd.DataFrame,
    monte_carlo: dict[str, Any],
    regime_table: pd.DataFrame | None = None,
    portfolio_table: pd.DataFrame | None = None,
) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Final Research Report",
        "",
        "> هذا التقرير بحث تاريخي فقط. لا يحتوي على توصية تداول ولا يثبت وجود Edge مستقبلي.",
        "",
        f"**Generated at (UTC):** {datetime.now(timezone.utc).isoformat()}",
        f"**Reference data:** {metadata.get('data_reference', 'not available')}",
        f"**Strategy version:** {metadata.get('strategy_version', 'not available')}",
        "",
    ]
    if not best_strategy or not best_strategy.get("metrics"):
        lines += ["## Conclusion", "", "`NO ROBUST EDGE FOUND`", "", "لم تتوفر نتيجة قابلة للتقييم أو لم تتجاوز شروط الحد الأدنى."]
    else:
        s = best_strategy["strategy"]
        m = best_strategy["metrics"]
        lines += ["## Best Candidate (not automatically approved)", "", "| Field | Value |", "|---|---:|"]
        for key, value in s.items():
            lines.append(f"| {key} | {value} |")
        lines += ["", "| Performance | Value |", "|---|---:|"]
        for key in ["trades", "winning_trades", "losing_trades", "win_rate", "profit_factor", "net_profit", "average_trade", "expectancy", "max_drawdown", "sharpe", "sortino", "calmar"]:
            lines.append(f"| {key} | {_fmt(m.get(key))} |")
        lines += ["", "## Out-of-Sample Locked Result", ""]
        if oos and oos.get("metrics"):
            lines += ["| Metric | Value |", "|---|---:|"]
            for key in ["trades", "win_rate", "profit_factor", "net_profit", "max_drawdown", "expectancy", "sharpe", "sortino"]:
                lines.append(f"| {key} | {_fmt(oos['metrics'].get(key))} |")
            lines += ["", "**OOS selection rule:** parameters were frozen before this final test and were not modified after viewing it."]
        else:
            lines += ["Final OOS result unavailable."]

    lines += ["", "## Coin Performance", ""]
    lines.append(_markdown_table(coin_table))
    lines += ["", "## Walk-Forward Windows", "", _markdown_table(walk_forward)]
    lines += ["", "## Stress Tests", "", _markdown_table(stress)]
    lines += ["", "## Market Regimes", "", _markdown_table(regime_table if regime_table is not None else pd.DataFrame())]
    lines += ["", "## Portfolio Position Limits", "", _markdown_table(portfolio_table if portfolio_table is not None else pd.DataFrame())]
    lines += ["", "## Monte Carlo / Bootstrap", "", "```json", json.dumps(_jsonable(monte_carlo), ensure_ascii=False, indent=2), "```"]
    lines += ["", "## Robustness Assessment", "", "الاختيار النهائي يجب أن يعتمد على ثبات النتائج بين العملات والنوافذ والأنظمة السوقية وحساسية التكاليف، وليس على Win Rate وحدها. إذا كانت النتائج تنهار مع زيادة بسيطة في التكاليف أو عند الإخراج خارج العينة، تُوسم الاستراتيجية `FRAGILE` أو `NO ROBUST EDGE FOUND`."]
    lines += ["", "## Disclosure", "", "**Basis:** Spot Long-Only، صفقات متسلسلة لكل رمز، رسوم وانزلاق وفارق سعر تقريبي على كل دخول وخروج، وتنفيذ الدخول على افتتاح الشمعة التالية بعد إشارة الإغلاق.", "", "**Time:** جميع الطوابع الزمنية UTC؛ فترة البيانات والتقسيمات مذكورة في metadata والملفات الخام.", "", "**Assumptions:** سياسة SL/TP محافظة عند تعارضهما داخل الشمعة، وحد أقصى للصفقة، ومخاطرة ثابتة على رأس المال المتاح.", "", "**Sources & Confidence:** بيانات OHLCV من Binance Spot Public API، مع احتمال وجود فجوات وتحيز Survivorship في Universe الحالي؛ لا تُعتبر الأرقام ضمانًا للمستقبل.", "", "**Compliance:** This is research and analysis only, not personalized financial advice."]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        if value == float("inf"):
            return "inf"
        return f"{value:.6f}"
    return str(value)


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        return "لا توجد بيانات كافية."
    small = frame.copy()
    cols = list(small.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in small.head(100).iterrows():
        lines.append("| " + " | ".join(_fmt(v) for v in row.tolist()) + " |")
    return "\n".join(lines)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float) and value != value:
        return None
    return value
