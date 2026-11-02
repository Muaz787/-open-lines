-- 042 — usage is recorded per call, in one locked step
--
-- record_call_minutes read the counter, added to it in Python and wrote the total back,
-- and the webhook wrote zero. Against a real database, 40 concurrent one-minute calls
-- recorded 2 minutes, and a reset racing 20 calls left 101 instead of 20.
--
-- usage_events holds one row per call, with the time it ended:
--   * A call belongs to the billing period containing its end time, whenever it is
--     processed. A rollover keeps the minutes of calls that ended in the new period, so
--     a call recorded while Stripe was unreachable is not cleared with the old one.
--   * A call that ended in an earlier period stays in the ledger and doesn't count
--     against the current allowance.
--   * A retried call changes nothing, because each call is recorded once.
--   * Overage is reported from the ledger, so a crash after Stripe accepts it can be
--     retried with the same identifier.
--
-- Each function takes the tenant's row lock. A period only moves forward.
--
-- Backend only: default privileges give new tables and functions to anon and
-- authenticated, so each is revoked explicitly. No existing data changes. Apply this
-- BEFORE deploying the backend that calls it, or calls will fail to record usage.

begin;
set local lock_timeout = '3s';

alter table public.tenants
  add column if not exists billing_period_started_at timestamptz;

create table if not exists public.usage_events (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    call_id         text not null,
    minutes         integer not null check (minutes > 0),
    ended_at        timestamptz not null,
    counted         boolean not null,
    overage_minutes integer not null default 0,
    overage_state   text not null default 'none'
                    check (overage_state in ('none', 'pending', 'reported', 'review')),
    created_at      timestamptz not null default now(),
    unique (tenant_id, call_id)
);

create index if not exists usage_events_tenant_ended on public.usage_events (tenant_id, ended_at);
create index if not exists usage_events_overage_pending on public.usage_events (created_at)
    where overage_state = 'pending';

alter table public.usage_events enable row level security;
revoke all on table public.usage_events from public, anon, authenticated;
grant select, insert, update, delete on table public.usage_events to service_role;

-- A stored date has no time of day, so it can only show a later date as newer.
create or replace function public.usage_period_moved(
    p_started timestamptz, p_anchor date, p_new timestamptz
)
returns boolean
language sql
immutable
security invoker
set search_path = ''
as $$
    select case
        when p_started is not null then p_new > p_started
        when p_anchor is not null then (p_new at time zone 'UTC')::date > p_anchor
        else false
    end;
$$;

-- Caller holds the tenant's row lock.
create or replace function public.usage_enter_period(p_tenant_id uuid, p_start timestamptz)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_minutes integer;
    v_cleared integer;
    v_reported integer;
begin
    select coalesce(t.minutes_used_this_period, 0) into v_cleared from public.tenants t where t.id = p_tenant_id;

    -- Overage worked out against the old balance no longer applies to these calls.
    update public.usage_events e
       set overage_minutes = 0, overage_state = 'none'
     where e.tenant_id = p_tenant_id and e.ended_at >= p_start and e.overage_state = 'pending';

    update public.usage_events e
       set counted = true
     where e.tenant_id = p_tenant_id and e.ended_at >= p_start and not e.counted;

    select coalesce(sum(e.minutes), 0),
           coalesce(sum(e.overage_minutes) filter (where e.overage_state = 'reported'), 0)
      into v_minutes, v_reported
      from public.usage_events e
     where e.tenant_id = p_tenant_id and e.ended_at >= p_start;

    update public.tenants t
       set minutes_used_this_period  = v_minutes,
           overage_minutes_reported  = v_reported,
           billing_period_started_at = p_start,
           billing_period_anchor     = (p_start at time zone 'UTC')::date
     where t.id = p_tenant_id;

    return v_cleared - v_minutes;
end;
$$;

create or replace function public.usage_record_call(
    p_tenant_id    uuid,
    p_call_id      text,
    p_minutes      integer,
    p_ended_at     timestamptz,
    p_period_start timestamptz default null,
    p_allowance    integer default null
)
returns table (
    minutes_used integer, overage_minutes integer, duplicate boolean,
    counted boolean, rolled boolean
)
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_tenant  public.tenants%rowtype;
    v_start   timestamptz;
    v_rolled  boolean := false;
    v_counted boolean;
    v_prev    integer;
    v_total   integer;
    v_overage integer := 0;
