-- 042 — usage counters change in one locked step
--
-- record_call_minutes read the counter, added to it in Python and wrote the total back,
-- and the webhook wrote zero. Against a real database, 40 concurrent one-minute calls
-- recorded 2 minutes, and a reset racing 20 calls left 101 instead of 20.
--
-- Each function takes the tenant's row lock, so calls can't overwrite each other, and a
-- period only moves forward, so a duplicate or late event can't reset twice. A call that
-- already knows the new period rolls it itself and is counted in it, which is why the
-- webhook arriving second can't erase it.
--
-- Backend only. Default privileges give new functions to anon and authenticated, so
-- each one is revoked explicitly. No data changes, and nothing calls these until the
-- backend that uses them is deployed: run this first.

begin;
set local lock_timeout = '3s';

create or replace function public.usage_add_minutes(
    p_tenant_id     uuid,
    p_minutes       integer,
    p_period_anchor date default null
)
returns table (minutes_used integer, overage_reported integer, period_anchor date, rolled boolean)
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_minutes  integer;
    v_overage  integer;
    v_anchor   date;
    v_rolled   boolean;
begin
    select t.minutes_used_this_period, t.overage_minutes_reported, t.billing_period_anchor
      into v_minutes, v_overage, v_anchor
      from public.tenants t
     where t.id = p_tenant_id
       for update;
    if not found then
        return;
    end if;

    v_rolled := p_period_anchor is not null and v_anchor is not null and p_period_anchor > v_anchor;
    v_minutes := case when v_rolled then p_minutes else coalesce(v_minutes, 0) + p_minutes end;
    v_overage := case when v_rolled then 0 else coalesce(v_overage, 0) end;
    if p_period_anchor is not null and (v_anchor is null or v_rolled) then
        v_anchor := p_period_anchor;
    end if;

    update public.tenants t
       set minutes_used_this_period = v_minutes,
           overage_minutes_reported = v_overage,
           billing_period_anchor    = v_anchor
     where t.id = p_tenant_id;

    return query select v_minutes, v_overage, v_anchor, v_rolled;
end;
$$;

create or replace function public.usage_roll_period(
    p_tenant_id     uuid,
    p_period_anchor date
)
returns table (rolled boolean, anchored boolean, cleared_minutes integer)
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_minutes integer;
    v_anchor  date;
begin
    select t.minutes_used_this_period, t.billing_period_anchor
      into v_minutes, v_anchor
      from public.tenants t
     where t.id = p_tenant_id
       for update;
    if not found then
        return;
    end if;

    if v_anchor is null then
        update public.tenants t set billing_period_anchor = p_period_anchor where t.id = p_tenant_id;
        return query select false, true, 0;
    elsif p_period_anchor > v_anchor then
        update public.tenants t
           set minutes_used_this_period = 0,
               overage_minutes_reported = 0,
               billing_period_anchor    = p_period_anchor
         where t.id = p_tenant_id;
        return query select true, false, coalesce(v_minutes, 0);
    else
        return query select false, false, 0;
    end if;
end;
$$;

-- Only counts toward the period it was reported in.
create or replace function public.usage_add_overage_reported(
    p_tenant_id     uuid,
    p_minutes       integer,
    p_period_anchor date
)
returns void
language sql
security invoker
set search_path = ''
as $$
    update public.tenants t
       set overage_minutes_reported = coalesce(t.overage_minutes_reported, 0) + p_minutes
     where t.id = p_tenant_id
       and t.billing_period_anchor is not distinct from p_period_anchor;
$$;

revoke execute on function public.usage_add_minutes(uuid, integer, date) from public, anon, authenticated;
revoke execute on function public.usage_roll_period(uuid, date) from public, anon, authenticated;
revoke execute on function public.usage_add_overage_reported(uuid, integer, date) from public, anon, authenticated;
grant execute on function public.usage_add_minutes(uuid, integer, date) to service_role;
grant execute on function public.usage_roll_period(uuid, date) to service_role;
grant execute on function public.usage_add_overage_reported(uuid, integer, date) to service_role;

notify pgrst, 'reload schema';
commit;
