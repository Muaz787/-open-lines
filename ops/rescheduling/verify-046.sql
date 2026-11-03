-- Read-only checks to run right after migration 046. Every "ok" must be true.
select json_build_object(
  'table', json_build_object('ok', to_regclass('public.calendar_move_operations') is not null),
  'empty', (select json_build_object('ok', count(*) = 0, 'rows', count(*)) from public.calendar_move_operations),
  'rls_on', json_build_object('ok', (select relrowsecurity from pg_class where oid = 'public.calendar_move_operations'::regclass)),
  'one_live_index', json_build_object('ok', exists (select 1 from pg_indexes where schemaname = 'public'
      and indexname = 'calendar_move_operations_one_live' and indexdef like '%UNIQUE%')),
  'function', json_build_object('ok', to_regprocedure('public.calendar_move_finish(uuid,uuid)') is not null),
  'browser_roles_denied', json_build_object('ok',
      not has_table_privilege('anon', 'public.calendar_move_operations', 'SELECT,INSERT,UPDATE,DELETE')
      and not has_table_privilege('authenticated', 'public.calendar_move_operations', 'SELECT,INSERT,UPDATE,DELETE')
      and not has_function_privilege('anon', 'public.calendar_move_finish(uuid,uuid)', 'EXECUTE')
      and not has_function_privilege('authenticated', 'public.calendar_move_finish(uuid,uuid)', 'EXECUTE')),
  'service_role_access', json_build_object('ok',
      has_table_privilege('service_role', 'public.calendar_move_operations', 'SELECT')
      and has_table_privilege('service_role', 'public.calendar_move_operations', 'INSERT')
      and has_table_privilege('service_role', 'public.calendar_move_operations', 'UPDATE')
      and has_function_privilege('service_role', 'public.calendar_move_finish(uuid,uuid)', 'EXECUTE'))
) as r;
