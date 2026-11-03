-- Read-only checks to run on production before migration 044. Changes nothing.
-- Every "ok" must be true. Stop on anything else.
select json_build_object(
  'database', json_build_object('ok', current_database() = 'postgres' and current_user = 'postgres',
                                'db', current_database(), 'user', current_user),
  'calls_table', json_build_object('ok', to_regclass('public.calls') is not null),
  'new_columns_absent', (select json_build_object('ok', count(*) = 0, 'found', coalesce(json_agg(column_name), '[]'))
      from information_schema.columns where table_schema = 'public' and table_name = 'calls'
       and column_name in ('summary', 'urgency', 'key_details', 'suggested_next_step')),
  'calls_rls_on', json_build_object('ok', (select relrowsecurity from pg_class where oid = 'public.calls'::regclass)),
  'browser_roles_have_no_calls_access', json_build_object('ok',
      not has_table_privilege('anon', 'public.calls', 'SELECT,INSERT,UPDATE,DELETE')
      and not has_table_privilege('authenticated', 'public.calls', 'SELECT,INSERT,UPDATE,DELETE')),
  'service_role_can_write_calls', json_build_object('ok',
      has_table_privilege('service_role', 'public.calls', 'SELECT')
      and has_table_privilege('service_role', 'public.calls', 'UPDATE')),
  'calls_rows', (select count(*) from public.calls),
  'long_transactions', (select json_build_object('ok', count(*) = 0, 'count', count(*)) from pg_stat_activity
      where state <> 'idle' and xact_start < now() - interval '1 minute' and pid <> pg_backend_pid())
) as r;
