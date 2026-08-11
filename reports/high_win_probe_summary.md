# High-win-rate probe summary

A focused development probe on BTCUSDT, ETHUSDT and BNBUSDT using normal fees, slippage and spread tested selective mean-reversion candidates with small take-profit multiples.

The highest observed development Win Rates were not profitable:

| Candidate | Trades | Win Rate | Profit Factor | Net Profit |
|---|---:|---:|---:|---:|
| mean_reversion_reclaim, threshold 35, TP 0.25R | 140 | 80.00% | 0.6378 | -540.08 |
| bollinger_reversion, threshold 35, TP 0.25R | 196 | 78.06% | 0.5492 | -989.20 |
| bollinger_reversion, threshold 55, TP 0.25R | 99 | 77.78% | 0.5311 | -549.10 |
| mean_reversion_reclaim, threshold 55, TP 0.25R | 61 | 73.77% | 0.4626 | -454.49 |

This is direct evidence in the current data that 75–80% Win Rate can be manufactured by reducing the target, while the strategy remains negative after realistic costs. The new research cycle therefore treats 75–80% as a screening preference, not a success criterion. A candidate can proceed only if its OOS Expectancy, Profit Factor, stress result, and Walk-Forward stability also pass.

No live or paper-trading permission is granted by this probe.

## Additional probes

A second probe tested tighter ATR stops, higher score thresholds, and a causal Break-Even rule. No candidate with the required minimum trade count had positive expectancy; the best development combinations remained below Profit Factor 1.0. Break-Even reduced some losses but also converted many trades into non-winning exits and did not create a positive edge.

The newly added `high_confidence_reclaim` rule was deliberately made very selective. It did not produce enough trades in the probe to satisfy the minimum evidence requirement, so it is not promoted to Paper Trading.

The readiness gate now explicitly requires `min_oos_win_rate: 0.75` in addition to OOS Profit Factor, positive Expectancy, drawdown, stress, and Walk-Forward stability. This means a strategy with 60–70% Win Rate cannot be called ready merely because it is profitable, and a strategy with 80% Win Rate cannot pass if it loses money after costs.
