-- فهارس خفيفة لتسريع التنظيف وحساب آخر نبضة رصيد.
CREATE INDEX IF NOT EXISTS idx_ct_cycles_ended ON ct_cycles(ended_at DESC);
CREATE INDEX IF NOT EXISTS idx_equity_marks_ts ON equity_marks(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
