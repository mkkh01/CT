create extension if not exists pgcrypto;

create table if not exists public.indicator_symbols (
  symbol text primary key,
  exchange text not null default 'binance',
  market_type text not null default 'spot',
  is_active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.indicator_candles (
  symbol text not null,
  timeframe text not null,
  open_time bigint not null,
  close_time bigint not null,
  open numeric not null,
  high numeric not null,
  low numeric not null,
  close numeric not null,
  volume numeric not null,
  is_closed boolean not null default true,
  source text not null default 'binance',
  received_at timestamptz not null default now(),
  primary key (symbol, timeframe, open_time)
);

create index if not exists indicator_candles_lookup_idx on public.indicator_candles(symbol, timeframe, open_time desc);

create table if not exists public.indicator_analysis_snapshots (
  symbol text not null,
  timeframe text not null,
  generated_at timestamptz not null default now(),
  payload jsonb not null default '{}'::jsonb,
  primary key (symbol, timeframe)
);

create table if not exists public.indicator_signals (
  id uuid primary key,
  symbol text not null,
  timeframe text not null,
  direction text not null check (direction in ('BUY','SELL')),
  status text not null check (status in ('SETUP_DETECTED','WAITING_CONFIRMATION','SIGNAL_CONFIRMED','ENTRY_PENDING','ACTIVE','TP1_HIT','TP2_HIT','SL_HIT','INVALIDATED','EXPIRED','CANCELLED')),
  score numeric not null check (score >= 0 and score <= 100),
  entry numeric not null,
  stop_loss numeric not null,
  tp1 numeric not null,
  tp2 numeric not null,
  created_at timestamptz not null,
  signal_version text not null,
  reasons jsonb not null default '[]'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  unique (symbol, timeframe, created_at, signal_version)
);

create index if not exists indicator_signals_lookup_idx on public.indicator_signals(symbol, timeframe, created_at desc);

create table if not exists public.indicator_runtime_state (
  key text primary key,
  updated_at timestamptz not null default now(),
  payload jsonb not null default '{}'::jsonb
);

create table if not exists public.indicator_settings (
  key text primary key,
  value jsonb not null default '{}'::jsonb,
  version text not null default 'core_v1',
  updated_at timestamptz not null default now()
);

alter table public.indicator_symbols enable row level security;
alter table public.indicator_candles enable row level security;
alter table public.indicator_analysis_snapshots enable row level security;
alter table public.indicator_signals enable row level security;
alter table public.indicator_runtime_state enable row level security;
alter table public.indicator_settings enable row level security;

grant usage on schema public to service_role;
grant select, insert, update, delete on public.indicator_symbols to service_role;
grant select, insert, update, delete on public.indicator_candles to service_role;
grant select, insert, update, delete on public.indicator_analysis_snapshots to service_role;
grant select, insert, update, delete on public.indicator_signals to service_role;
grant select, insert, update, delete on public.indicator_runtime_state to service_role;
grant select, insert, update, delete on public.indicator_settings to service_role;

notify pgrst, 'reload schema';
