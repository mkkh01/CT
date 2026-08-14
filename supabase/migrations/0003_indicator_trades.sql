create table if not exists public.indicator_trades (
  id uuid primary key,
  signal_id uuid not null unique references public.indicator_signals(id) on delete cascade,
  symbol text not null,
  timeframe text not null,
  direction text not null check (direction in ('BUY','SELL')),
  status text not null check (status in ('SIGNAL_CONFIRMED','ENTRY_PENDING','ACTIVE','TP1_HIT','TP2_HIT','SL_HIT','INVALIDATED','EXPIRED','CANCELLED')),
  score numeric not null check (score >= 0 and score <= 100),
  entry numeric not null,
  stop_loss numeric not null,
  tp1 numeric not null,
  tp2 numeric not null,
  created_at timestamptz not null,
  activated_at timestamptz,
  tp1_hit_at timestamptz,
  exit_at timestamptz,
  exit_price numeric,
  close_reason text,
  last_price numeric,
  last_candle_open_time bigint,
  reasons jsonb not null default '[]'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists indicator_trades_lookup_idx on public.indicator_trades(symbol, timeframe, created_at desc);
create index if not exists indicator_trades_active_idx on public.indicator_trades(status) where status in ('SIGNAL_CONFIRMED','ENTRY_PENDING','ACTIVE','TP1_HIT');

alter table public.indicator_trades enable row level security;
grant select, insert, update, delete on public.indicator_trades to service_role;

notify pgrst, 'reload schema';
