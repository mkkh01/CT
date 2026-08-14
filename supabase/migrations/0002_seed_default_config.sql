insert into public.indicator_symbols (symbol, exchange, market_type, is_active)
values
  ('BTCUSDT','binance','spot',true),('ETHUSDT','binance','spot',true),('BNBUSDT','binance','spot',true),('SOLUSDT','binance','spot',true),('XRPUSDT','binance','spot',true),
  ('ADAUSDT','binance','spot',true),('DOGEUSDT','binance','spot',true),('AVAXUSDT','binance','spot',true),('LINKUSDT','binance','spot',true),('DOTUSDT','binance','spot',true),
  ('TRXUSDT','binance','spot',true),('LTCUSDT','binance','spot',true),('BCHUSDT','binance','spot',true),('NEARUSDT','binance','spot',true),('UNIUSDT','binance','spot',true),
  ('ATOMUSDT','binance','spot',true),('ETCUSDT','binance','spot',true),('FILUSDT','binance','spot',true),('APTUSDT','binance','spot',true),('ARBUSDT','binance','spot',true)
on conflict (symbol) do update set is_active = excluded.is_active, updated_at = now();

insert into public.indicator_settings (key, value, version)
values
  ('signal', '{"min_score":80,"min_direction_gap":15,"require_closed_candle":true,"max_pending_candles":10}'::jsonb, 'core_v1'),
  ('risk', '{"rr_tp1":1.0,"rr_tp2":2.0,"atr_buffer_multiplier":0.1}'::jsonb, 'core_v1'),
  ('multi_timeframe', '{"15m":["1h","4h"]}'::jsonb, 'core_v1')
on conflict (key) do update set value = excluded.value, version = excluded.version, updated_at = now();
