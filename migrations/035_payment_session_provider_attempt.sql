-- ---------------------------------------------------------------------------
-- 035 — tell "never called Stripe" apart from "called Stripe, outcome unknown"
--       (W9I-H.0.2R)
--
-- WHAT 034 GOT RIGHT, AND WHAT IT CANNOT SAY
-- 034 binds one signup to at most one Stripe Customer and elects a single
-- creator by primary key. Verified live: 19/19. What it cannot express is the
-- difference between two situations that look identical in its columns --
-- a row with stripe_customer_id NULL:
--
--   (2) the claim was taken and Stripe was NEVER called
--   (4) Stripe WAS called and the answer never came back
--
-- Those need opposite treatment. (2) is provably safe to retry. (4) may already
-- have created a Customer, and retrying it after Stripe has forgotten the
-- idempotency key produces a second billing identity for one business.
--
-- THE CORRECTION THIS MIGRATION EXISTS FOR
-- An earlier report of mine claimed: "if neither idempotency recovery nor the
-- metadata lookup answers, the claim stays NULL and the next attempt retries --
-- it never creates a second." That is wrong, and the checkpoint review was right
-- to reject it. ABSENCE OF POSITIVE RECONCILIATION IS NOT PROOF THAT
-- CUSTOMER.CREATE FAILED. Search can return zero because it is eventually
-- consistent, or because it is unavailable, or because the query could not run.
-- None of those mean the Customer does not exist.
--
-- WITHOUT THIS COLUMN the only safe implementation is to treat EVERY unattached
-- claim as ambiguous and never create again -- which is correct, and turns any
-- crash between the claim and the attach into a permanently wedged signup, even
-- when the crash provably happened before Stripe was touched. That is a silent
-- conversion loss, and an operator review for a case we could simply have
-- distinguished.
--
-- WHAT THIS IS NOT
-- It is not a lease timer, and nothing here authorizes a create because time
-- passed. It records that an attempt was INITIATED. The rule it enables is:
--
--   provider_attempt_at IS NULL   -> Stripe was never called. A stale claim may
--                                    be retaken, because "never attempted" is
--                                    proved rather than assumed.
--   provider_attempt_at IS NOT NULL
--     and customer IS NULL        -> outcome unknown. NEVER create again.
--                                    Reconcile by idempotency key or metadata;
--                                    if neither positively identifies a
--                                    Customer, this is an operator's problem,
--                                    not a retry's.
--   customer IS NOT NULL          -> attached. Always reuse.
--
-- State 4 has no automatic route back to state 1. Deliberately: a rare operator
-- review is preferable to permanent duplicate billing identities.
-- ---------------------------------------------------------------------------

alter table onboarding_payment_sessions
    add column if not exists provider_attempt_at timestamptz null;

comment on column onboarding_payment_sessions.provider_attempt_at is
    'W9I-H.0.2R: set immediately BEFORE calling stripe.Customer.create, and never '
    'cleared. NULL proves Stripe was never called for this session, which is the '
    'only condition under which a stale claim may be retaken. Set with a NULL '
    'stripe_customer_id means the outcome is unknown and no further create may be '
    'attempted automatically.';

-- A recorded Customer cannot exist without the attempt that produced it. This is
-- what makes the marker impossible to skip: no code path can attach a Customer
-- while leaving the session looking like Stripe was never called, so the "safe
-- to retake" condition can never be reached by a session that already has one.
do $$
begin
    if not exists (select 1 from pg_constraint
                    where conname = 'ops_attach_implies_attempt_chk') then
        alter table onboarding_payment_sessions
            add constraint ops_attach_implies_attempt_chk
            check (stripe_customer_id is null or provider_attempt_at is not null);
    end if;
end $$;

-- NO INDEX. Every read is by primary key. A future reconciliation sweep looking
-- for unresolved attempts can add its own, with the query that justifies it.

-- NO RLS CHANGE. 034 enabled row-level security with no policies; adding a
-- column does not alter that.

-- BACKFILL: none needed. 034 is live and the table is empty -- verified 19/19
-- against production before this was written -- so there is no existing row
-- whose history would have to be guessed at. Had there been, the honest value
-- would have been NULL only for rows with no customer, and this migration would
-- have had to say so rather than assume.

-- ---------------------------------------------------------------------------
-- Rollback. Dropping this re-opens the gap between "never called" and "outcome
-- unknown", so it is written down rather than made convenient:
--
--   alter table onboarding_payment_sessions
--       drop constraint if exists ops_attach_implies_attempt_chk;
--   alter table onboarding_payment_sessions
--       drop column if exists provider_attempt_at;
-- ---------------------------------------------------------------------------
