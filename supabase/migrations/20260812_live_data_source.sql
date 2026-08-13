alter table public.runtime_state
  add column if not exists live_data_available boolean not null default false,
  add column if not exists live_data_source text not null default 'none';

grant usage on schema public to service_role;
grant select, insert, update, delete on table public.runtime_state to service_role;
