-- Read-only checks to run on production before migration 047. Changes nothing.
-- Every "ok" must be true. Stop on anything else.
select json_build_object(
  'database', json_build_object('ok', current_database() = 'postgres' and current_user = 'postgres'),
  'table_046_present', json_build_object('ok', to_regclass('public.calendar_move_operations') is not null),
  'finish_046_present', json_build_object('ok', to_regprocedure('public.calendar_move_finish(uuid,uuid)') is not null),
  'provider_check_is_046s', (select json_build_object('ok', count(*) = 1, 'def', min(pg_get_constraintdef(oid)))
      from pg_constraint where conrelid = 'public.calendar_move_operations'::regclass
       and conname = 'calendar_move_operations_provider_check'),
  'new_columns_absent', (select json_build_object('ok', count(*) = 0, 'found', coalesce(json_agg(column_name), '[]'))
      from information_schema.columns where table_schema = 'public' and table_name = 'calendar_move_operations'
       and column_name in ('provider_version', 'team_member_id', 'service_variation_id', 'slot_ref')),
  'claim_type_check_is_021s', (select json_build_object('ok', count(*) = 1
          and min(pg_get_constraintdef(oid)) not like '%payment_confirmation%', 'def', min(pg_get_constraintdef(oid)))
      from pg_constraint where conrelid = 'public.appointment_mutation_claims'::regclass
       and conname = 'appointment_mutation_claims_type_chk'),
  'no_live_moves', (select json_build_object('ok', count(*) = 0, 'count', count(*))
      from public.calendar_move_operations where state in ('in_progress', 'unknown', 'provider_moved')),
  'long_transactions', (select json_build_object('ok', count(*) = 0, 'count', count(*)) from pg_stat_activity
      where state <> 'idle' and xact_start < now() - interval '1 minute' and pid <> pg_backend_pid())
) as r;
