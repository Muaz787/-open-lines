-- W9E scratch bootstrap, part 1: Supabase-provided roles (cluster-wide, idempotent).
-- Supabase ships anon / authenticated / service_role, grants the first two full table
-- privileges by default, and makes RLS the only thing between anon and the data.
-- service_role has BYPASSRLS. migrations/008, 012 and 024 name these roles, so plain
-- Postgres cannot replay the lineage without them -- and recreating them faithfully is
-- what makes the Stage F RLS proof mean anything.
do $$ begin create role anon          nologin;           exception when duplicate_object then null; end $$;
do $$ begin create role authenticated nologin;           exception when duplicate_object then null; end $$;
do $$ begin create role service_role  nologin bypassrls; exception when duplicate_object then null; end $$;
grant usage on schema public to anon, authenticated, service_role;
alter default privileges in schema public grant all on tables    to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
