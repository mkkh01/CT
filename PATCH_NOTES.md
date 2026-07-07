# Patch notes

Files changed in this bundle:
- `strategies.py`
- `README_FIX.md`

Repository files reviewed for cross-file effects:
- `Core/ai_engine.py`
- `Core/trade_monitor.py`
- `Core/risk_manager.py`
- `database.py`
- `main.py`

Why only one functional file was changed:
- The false entry came from the strategy verdict being too permissive.
- `ai_engine.py` mainly relays the verdict and performs final execution checks.
- `trade_monitor.py` schedules analysis.
- `risk_manager.py` sizes risk and defines SL/TP, but it does not decide entry quality.
- `database.py` already matches the current capital/timeframe/risk schema.

Operational impact:
- Trades under the old 65-score gray zone now fall through to `SKIP`.
- A trade must now clear direction, SMC, validation, and the 85 score floor.
