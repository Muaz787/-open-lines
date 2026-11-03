-- Read-only checks to run on production before migration 046. Changes nothing.
-- Every "ok" must be true. Stop on anything else.
select json_build_object(
  'database', json_build_object('ok', current_database() = 'postgres' and current_user = 'postgres',
                                'db', current_database(), 'user', current_user),
  'table_absent', json_build_object('ok', to_regclass('public.calendar_move_operations') is null),
  'function_absent', json_build_object('ok', to_regprocedure('public.calendar_move_finish(uuid,uuid)') is null),
  'claims_shape', (select json_build_object('ok', count(*) = 4, 'found', json_object_agg(column_name, data_type))
      from information_schema.columns where table_schema = 'public' and table_name = 'appointment_mutation_claims'
       and (column_name, data_type) in (('appointment_id', 'uuid'), ('operation_id', 'uuid'),
                                        ('claim_token', 'uuid'), ('operation_type', 'text'))),
  'appointments_shape', (select json_build_object('ok', count(*) = 3, 'found', json_object_agg(column_name, data_type))
      from information_schema.columns where table_schema = 'public' and table_name = 'appointments'
       and (column_name, data_type) in (('id', 'uuid'), ('appointment_datetime', 'timestamp with time zone'),
                                        ('status', 'text'))),
  -- calendar_move_finish runs as the caller (service_role), so it needs these.
  'service_role_can_finish', json_build_object('ok',
      has_table_privilege('service_role', 'public.appointments', 'SELECT')
      and has_table_privilege('service_role', 'public.appointments', 'UPDATE')
      and has_table_privilege('service_role', 'public.appointment_mutation_claims', 'SELECT')
      and has_table_privilege('service_role', 'public.appointment_mutation_claims', 'UPDATE')
      and has_table_privilege('service_role', 'public.appointment_mutation_claims', 'DELETE')),
  -- 043: new tables and functions must not reach browser roles, even before 046's own revokes.
  'defaults_exclude_browser_roles', (select json_build_object('ok', count(*) = 0, 'count', count(*))
      from pg_default_acl d, aclexplode(d.defaclacl) a
      where d.defaclrole = 'postgres'::regrole and d.defaclnamespace = 'public'::regnamespace
        and d.defaclobjtype in ('r', 'f') and a.grantee in (0, 'anon'::regrole, 'authenticated'::regrole)),
  'no_global_public_execute', json_build_object('ok', exists (select 1 from pg_default_acl d
      where d.defaclrole = 'postgres'::regrole and d.defaclnamespace = 0 and d.defaclobjtype = 'f'
        and not exists (select 1 from aclexplode(d.defaclacl) a where a.grantee = 0))),
  'live_reschedule_claims', (select json_build_object('ok', true, 'count', count(*))
      from public.appointment_mutation_claims where operation_type = 'reschedule'),
  'long_transactions', (select json_build_object('ok', count(*) = 0, 'count', count(*)) from pg_stat_activity
      where state <> 'idle' and xact_start < now() - interval '1 minute' and pid <> pg_backend_pid())
) as r;
