-- Read-only checks to run right after migration 047. Every "ok" must be true.
select json_build_object(
  'square_allowed', json_build_object('ok', exists (select 1 from pg_constraint
      where conrelid = 'public.calendar_move_operations'::regclass and conname = 'calendar_move_operations_provider_check'
        and pg_get_constraintdef(oid) like '%square%' and pg_get_constraintdef(oid) like '%google%'
        and pg_get_constraintdef(oid) like '%microsoft%')),
  'columns', (select json_build_object('ok', count(*) = 4, 'found', json_object_agg(column_name, data_type))
      from information_schema.columns where table_schema = 'public' and table_name = 'calendar_move_operations'
       and column_name in ('provider_version', 'team_member_id', 'service_variation_id', 'slot_ref')),
  'existing_rows_untouched', (select json_build_object('ok', count(*) filter (where provider_version is not null
       or team_member_id is not null or service_variation_id is not null or slot_ref is not null) = 0, 'rows', count(*))
      from public.calendar_move_operations),
  'claim_type_allows_confirmation', json_build_object('ok', exists (select 1 from pg_constraint
      where conrelid = 'public.appointment_mutation_claims'::regclass and conname = 'appointment_mutation_claims_type_chk'
        and pg_get_constraintdef(oid) like '%payment_confirmation%' and pg_get_constraintdef(oid) like '%cancel_reconcile%'
        and pg_get_constraintdef(oid) like '%reschedule%')),
  'claims_untouched', (select json_build_object('ok', count(*) filter (where operation_type not in
          ('cancel', 'reschedule', 'cancel_reconcile', 'payment_confirmation')) = 0, 'rows', count(*))
      from public.appointment_mutation_claims),
  'browser_roles_denied', json_build_object('ok',
      not has_table_privilege('anon', 'public.calendar_move_operations', 'SELECT,INSERT,UPDATE,DELETE')
      and not has_table_privilege('authenticated', 'public.calendar_move_operations', 'SELECT,INSERT,UPDATE,DELETE'))
) as r;
