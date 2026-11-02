-- Read-only checks to run on production before migration 042. Changes nothing.
-- Every "ok" must be true. Stop on anything else.
select json_build_object(
  'database', current_database(),
  'tenants', (select count(*) from public.tenants),
  'tenants_rls_on', json_build_object('ok', (select relrowsecurity from pg_class where oid = 'public.tenants'::regclass)),
  'required_columns', (
    with want(c, t) as (values
      ('minutes_used_this_period', 'integer'),
      ('overage_minutes_reported', 'integer'),
      ('billing_period_anchor', 'date'))
    select json_build_object('ok', count(*) filter (where i.data_type = want.t) = 3,
                             'found', json_object_agg(want.c, i.data_type))
    from want left join information_schema.columns i
      on i.table_schema = 'public' and i.table_name = 'tenants' and i.column_name = want.c),
  'tenants_id_is_uuid', json_build_object('ok', (select data_type = 'uuid' from information_schema.columns
      where table_schema = 'public' and table_name = 'tenants' and column_name = 'id')),
  'no_name_collisions', (
    with hits as (
      select 'table ' || relname n from pg_class c join pg_namespace s on s.oid = c.relnamespace
       where s.nspname = 'public' and relname in ('usage_events', 'usage_quarantine')
      union all select 'function ' || proname from pg_proc p join pg_namespace s on s.oid = p.pronamespace
       where s.nspname = 'public' and proname like 'usage\_%'
      union all select 'column ' || column_name from information_schema.columns
       where table_schema = 'public' and table_name = 'tenants' and column_name = 'billing_period_started_at')
    select json_build_object('ok', count(*) = 0, 'found', coalesce(json_agg(n), '[]')) from hits),
  'pgcrypto_or_builtin_uuid', json_build_object('ok', exists(select 1 from pg_proc where proname = 'gen_random_uuid')),
  'no_triggers_on_tenants', json_build_object('ok', not exists(select 1 from pg_trigger
      where tgrelid = 'public.tenants'::regclass and not tgisinternal)),
  'long_transactions', (select json_build_object('ok', count(*) = 0, 'count', count(*)) from pg_stat_activity
      where datname = current_database() and xact_start < now() - interval '30 seconds' and pid <> pg_backend_pid()),
  'tenants_with_subscription', (select count(*) from public.tenants where stripe_subscription_id is not null),
  'tenants_live_status_no_anchor', (select count(*) from public.tenants
      where stripe_subscription_id is not null and billing_period_anchor is null
        and subscription_status in ('active', 'trialing', 'past_due', 'canceling')),
  'overage_reported_so_far', (select coalesce(sum(overage_minutes_reported), 0) from public.tenants)
) as preflight;
