# CT fix bundle

This bundle isolates the root causes behind the missing logs / missing live prices / stale strategy integration.

## Root causes found

1. `main.py` called `logger.info(...)` before `logger = logging.getLogger(...)` was assigned when `OBS_JSON_LOG` was set.
2. The observability layer suppresses `strategy_check`, `event_log`, and several monitoring traces unless the level is DEBUG/TRACE.
3. `Core/trade_monitor.py` reset `last_analysis_time` immediately before the periodic scan check, which made the 30-minute scanner effectively dead code.
4. Live prices were stored, but the visible output path relied on debug-level observability calls, so the operator saw too little.
5. The system had enough telemetry hooks, but not enough always-on reporting for the exact symptoms the user described.

## Fixes in this bundle

- initialize the logger before any use
- force DEBUG observability unless the operator already selected a level
- keep Telegram polling single-instance and delete any stale webhook before polling
- add periodic system snapshots with current live prices
- move the 30-minute scanner onto its own timer so candle activity cannot suppress it
- emit live price summaries and WebSocket heartbeats regularly
\n- Fixed ModuleNotFoundError for 'config.settings' by converting config.py to a package with __init__.py
