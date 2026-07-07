# CT fix bundle

This bundle is a surgical repair of the core decision logic for `mkkh01/CT`.

What is fixed:
- Direction-aware scoring for BUY and SELL.
- `OrderBlock` now contributes to SMC scoring instead of being log-only.
- SMC is no longer cosmetic; it participates in the hard gate.
- Confidence and probability are separated from score semantics.
- Conservative probability mapping replaces the old score=probability shortcut.
- The acceptance threshold is now 85, not 60/65.

What I reviewed in the repository:
- `Core/ai_engine.py` — it consumes the strategy verdict directly and opens live trades only after `SKIP` is excluded.
- `Core/trade_monitor.py` — it acts as the scheduler/trigger layer.
- `Core/risk_manager.py` — it handles sizing and SL/TP, but it is not the source of the false-positive entry bug.
- `database.py` — the current schema uses `capital`, `risk_percentage`, `timeframe`, and `enabled`, so it does not need the schema change seen in your logs.

Important note:
- This is not a byte-for-byte mirror of the whole repository.
- It is the corrected logic bundle that prevents low-quality 65-score entries and raises the practical acceptance bar to 85.
