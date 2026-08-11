from __future__ import annotations

from pathlib import Path
import pandas as pd

from crypto_research.paper_gate import evaluate_gate, save_gate
from crypto_research.utils.config import load_config

root = Path(__file__).resolve().parent
cfg = load_config(root / "configs/config.yaml")
# The 50-symbol run used 4h data; its output files are the current run artifacts.
walk_forward = pd.read_csv(root / "results/walk_forward.csv")
stress = pd.read_csv(root / "results/stress_tests.csv")
coin = pd.read_csv(root / "results/coin_performance_oos.csv")
metrics = {
    "trades": int(coin["trades"].sum()),
    "profit_factor": float(coin["gross_profit"].sum() / max(-coin["gross_loss"].sum(), 1e-12)),
    "expectancy": float((coin["pnl"] if "pnl" in coin else coin["expectancy"] * coin["trades"]).sum() / max(coin["trades"].sum(), 1)),
    "max_drawdown": float(walk_forward["test_max_drawdown"].min()),
}
# Use the actual OOS aggregate and the actual stress row from the final report inputs.
oos = pd.read_csv(root / "results/experiments.csv")
test = oos[oos["split"] == "test"].sort_values("window")
if not test.empty:
    metrics["trades"] = int(test.iloc[-1]["trades"])
    metrics["profit_factor"] = float(test.iloc[-1]["profit_factor"])
    metrics["win_rate"] = float(test.iloc[-1]["win_rate"])
    metrics["expectancy"] = float(test.iloc[-1]["expectancy"])
    metrics["max_drawdown"] = float(test.iloc[-1]["max_drawdown"])
stress_row = stress.loc[stress["stress"] == "stress"].iloc[0].to_dict()
decision = evaluate_gate(metrics, cfg, stress_row, walk_forward)
save_gate(decision, root / "results/paper_gate.json")
print(decision.to_dict())
