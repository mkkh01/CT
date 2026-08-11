from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from crypto_research.backtesting.costs import CostModel
from crypto_research.backtesting.portfolio import run_portfolio_backtest
from crypto_research.data.binance import BinanceClient, download_universe, load_or_download
from crypto_research.data.universe import add_user_symbol, discover_spot_symbols, save_universe
from crypto_research.data.validate import validate_universe
from crypto_research.reporting.writers import save_frame, save_json, write_final_report
from crypto_research.paper_gate import evaluate_gate, save_gate
from crypto_research.strategies.candidates import StrategyConfig, add_scores
from crypto_research.strategies.indicators import add_indicators
from crypto_research.utils.config import ensure_dirs, load_config, set_seed
from crypto_research.validation.evaluator import evaluate_strategy, result_row
from crypto_research.validation.optimizer import _config_from_dict, optimize_candidates
from crypto_research.validation.robustness import bootstrap_metrics, monte_carlo_ruin, stress_matrix
from crypto_research.validation.regimes import label_trades, regime_summary
from crypto_research.validation.splits import slice_window, walk_forward_windows

LOG = logging.getLogger("research")


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    if args.interval:
        cfg["data"]["interval"] = args.interval
    if args.symbols:
        cfg["data"]["symbols"] = [s.upper().replace("/", "") for s in args.symbols.split(",") if s.strip()]
    if args.add_symbol:
        seed = pd.DataFrame({"symbol": cfg["data"]["symbols"]})
        for symbol in args.add_symbol:
            seed = add_user_symbol(symbol, seed, cfg["exchange"]["base_url"], cfg["data"].get("quote_asset", "USDT"))
        cfg["data"]["symbols"] = seed["symbol"].tolist()
    if args.add_symbol or args.symbols:
        cfg["data"]["max_symbols"] = max(int(cfg["data"].get("max_symbols", 30)), len(cfg["data"]["symbols"]))
    if args.discover_universe or cfg["data"].get("discover_universe", False):
        discovered = discover_spot_symbols(
            cfg["exchange"]["base_url"], cfg["data"].get("quote_asset", "USDT"),
            int(args.max_symbols or cfg["data"].get("max_symbols", 30)), cfg["data"].get("exclude_base_assets", []),
        )
        save_universe(discovered, Path(cfg["research"]["output_dir"]) / "discovered_universe.csv")
        cfg["data"]["symbols"] = discovered["symbol"].tolist()
    ensure_dirs(cfg)
    set_seed(int(cfg["project"].get("seed", 42)))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.max_symbols:
        cfg["data"]["max_symbols"] = args.max_symbols
    force = args.force_download
    if args.no_download:
        universe = load_cached_universe(cfg)
    else:
        universe = download_universe(cfg, force=force)
    if not universe:
        raise RuntimeError("No data available. Run without --no-download to fetch Binance Spot data.")

    validation = validate_universe(universe, cfg["data"]["interval"])
    save_frame(validation, Path(cfg["research"]["output_dir"]) / "data_validation.csv")
    if not validation["passed"].all():
        bad = validation.loc[~validation["passed"]]
        raise RuntimeError(f"Data validation failed for symbols: {bad['symbol'].tolist()}")
    universe = {symbol: add_scores(add_indicators(frame)) for symbol, frame in universe.items()}

    if args.mode == "data":
        LOG.info("Data validation complete for %d symbols", len(universe))
        return

    costs = {name: CostModel(**values) for name, values in cfg["costs"].items()}
    normal_cost = costs["normal"]
    ref = max(universe.values(), key=len)
    windows = walk_forward_windows(
        ref,
        int(cfg["validation"]["train_days"]), int(cfg["validation"]["validation_days"]),
        int(cfg["validation"]["test_days"]), int(cfg["validation"]["step_days"]),
    )
    if not windows:
        raise RuntimeError("Not enough historical data for the configured Train/Validation/Test windows.")
    if args.mode == "smoke":
        windows = windows[-1:]
        max_trials = min(args.max_trials or 6, 6)
    else:
        max_trials = args.max_trials or int(cfg["research"].get("max_trials", 48))
    if args.max_windows:
        windows = windows[-int(args.max_windows):]

    def split_universe(start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
        return {sym: slice_window(frame, start, end) for sym, frame in universe.items()}

    experiment_rows: list[dict[str, Any]] = []
    wf_rows: list[dict[str, Any]] = []
    final_best: dict[str, Any] | None = None
    final_oos: dict[str, Any] | None = None
    final_oos_universe: dict[str, pd.DataFrame] = {}

    for window in windows:
        train_uni = split_universe(window.train_start, window.train_end)
        val_uni = split_universe(window.validation_start, window.validation_end)
        test_uni = split_universe(window.test_start, window.test_end)
        # Purge the latest bars of train and embargo the first bars of validation.
        purge = int(cfg["validation"].get("purge_bars", 2))
        embargo = int(cfg["validation"].get("embargo_bars", 2))
        train_uni = {s: (f.iloc[:-purge] if len(f) > purge else f.iloc[0:0]) for s, f in train_uni.items()}
        val_uni = {s: (f.iloc[embargo:] if len(f) > embargo else f.iloc[0:0]) for s, f in val_uni.items()}
        optimization = optimize_candidates(
            train_uni, val_uni, cfg, normal_cost, float(cfg["backtest"]["initial_capital"]),
            float(cfg["backtest"]["risk_per_trade"]), max_trials=max_trials,
            top_k=min(8, max_trials), seed=int(cfg["project"].get("seed", 42)) + window.window_id,
        )
        if optimization["best"] is None:
            continue
        best_config = _config_from_dict(pd.Series(optimization["best"]["strategy"]))
        train_result = evaluate_strategy(train_uni, best_config, normal_cost, float(cfg["backtest"]["initial_capital"]), float(cfg["backtest"]["risk_per_trade"]))
        val_result = evaluate_strategy(val_uni, best_config, normal_cost, float(cfg["backtest"]["initial_capital"]), float(cfg["backtest"]["risk_per_trade"]))
        test_result = evaluate_strategy(test_uni, best_config, normal_cost, float(cfg["backtest"]["initial_capital"]), float(cfg["backtest"]["risk_per_trade"]))
        experiment_rows.extend([
            {"experiment_id": experiment_id(window.window_id, "train", best_config), "window": window.window_id, "split": "train", **result_row(train_result)},
            {"experiment_id": experiment_id(window.window_id, "validation", best_config), "window": window.window_id, "split": "validation", **result_row(val_result)},
            {"experiment_id": experiment_id(window.window_id, "test", best_config), "window": window.window_id, "split": "test", **result_row(test_result)},
        ])
        wf_rows.append({"window": window.window_id, "train_start": window.train_start, "train_end": window.train_end, "validation_start": window.validation_start, "validation_end": window.validation_end, "test_start": window.test_start, "test_end": window.test_end, **{f"test_{k}": v for k, v in test_result["metrics"].items()}, **{f"strategy_{k}": v for k, v in best_config.to_dict().items()}})
        final_best = evaluate_strategy({s: pd.concat([train_uni[s], val_uni[s]]) for s in universe}, best_config, normal_cost, float(cfg["backtest"]["initial_capital"]), float(cfg["backtest"]["risk_per_trade"]))
        final_best["strategy"] = best_config.to_dict()
        final_oos = test_result
        final_oos["strategy"] = best_config.to_dict()
        final_oos_universe = test_uni

    experiments = pd.DataFrame(experiment_rows)
    walk_forward = pd.DataFrame(wf_rows)
    save_frame(experiments, Path(cfg["research"]["output_dir"]) / "experiments.csv")
    save_frame(walk_forward, Path(cfg["research"]["output_dir"]) / "walk_forward.csv")

    if final_best is None or final_oos is None:
        raise RuntimeError("No strategy candidate produced an evaluable result.")
    coin_table = pd.DataFrame(final_oos["per_coin"])
    save_frame(coin_table, Path(cfg["research"]["output_dir"]) / "coin_performance_oos.csv")
    if not final_oos["trades"].empty:
        save_frame(final_oos["trades"], Path(cfg["research"]["output_dir"]) / "trades_oos.csv")
    frozen_strategy = StrategyConfig(**final_oos["strategy"])
    stress = stress_matrix(final_oos_universe, frozen_strategy, costs, float(cfg["backtest"]["initial_capital"]), float(cfg["backtest"]["risk_per_trade"]))
    save_frame(stress, Path(cfg["research"]["output_dir"]) / "stress_tests.csv")
    normal_stress = stress.loc[stress["stress"] == "normal"].iloc[0].to_dict() if not stress.empty and (stress["stress"] == "normal").any() else None
    gate = evaluate_gate(final_oos["metrics"], cfg, normal_stress, walk_forward)
    save_gate(gate, Path(cfg["research"]["output_dir"]) / "paper_gate.json")
    regime_trades = []
    for symbol, frame in final_oos_universe.items():
        symbol_trades = final_oos["trades"].loc[final_oos["trades"]["symbol"] == symbol].copy()
        if not symbol_trades.empty:
            regime_trades.append(label_trades(symbol_trades, frame))
    regime_table = regime_summary(pd.concat(regime_trades, ignore_index=True) if regime_trades else pd.DataFrame())
    save_frame(regime_table, Path(cfg["research"]["output_dir"]) / "regime_performance_oos.csv")
    portfolio_rows = []
    for limit in cfg["portfolio"].get("max_positions", [1, 3, 5, 10]):
        portfolio = run_portfolio_backtest(final_oos_universe, frozen_strategy, normal_cost, float(cfg["backtest"]["initial_capital"]), float(cfg["backtest"]["risk_per_trade"]), int(limit), float(cfg["portfolio"].get("max_total_exposure", 0.80)))
        portfolio_rows.append({"max_positions": int(limit), **portfolio["metrics"]})
    portfolio_table = pd.DataFrame(portfolio_rows)
    save_frame(portfolio_table, Path(cfg["research"]["output_dir"]) / "portfolio_limits.csv")
    monte_carlo = {
        "bootstrap": bootstrap_metrics(final_oos["trades"], seed=int(cfg["project"].get("seed", 42))),
        "monte_carlo": monte_carlo_ruin(final_oos["trades"], float(cfg["backtest"]["initial_capital"]), seed=int(cfg["project"].get("seed", 42))),
    }
    save_json(Path(cfg["research"]["output_dir"]) / "monte_carlo.json", monte_carlo)
    metadata = {
        "data_reference": {s: {"first": str(f["timestamp"].min()), "last": str(f["timestamp"].max()), "rows": len(f)} for s, f in universe.items()},
        "strategy_version": cfg["project"].get("version", "1.0.0"),
        "symbols": list(universe), "interval": cfg["data"]["interval"], "windows": len(windows),
        "survivorship_bias_note": "Current symbol list is not a delisting-complete historical universe.",
        "paper_gate": gate.to_dict(),
    }
    save_json(Path(cfg["research"]["output_dir"]) / "metadata.json", metadata)
    write_final_report(Path(cfg["research"]["report_dir"]) / "final_report.md", metadata, final_best, final_oos, coin_table, walk_forward, stress, monte_carlo, regime_table, portfolio_table)
    LOG.info("Research complete. Report: %s", Path(cfg["research"]["report_dir"]) / "final_report.md")


def load_cached_universe(cfg: dict) -> dict[str, pd.DataFrame]:
    cache_dir = Path(cfg["data"]["cache_dir"])
    interval = cfg["data"]["interval"]
    universe: dict[str, pd.DataFrame] = {}
    for symbol in list(cfg["data"]["symbols"])[: int(cfg["data"].get("max_symbols", 30))]:
        candidates = sorted(cache_dir.glob(f"{symbol}_{interval}_*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            universe[symbol] = pd.read_parquet(candidates[0])
    return universe


def experiment_id(window: int, split: str, strategy: StrategyConfig) -> str:
    payload = f"{window}|{split}|{strategy.to_dict()}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Crypto Spot Long-Only backtest")
    parser.add_argument("--config", default="configs/config.yaml")
    parser.add_argument("--mode", choices=["data", "smoke", "full"], default="full")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--max-trials", type=int, default=None)
    parser.add_argument("--max-windows", type=int, default=None)
    parser.add_argument("--interval", default=None, help="OHLCV interval, e.g. 5m, 15m, 1h, 4h")
    parser.add_argument("--symbols", default=None, help="Comma-separated Spot symbols, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument("--add-symbol", action="append", default=[], help="Add and validate a user-selected Spot symbol")
    parser.add_argument("--discover-universe", action="store_true", help="Discover active USDT Spot symbols from Binance")
    return parser.parse_args()


if __name__ == "__main__":
    main()
