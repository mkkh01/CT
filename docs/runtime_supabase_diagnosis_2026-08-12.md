# Runtime/Supabase diagnosis — 2026-08-12

## Evidence from deployed Render

`/healthz` at `https://crypto-trading-ru2v.onrender.com/healthz` returned `runtime_started=true`, `websocket_connected=false`, `startup_stage=waiting_for_live_candle_close`, `last_ws_attempt_at=2026-08-12T17:58:20.362128+00:00`, `last_message_at=null`, no WebSocket error/close code, and all four symbols ready with 199 candles per timeframe. This means historical readiness remains true while the live socket is currently down.

## Evidence from Supabase project

Project: `Trading_bot`, ref `licqbfixgyzrahuscwnh`, region `eu-west-1`, status `ACTIVE_HEALTHY`.

`public.bot_settings` has one row for chat `1503808643`, selected symbols `LINKUSDT, NEARUSDT, XLMUSDT, XRPUSDT`, capital `30 USDT` per symbol, max concurrent positions `5`, daily loss limit `0.09`, updated at `2026-08-11 22:21:09.468917+00`.

Current schema tables: `bot_settings` (1 row), `signals` (0), `virtual_positions` (0), `trade_events` (0), `system_events` (565 rows). RLS is enabled on all tables. There is no dedicated mutable runtime-state table; `system_events` is append-only history.

The latest `system_events` summary at approximately `2026-08-12T18:02:24Z` reported `websocket_connected=true`, `startup_stage=ready`, all four symbols ready, 200 1H candles and 199 4H candles, and four strategy cycles. Its `last_decision` for LINKUSDT was `NO_SIGNAL` because breakout and volume confirmation were false. XLMUSDT, XRPUSDT, and NEARUSDT were rejected by the ADX sideways filter. This historical row conflicts with the current `/healthz`, confirming that Dashboard mixes live in-memory health with historical Supabase events.

## Root-cause hypothesis

The current dashboard is not database-inconsistent at the schema level; it has two different sources of truth. Live fields (`websocket_connected`, current market status) come from the current process memory, while events/summary rows come from Supabase history. The WebSocket client has no stale-message watchdog and readiness is calculated solely from candle counts, so `ready_for_strategy=true` can remain true after a live socket disconnects. The runtime can therefore show 100% readiness while health shows disconnected.

## Follow-up comparison

At 18:03 UTC, `/healthz` returned `websocket_connected=false` with null `last_message_at`. At 18:06 UTC, `/dashboard/api/overview` returned `websocket_connected=true`, `market_status.connected=true`, and `last_message_at=2026-08-12T18:06:27.228661+00Z`, with current summary events. This indicates a transient connection state or inconsistent request/instance view rather than a persistent database outage. The dashboard must expose current-vs-persisted timestamps explicitly and use a liveness watchdog so stale connected states cannot be shown as healthy.

## Database alignment fix

A new `public.runtime_state` table was applied successfully to the Trading_bot project through a migration. It stores one mutable row per `user_id` with current runtime status, WebSocket liveness timestamps/errors, stream URL, symbols, capital, strategy-ready symbols, market status, and metrics. The row is upserted on every summary cycle and read by Dashboard to display `متطابق` or `غير متطابق` with its age.

Before the new Render code is deployed, the table is empty (`[]`), which is expected. The first startup summary after deployment will create the row for chat `1503808643`.

## Final local verification

Full test suite: `25 passed`. Dashboard inline JavaScript syntax check: passed. Python compileall and `git diff --check`: passed.
