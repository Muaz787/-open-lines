-- 038 — the difference between "not asked yet" and "asked, and declined"
-- (onboarding Gate B.1)
--
-- Two nullable timestamps. No data is rewritten, nothing is backfilled, and no
-- existing tenant's behaviour changes when this is applied.
--
-- WHY EXISTING STATE CANNOT CARRY THIS
-- The setup resolver reads "is a booking integration connected?" from the
-- provider tokens, and "were notification preferences chosen?" from
-- notification_prefs_set_at. Both are absences, and an absence cannot say
-- whether the customer was never offered the step or offered it and said no.
-- So a customer who skipped the calendar was returned to it on every refresh.
--
-- onboarding_state cannot hold this: migration 031 constrains it to
-- provisioning / regulatory_required / active, and it answers a different
-- question -- whether the tenant has a working line, not how far through setup
-- they clicked.
--
-- WHY notification_prefs_deferred_at IS SEPARATE FROM notification_prefs_set_at
-- They mean different things and are read by different code. `set` is a BILLING
-- AND DELIVERY fact: it moves a tenant from legacy dispatch semantics into
-- explicit ones, where every enabled channel must carry its own destination.
-- `deferred` is an ONBOARDING fact and nothing more. Collapsing them would
-- either move a deferring customer into explicit semantics with no destinations
-- configured, or make a deferral indistinguishable from an answer. The
-- dispatcher must never read the column below, and a test asserts it does not.
--
-- MONOTONIC. Neither column is ever cleared. A customer who skips and later
-- connects a calendar is complete because the TOKEN exists -- positive state
-- wins on its own, so nothing has to be unwound, and there is no ordering
-- between the two writes that could race.
--
-- ROLLBACK
--   Before the release that reads these columns, dropping them is structurally
--   reversible: they are empty and nothing depends on them. Afterwards they
--   hold a record of what customers actually chose, so removal would send
--   people who declined a step back to it. Forward fix from that point.
--
--   alter table tenants
--     drop column if exists booking_setup_skipped_at,
--     drop column if exists notification_prefs_deferred_at;

alter table tenants
    add column if not exists booking_setup_skipped_at       timestamptz null;

alter table tenants
    add column if not exists notification_prefs_deferred_at timestamptz null;

comment on column tenants.booking_setup_skipped_at is
    'Server-stamped when the customer explicitly skipped booking/calendar setup '
    'during onboarding. NULL means they have not been asked, or have not '
    'answered -- never that an integration failed or was unavailable. A '
    'connected integration counts as complete on its own, whatever this holds.';

comment on column tenants.notification_prefs_deferred_at is
    'Server-stamped when the customer explicitly deferred the call-summary '
    'preference step during onboarding. An ONBOARDING fact only: it does NOT '
    'set preferences, enable a channel, select Dashboard-only, or move the '
    'tenant out of legacy dispatch semantics. The notification dispatcher must '
    'never read it.';
