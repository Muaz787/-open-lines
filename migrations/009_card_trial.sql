-- Migration: 009 — Card-required free trial (foundation)
-- Run this in your Supabase SQL editor or via psql. Idempotent (safe to re-run).
--
-- SAFETY: purely ADDITIVE. Every column is nullable or defaulted, nothing existing
-- is altered, and no code reads these until the card-trial flow ships. Applying
-- this migration alone changes no behaviour.
--
-- CONTEXT: the pre-existing free trial is DERIVED (tenants.created_at + 7 days,
-- capped at 30 minutes) and involves no Stripe subscription at all — see
-- services/trial.py. The new trial is a real Stripe subscription in `trialing`
-- status with a card on file, so its end date and lifecycle live in Stripe. These
-- columns mirror the parts of that state we must read on EVERY inbound call
-- (services/trial.trial_status is on the call-gating hot path in
-- routers/webhooks.py and must never make a Stripe API call).
--
-- Both trial kinds coexist: tenants provisioned before the cutover keep the
-- derived trial, new signups get the card trial. services/trial.py branches on
-- subscription_status == 'trialing'.

-- ---------------------------------------------------------------------------
-- 1) Trial end date, mirrored from the Stripe subscription's trial_end.
--    Written when a trialing subscription is created or updated; cleared when the
--    subscription leaves `trialing`. NULL for derived (card-free) trials, which
--    compute their end date from created_at instead.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists stripe_trial_ends_at timestamptz;

-- ---------------------------------------------------------------------------
-- 2) Why the trial ended — 'time' (7 days elapsed) or 'minutes' (hit the 60-minute
--    trial cap and was auto-converted early). Analytics only; never gates anything.
--    NULL while the trial is still running or for derived trials.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists trial_converted_reason text;

-- ---------------------------------------------------------------------------
-- 3) Per-email dedupe flags for the card-trial reminder sequence.
--
--    Deliberately SEPARATE from the existing trial_email_day3_sent /
--    trial_email_day6_sent / trial_email_ended_sent flags: those belong to the
--    derived trial, whose reminder job (services/trial.process_trial_reminders)
--    skips any tenant with an active subscription — which is every card-trial
--    tenant. The two sequences say different things (a card trial warns about an
--    imminent CHARGE) and must be tracked independently so a tenant that somehow
--    passes through both states can still receive each.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists card_trial_day3_sent      boolean default false;
alter table tenants add column if not exists card_trial_day6_sent      boolean default false;
alter table tenants add column if not exists card_trial_converted_sent boolean default false;
alter table tenants add column if not exists card_trial_failed_sent    boolean default false;

-- ---------------------------------------------------------------------------
-- 4) Index for the daily reminder sweep, which scans trialing tenants by end date.
-- ---------------------------------------------------------------------------
create index if not exists idx_tenants_stripe_trial_ends_at
  on tenants (stripe_trial_ends_at)
  where stripe_trial_ends_at is not null;