begin
    select * into v_tenant from public.tenants t where t.id = p_tenant_id for update;
    if not found then
        return;
    end if;

    if exists (select 1 from public.usage_events e where e.tenant_id = p_tenant_id and e.call_id = p_call_id) then
        return query select coalesce(v_tenant.minutes_used_this_period, 0), 0, true, false, false;
        return;
    end if;

    if p_period_start is not null then
        if public.usage_period_moved(v_tenant.billing_period_started_at, v_tenant.billing_period_anchor, p_period_start) then
            perform public.usage_enter_period(p_tenant_id, p_period_start);
            v_rolled := true;
        elsif v_tenant.billing_period_started_at is null then
            update public.tenants t
               set billing_period_started_at = p_period_start,
                   billing_period_anchor     = (p_period_start at time zone 'UTC')::date
             where t.id = p_tenant_id;
        end if;
    end if;

    select t.minutes_used_this_period,
           coalesce(t.billing_period_started_at, t.billing_period_anchor::timestamp at time zone 'UTC')
      into v_prev, v_start
      from public.tenants t where t.id = p_tenant_id;
    v_prev := coalesce(v_prev, 0);

    v_counted := v_start is null or p_ended_at >= v_start;
    v_total := case when v_counted then v_prev + p_minutes else v_prev end;
    if v_counted and p_allowance is not null then
        v_overage := greatest(0, v_total - p_allowance) - greatest(0, v_prev - p_allowance);
    end if;

    insert into public.usage_events (tenant_id, call_id, minutes, ended_at, counted, overage_minutes, overage_state)
    values (p_tenant_id, p_call_id, p_minutes, p_ended_at, v_counted, v_overage,
            case when v_overage > 0 then 'pending' else 'none' end);

    update public.tenants t set minutes_used_this_period = v_total where t.id = p_tenant_id;

    return query select v_total, v_overage, false, v_counted, v_rolled;
end;
$$;

-- p_start_paid: a trial or complimentary account starting to pay. The new period begins
-- even if no period was on record, or the old one started the same day.
create or replace function public.usage_roll_period(
    p_tenant_id    uuid,
    p_period_start timestamptz,
    p_start_paid   boolean default false
)
returns table (rolled boolean, cleared_minutes integer)
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_tenant public.tenants%rowtype;
    v_moved  boolean;
begin
    select * into v_tenant from public.tenants t where t.id = p_tenant_id for update;
    if not found then
        return;
    end if;

    v_moved := public.usage_period_moved(v_tenant.billing_period_started_at, v_tenant.billing_period_anchor, p_period_start)
               or (p_start_paid and (v_tenant.billing_period_started_at is null or p_period_start > v_tenant.billing_period_started_at));

    if v_moved then
        return query select true, public.usage_enter_period(p_tenant_id, p_period_start);
    end if;

    if v_tenant.billing_period_started_at is null and v_tenant.billing_period_anchor is null then
        update public.tenants t
           set billing_period_started_at = p_period_start,
               billing_period_anchor     = (p_period_start at time zone 'UTC')::date
         where t.id = p_tenant_id;
    end if;
    return query select false, 0;
end;
$$;

-- Once Stripe has accepted a call's overage.
create or replace function public.usage_overage_reported(p_tenant_id uuid, p_call_id text)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_tenant public.tenants%rowtype;
    v_event  public.usage_events%rowtype;
begin
    select * into v_tenant from public.tenants t where t.id = p_tenant_id for update;
    select * into v_event from public.usage_events e
     where e.tenant_id = p_tenant_id and e.call_id = p_call_id and e.overage_state = 'pending';
    if not found then
        return false;
    end if;

    update public.usage_events e set overage_state = 'reported' where e.id = v_event.id;
    if v_event.ended_at >= coalesce(v_tenant.billing_period_started_at, v_tenant.billing_period_anchor::timestamp at time zone 'UTC') then
        update public.tenants t
           set overage_minutes_reported = coalesce(t.overage_minutes_reported, 0) + v_event.overage_minutes
         where t.id = p_tenant_id;
    end if;
    return true;
end;
$$;

do $$
declare f text;
begin
    foreach f in array array[
        'public.usage_period_moved(timestamptz, date, timestamptz)',
        'public.usage_enter_period(uuid, timestamptz)',
        'public.usage_record_call(uuid, text, integer, timestamptz, timestamptz, integer)',
        'public.usage_roll_period(uuid, timestamptz, boolean)',
        'public.usage_overage_reported(uuid, text)'
    ] loop
        execute format('revoke execute on function %s from public, anon, authenticated', f);
        execute format('grant execute on function %s to service_role', f);
    end loop;
end $$;

notify pgrst, 'reload schema';
commit;
