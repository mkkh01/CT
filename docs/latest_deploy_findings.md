# Latest deployment findings

## Render
- Build completed successfully.
- Start command is now `gunicorn --workers 1 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT app.main:app`.
- Gunicorn is listening on port 10000 and Render reports the service live at `https://crypto-trading-ru2v.onrender.com`.
- Binance public bootstrap completed for BTCUSDT and ETHUSDT at 1h and 4h, then WebSocket connected successfully.

## Supabase warning
- The application attempted to call the REST path using a PostgreSQL pooler URL: `postgresql://.../rest/v1/...`.
- Correct `SUPABASE_URL` must be the project REST URL such as `https://licqbfixgyzrahuscwnh.supabase.co`; the PostgreSQL connection string belongs in a database driver, not in the REST client.
- The logged URL contained credentials. Rotate any password or database credential that was exposed in Render logs, and do not paste database passwords into application logs or screenshots.

## Telegram warning
- Telegram returned HTTP 409 Conflict for `getUpdates`, which indicates that another consumer is polling the same bot token or a webhook/polling conflict exists.
- The service must have only one polling process for this bot token. The application now calls `deleteWebhook` at polling startup and rate-limits the conflict log, but another running bot instance must still be stopped.

## Dynamic UI requirement
- User wants no hard-coded BTCUSDT or ETHUSDT display.
- The single Telegram button should be `إدارة العملات ورأس المال`.
- User commands should support `أضف XRPUSDT 50`, `عدّل XRPUSDT 75`, `احذف XRPUSDT`, and `القائمة`.
- Telegram keyboard should add one `🔎 SYMBOL` button per user-selected symbol and remove it when the symbol is deleted.
- Render `summary_cycle` should include selected symbols, capital per symbol, live prices, WebSocket state, strategy name, candle cycle counts, generated/rejected signals, open/closed positions, last decision, and last signal.
