-- Read-only checks to run on production before migration 045. Changes nothing.
-- Every "ok" must be true. Stop on anything else.
select json_build_object(
  'database', json_build_object('ok', current_database() = 'postgres' and current_user = 'postgres',
                                'db', current_database(), 'user', current_user),
  'table_absent', json_build_object('ok', to_regclass('public.call_booking_claims') is null),
  'appointments_shape', (select json_build_object('ok', count(*) = 3, 'found', json_object_agg(column_name, data_type))
      from information_schema.columns where table_schema = 'public' and table_name = 'appointments'
       and column_name in ('vapi_call_id', 'google_event_id', 'rescheduled_from_appointment_id')),
  'tenants_id_is_uuid', json_build_object('ok', (select data_type = 'uuid' from information_schema.columns
      where table_schema = 'public' and table_name = 'tenants' and column_name = 'id')),
  -- 043's defaults: a new table must not reach the browser roles, even before the
  -- migration's own revoke runs.
  'defaults_exclude_browser_roles', (select json_build_object('ok', count(*) = 0, 'count', count(*))
      from pg_default_acl d, aclexplode(d.defaclacl) a
      where d.defaclrole = 'postgres'::regrole and d.defaclnamespace = 'public'::regnamespace
        and d.defaclobjtype = 'r' and a.grantee in ('anon'::regrole, 'authenticated'::regrole)),
  'mutation_claims_present', json_build_object('ok', to_regclass('public.appointment_mutation_claims') is not null),
  'long_transactions', (select json_build_object('ok', count(*) = 0, 'count', count(*)) from pg_stat_activity
      where state <> 'idle' and xact_start < now() - interval '1 minute' and pid <> pg_backend_pid())
) as r;
