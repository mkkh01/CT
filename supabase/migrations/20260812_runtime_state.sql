create table if not exists public.runtime_state (
  user_id text primary key,
  runtime_started boolean not null default false,
  websocket_connected boolean not null default false,
  startup_stage text not null default 'idle',
  websocket_last_message_at timestamptz null,
  websocket_connected_at timestamptz null,
  websocket_last_error text null,
  websocket_last_close_code text null,
  websocket_last_close_reason text null,
  websocket_active_stream_url text null,
  selected_symbols jsonb not null default '[]'::jsonb,
  capital_by_symbol jsonb not null default '{}'::jsonb,
  strategy_ready_symbols jsonb not null default '[]'::jsonb,
  market_status jsonb not null default '{}'::jsonb,
  metrics jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists runtime_state_updated_idx on public.runtime_state(updated_at desc);
alter table public.runtime_state enable row level security;
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.runtime_state to service_role;
