from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import json


@dataclass(frozen=True)
class GateDecision:
    status: str
    paper_trading_allowed: bool
    live_trading_allowed: bool
    reasons: list[str]
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_gate(metrics: dict[str, Any], cfg: dict[str, Any], stress: dict[str, Any] | None = None, walk_forward: Any | None = None) -> GateDecision:
    research = cfg.get("research", {})
    reasons: list[str] = []
    if int(metrics.get("trades", 0)) < int(research.get("min_oos_trades", 30)):
        reasons.append("OOS trade count below minimum")
    if float(metrics.get("profit_factor", 0.0)) < float(research.get("min_oos_profit_factor", 1.10)):
        reasons.append("OOS profit factor below minimum")
    if float(metrics.get("win_rate", 0.0)) < float(research.get("min_oos_win_rate", 0.75)):
        reasons.append("OOS win rate below configured target")
    if float(metrics.get("expectancy", 0.0)) <= float(research.get("min_oos_expectancy", 0.0)):
        reasons.append("OOS expectancy is not positive")
    if float(metrics.get("max_drawdown", 0.0)) < float(research.get("max_oos_drawdown", -0.30)):
        reasons.append("OOS drawdown exceeds configured limit")
    if stress and stress.get("profit_factor", 0.0) < 1.0:
        reasons.append("stress result is not profitable")
    if walk_forward is not None and len(walk_forward) > 0:
        wfa = walk_forward
        positive_share = float((wfa["test_expectancy"] > 0).mean())
        median_pf = float(wfa["test_profit_factor"].replace(float("inf"), float("nan")).median())
        if positive_share < 0.60:
            reasons.append("Walk-Forward positive-expectancy share below 60%")
        if median_pf < 1.0:
            reasons.append("Walk-Forward median profit factor below 1.0")
    paper_allowed = len(reasons) == 0
    return GateDecision(
        status="PAPER_READY" if paper_allowed else "FAILED_NO_ROBUST_EDGE",
        paper_trading_allowed=paper_allowed,
        live_trading_allowed=False,
        reasons=reasons or ["All configured OOS checks passed; continue Paper Trading only."],
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


def save_gate(decision: GateDecision, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
