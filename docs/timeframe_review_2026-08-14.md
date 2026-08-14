
## BTCUSDT 1h analysis

`/api/v1/analysis/BTCUSDT/1h` returned 500 entry/structure/HTF candles and rich analysis structures, but `data_health` was `healthy=false` with reason `CANDLE_NOT_CLOSED` because the latest 1h candle was still open. The endpoint therefore returned `NO TRADE` by design. This is logically correct for the closed-candle safety rule, but the UI should explain it instead of looking empty.
