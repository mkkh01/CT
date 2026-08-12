-- The runtime uses the Supabase service-role key on Render.
-- Tables created after the original reset need explicit PostgREST privileges.
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.runtime_state to service_role;
