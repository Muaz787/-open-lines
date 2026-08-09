-- Migration: 011 — Phone-number reclaim
-- Run this in your Supabase SQL editor or via psql. Idempotent (safe to re-run).
--
-- SAFETY: additive and inert. The sweep that reads these columns is dark by
-- default (NUMBER_RECLAIM_ENABLED) and dry-run by default even once enabled
-- (NUMBER_RECLAIM_DRY_RUN). Applying this migration releases nothing.
--
-- WHY: a tenant whose trial lapsed keeps is_active = true and closed_at = null
-- forever, so the retention purge never sees them and their Twilio number bills
-- us indefinitely. Reclaiming it needs two facts we were not recording — when
-- their subscription ended, and whether they were ever a paying customer — plus
-- an audit trail, because releasing a number cannot be undone.

-- ---------------------------------------------------------------------------
-- 1) When the subscription ended. Set from the Stripe webhook when a
--    subscription is deleted or moves to canceled. NULL for tenants that never
--    had one. Without it a cancelled customer has no anchor to count 60 days
--    from, and the sweep conservatively refuses to touch them.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists subscription_canceled_at timestamptz;

-- ---------------------------------------------------------------------------
-- 2) First successful payment, ever. This is what separates "trial that never
--    converted" (30-day grace) from "customer who left" (60-day grace) — they
--    deserve different treatment, and subscription_status alone can't tell them
--    apart once both read 'canceled'.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists first_paid_at timestamptz;

-- ---------------------------------------------------------------------------
-- 3) Audit trail. Releasing a number is irreversible and Twilio may reassign it,
--    so we keep a permanent record of when it happened even though the number
--    itself is cleared off the row.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists number_released_at timestamptz;

-- ---------------------------------------------------------------------------
-- 4) Warning dedupe. Two notices go out before a release (14 days and 3 days
--    ahead). Flags rather than timestamps because each is sent at most once and
--    the schedule is derived from the due date, not from when we last wrote.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists number_release_warn1_sent boolean default false;
alter table tenants add column if not exists number_release_warn2_sent boolean default false;

-- ---------------------------------------------------------------------------
-- 5) Index for the daily sweep, which only ever looks at tenants still holding
--    a number.
-- ---------------------------------------------------------------------------
create index if not exists idx_tenants_holding_number
  on tenants (subscription_status)
  where twilio_phone_number is not null;
