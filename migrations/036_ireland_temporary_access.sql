-- 036 — the durable lifecycle of one Irish onboarding's free temporary test access
-- (W9I-H.AUTO.1)
--
-- WHY A TABLE AND NOT COLUMNS ON tenant_phone_numbers
-- Every policy this holds outlives the NUMBER it is about. The 60-minute
-- allowance and the 30-day clock belong to the ONBOARDING LIFECYCLE: they must
-- survive a number being replaced, adopted, retired, or re-acquired after an
-- ambiguous purchase. Hanging them off the phone row would reset the allowance
-- exactly when someone cycles a number, which is the abuse this is here to stop.
-- One row per tenant, and the tenant is the lifecycle.
--
-- WHAT provider_attempt_at IS FOR
-- The same lesson as migration 035, applied to a different provider. Written
-- immediately BEFORE Twilio is asked to buy a number, so a worker that dies
-- mid-call leaves proof it may have spent money. Absence of positive
-- reconciliation is not proof the purchase failed, and no amount of elapsed time
-- makes a second purchase safe.
--
-- ROLLBACK
--   drop function if exists ita_consume_seconds(uuid, integer);
--   drop table if exists ireland_temporary_access;

create table if not exists ireland_temporary_access (
    tenant_id               uuid primary key
                            references tenants(id) on delete cascade,

    -- ── the provider-attempt boundary (Stage E) ──────────────────────────
    provider_attempt_at     timestamptz null,
    e164                    text        null,
    provider_sid            text        null,

    -- ── the free allowance (Stages I, N) ─────────────────────────────────
    -- Seconds, not minutes: the provider reports seconds, and rounding at write
    -- time would let many short calls round away most of the allowance.
    seconds_used            integer     not null default 0,

    -- ── the clocks (Stages P, Q, R, Z) ───────────────────────────────────
    -- Each is a START point recorded once. Durations live in application policy
    -- so they can be changed by decision rather than by migration, but the
    -- instants they count from are durable and are never restamped.
    access_started_at       timestamptz null,
    action_required_at      timestamptz null,
    rejected_at             timestamptz null,
    cutover_at              timestamptz null,

    -- ── suspension, separate from release (Stage S) ──────────────────────
    -- Suspension stops inbound testing. It does NOT release the number: the
    -- regulatory lifecycle may still need it, and retirement is its own fenced
    -- step with its own triggers.
    suspended_at            timestamptz null,
    suspend_reason          text        null,

    -- ── retirement (Stage AA) ────────────────────────────────────────────
    retirement_claimed_at   timestamptz null,
    released_at             timestamptz null,

    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);

-- A number may only be recorded once an attempt to buy one was recorded first.
-- The structural twin of ops_attach_implies_attempt_chk in migration 035.
alter table ireland_temporary_access
    drop constraint if exists ita_number_implies_attempt_chk;
alter table ireland_temporary_access
    add  constraint ita_number_implies_attempt_chk
    check (e164 is null or provider_attempt_at is not null);

-- The E.164 and its provider SID are one fact, recorded together.
alter table ireland_temporary_access
    drop constraint if exists ita_number_columns_agree_chk;
alter table ireland_temporary_access
    add  constraint ita_number_columns_agree_chk
    check ((e164 is null) = (provider_sid is null));

-- Allowance is consumed, never restored to a negative.
alter table ireland_temporary_access
    drop constraint if exists ita_seconds_used_chk;
alter table ireland_temporary_access
    add  constraint ita_seconds_used_chk check (seconds_used >= 0);

-- A suspension always says why. Not orphan protection -- it only proves the two
-- columns agree, so neither can be set without the other.
alter table ireland_temporary_access
    drop constraint if exists ita_suspend_columns_agree_chk;
alter table ireland_temporary_access
    add  constraint ita_suspend_columns_agree_chk
    check ((suspended_at is null) = (suspend_reason is null));

-- Access cannot have started before there was a number to access.
alter table ireland_temporary_access
    drop constraint if exists ita_access_implies_number_chk;
alter table ireland_temporary_access
    add  constraint ita_access_implies_number_chk
    check (access_started_at is null or e164 is not null);

-- A release is always the completion of a claimed retirement, never a bare event.
alter table ireland_temporary_access
    drop constraint if exists ita_release_implies_claim_chk;
alter table ireland_temporary_access
    add  constraint ita_release_implies_claim_chk
    check (released_at is null or retirement_claimed_at is not null);

-- Server-side only. No customer and no browser reads or writes this: it decides
-- entitlement and spend, so RLS is on with NO policy and the deny is total.
alter table ireland_temporary_access enable row level security;

-- ── the allowance increment, done IN the database (Stage M) ──────────────
-- Two test calls ending at the same instant must not both read the same
-- starting total and write the same result -- that is how a 59-minute tenant
-- gets unbounded minutes. `seconds_used = seconds_used + n` is evaluated by
-- Postgres under the row lock the UPDATE already takes, so concurrent callers
-- serialise and the total is exact. Returns the new total so the caller can act
-- on the value it actually produced rather than re-reading a moving row.
create or replace function ita_consume_seconds(p_tenant uuid, p_seconds integer)
returns table (tenant_id uuid, seconds_used integer, suspended_at timestamptz)
language sql
security definer
set search_path = public
as $$
    update ireland_temporary_access
       set seconds_used = seconds_used + greatest(0, p_seconds),
           updated_at   = now()
     where ireland_temporary_access.tenant_id = p_tenant
 returning ireland_temporary_access.tenant_id,
           ireland_temporary_access.seconds_used,
           ireland_temporary_access.suspended_at;
$$;

-- Server-side only, like the table. No browser role may spend an allowance.
revoke all on function ita_consume_seconds(uuid, integer) from public;
revoke all on function ita_consume_seconds(uuid, integer) from anon, authenticated;

comment on table ireland_temporary_access is
    'W9I-H.AUTO.1: one Irish onboarding''s free temporary test access. The '
    '60-minute allowance and every lifecycle clock live here rather than on the '
    'phone row, so they survive the number being replaced or retired.';
