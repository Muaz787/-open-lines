-- Fix 4 — aggregate the dashboard stats in the database.
--
-- GET /leads/{tenant_id}/stats built its trend charts by SELECTing every calls,
-- leads and appointments row in the period (capped at 100k each) and counting
-- them in Python. That transfers and parses O(rows); at volume it is the slowest
-- thing the dashboard does. This function returns one row per (metric, time
-- bucket) instead, so only O(buckets) crosses the wire (<= 30 per metric).
--
-- PARITY WITH THE PYTHON PATH (which stays as a fallback):
--   * Buckets are truncated in UTC, matching _period_window's midnight-UTC start
--     and per-hour ('today') / per-day (7d,30d) bucketing.
--   * status <> 'cancelled' drops NULL-status rows too, exactly as PostgREST's
--     .neq('status','cancelled') does, so the appointment count is unchanged.
--   * bucket_start is returned as a UTC timestamptz; the caller maps it to a
--     bucket index with the SAME function it applies to a raw row's created_at,
--     and every row in a bucket shares that bucket's hour/day, so the index is
--     identical to counting the rows one by one.
--
-- SECURITY DEFINER so it runs regardless of RLS; it is only ever called by the
-- backend under the service role, after verify_tenant_owner has authorised the
-- caller for p_tenant_id, and it never returns row-level data — only counts.

create or replace function tenant_stats_series(
    p_tenant_id uuid,
    p_start     timestamptz,
    p_bucket    text
)
returns table (metric text, bucket_start timestamptz, cnt bigint, secs numeric)
language sql
stable
security definer
set search_path = public
as $$
    select 'calls'::text,
           date_trunc(p_bucket, created_at at time zone 'UTC') at time zone 'UTC',
           count(*)::bigint,
           coalesce(sum(duration_secs), 0)::numeric
    from calls
    where tenant_id = p_tenant_id and created_at >= p_start
    group by 2
  union all
    select 'leads'::text,
           date_trunc(p_bucket, created_at at time zone 'UTC') at time zone 'UTC',
           count(*)::bigint,
           0::numeric
    from leads
    where tenant_id = p_tenant_id and created_at >= p_start
    group by 2
  union all
    select 'appts'::text,
           date_trunc(p_bucket, created_at at time zone 'UTC') at time zone 'UTC',
           count(*)::bigint,
           0::numeric
    from appointments
    where tenant_id = p_tenant_id and status <> 'cancelled' and created_at >= p_start
    group by 2
$$;
