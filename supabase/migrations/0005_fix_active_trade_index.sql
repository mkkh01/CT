drop index if exists public.indicator_trades_active_idx;
create index if not exists indicator_trades_active_idx on public.indicator_trades(status) where status in ('SIGNAL_CONFIRMED','ENTRY_PENDING','ACTIVE');
notify pgrst, 'reload schema';
