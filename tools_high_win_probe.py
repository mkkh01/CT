from __future__ import annotations

from pathlib import Path
import pandas as pd

from crypto_research.backtesting.costs import CostModel
from crypto_research.data.binance import cache_path
from crypto_research.strategies.candidates import StrategyConfig, add_scores
from crypto_research.strategies.indicators import add_indicators
from crypto_research.validation.evaluator import evaluate_strategy
from crypto_research.utils.config import load_config

root = Path(__file__).resolve().parent
cfg = load_config(root / "configs/config.yaml")
cache = Path(cfg["data"]["cache_dir"])
universe = {}
for symbol in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]:
    files = sorted(cache.glob(f"{symbol}_4h_*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
    universe[symbol] = add_scores(add_indicators(pd.read_parquet(files[0])))
# Use an older development window only; this is a probe, not final OOS selection.
end = pd.Timestamp("2025-11-30", tz="UTC")
start = end - pd.Timedelta(days=365)
development = {s: f[(f["timestamp"] >= start) & (f["timestamp"] < end)].reset_index(drop=True) for s, f in universe.items()}
rows = []
costs = CostModel(**cfg["costs"]["normal"])
for name in ["bollinger_reversion", "mean_reversion_reclaim", "trend_pullback"]:
    for threshold in [35, 55]:
        for stop_mult in [1.0]:
            for tp in [0.25, 0.50]:
                for breakeven in [0.0, 0.25, 0.50]:
                    for stop_method in ["atr"]:
                        strategy = StrategyConfig(name, threshold, stop_mult, tp, 0.2, stop_method, 96, breakeven)
                        result = evaluate_strategy(development, strategy, costs, 10000.0, 0.005)
                    m = result["metrics"]
                    if m["trades"] >= 20:
                        rows.append({"name": name, "threshold": threshold, "stop_mult": stop_mult, "tp_r": tp, "stop_method": stop_method, **m})
frame = pd.DataFrame(rows)
if frame.empty:
    print("NO_CANDIDATE_WITH_MIN_TRADES")
else:
    print("TOP_BY_WIN_RATE_AND_POSITIVE_EXPECTANCY")
    selected = frame[frame["expectancy"] > 0].sort_values(["win_rate", "profit_factor", "trades"], ascending=[False, False, False])
    print(selected.head(20).to_string(index=False))
    print("TOP_BY_EXPECTANCY")
    print(frame.sort_values(["expectancy", "profit_factor"], ascending=False).head(20).to_string(index=False))
    frame.to_csv(root / "results/high_win_probe.csv", index=False)
