-- ---------------------------------------------------------------------------
-- 032 — one activation email per ACTIVATION, not per tenant (W9I-G)
--
-- SUPERSEDES A REJECTED DESIGN, AND THE REASON MATTERS
-- The first proposal put these timestamps on `tenants`. The checkpoint review
-- rejected it, correctly. A tenant can eventually REPLACE a +353 -- a reclaim, a
-- port, a re-filing after rejection -- and a tenant-global sent_at would suppress
-- the activation email for the replacement. The customer would be given a new
-- number and never told about it, and the bug would only appear the first time
-- somebody replaced a number, long after this was written.
--
-- The notification belongs to the ACTIVATION. An activation is one row in
-- tenant_phone_numbers. Scoping the state there makes a replacement's
-- notification lifecycle independent for free, because a replacement is a
-- different row -- and it gives the deterministic provider idempotency key a
-- naturally unique component, without anything having to remember to vary it.
--
-- WHY A MIGRATION AT ALL, WHEN THE LAST FIVE GATES NEEDED NONE
-- Three candidate needs were examined and only ONE survives:
--
--   * BILLING IDEMPOTENCY — not needed. services/subscriptions.py already passes
--     Stripe `idempotency_key=f"trial-sub-{tenant_id}"`, so concurrent creates
--     return the SAME subscription, and tenants.stripe_subscription_id records
--     it. The provider deduplicates, which is where that belongs.
--
--   * TEMPORARY RETIREMENT SCHEDULE — not needed. 027 already carries
--     retiring_since and released_at, and W9I-G does not choose a grace
--     DURATION: that stays an unresolved product decision, and a deadline column
--     would invite one to be invented to fill it.
--
--   * ACTIVATION NOTIFICATION — needed. There is no tenant-email outbox and no
--     column for this message. The repository's existing pattern for lifecycle
--     email (services/trial.py) is send-then-set-a-boolean: correct on a
--     once-daily cron where a duplicate is bounded, wrong here, where two
--     activation workers can be in flight in the same second.
--
-- WHAT THESE THREE COLUMNS BUY, AND WHAT THEY DO NOT
-- The DB claim stops two CONCURRENT workers becoming two email events. The
-- provider's Idempotency-Key stops one event becoming two DELIVERED emails --
-- measured, not assumed: resend 2.44.0 turns options={"idempotency_key": ...}
-- into the Idempotency-Key header on POST /emails.
--
-- Together they cover the crash window. A worker that dies between claiming and
-- confirming leaves a claim with no send; a later worker may take it over and
-- retry with the SAME key and the SAME body, and the provider returns the
-- original instead of delivering again.
--
-- The edge is the provider's memory. Resend retains a key for about 24 hours, so
-- a claim older than that is NOT retried automatically -- it becomes a review
-- state. That rule lives in services/activation_notification.py, beside the
-- other claim leases, because it is a property of the provider rather than of
-- the schema.
--
-- provider_id is kept because it is the only handle an operator has on the
-- actual send when reconciling a lost acknowledgement. Without it, "did this
-- email go out?" has no answer anywhere.
--
-- Idempotent: add column if not exists, and each constraint is added only when
-- absent, so replaying this file is a no-op.
-- ---------------------------------------------------------------------------

alter table tenant_phone_numbers
    add column if not exists activation_email_claimed_at  timestamptz null,
    add column if not exists activation_email_sent_at     timestamptz null,
    add column if not exists activation_email_provider_id text        null;

comment on column tenant_phone_numbers.activation_email_claimed_at is
    'W9I-G: one worker has taken responsibility for sending this activation''s '
    'email. Set by a fenced UPDATE matching only an unclaimed row, so exactly '
    'one concurrent worker proceeds. An unconfirmed claim younger than the mail '
    'provider''s idempotency window may be taken over; an older one must not be, '
    'and becomes a review state instead.';

comment on column tenant_phone_numbers.activation_email_sent_at is
    'W9I-G: the mail provider accepted this activation''s email. Once set, no '
    'later run sends it again for this phone row. A REPLACEMENT number is a '
    'different row and is announced on its own.';

comment on column tenant_phone_numbers.activation_email_provider_id is
    'W9I-G: the mail provider''s id for the accepted send. The only handle an '
    'operator has on the actual message when reconciling a lost acknowledgement.';

-- A send cannot exist without the claim that authorised it. This is what stops a
-- future caller setting sent_at directly and skipping the fence: the only route
-- to a confirmed send is through a claim somebody won.
do $$
begin
    if not exists (select 1 from pg_constraint
                    where conname = 'tpn_activation_email_claim_chk') then
        alter table tenant_phone_numbers
            add constraint tpn_activation_email_claim_chk
            check (activation_email_sent_at is null
                   or activation_email_claimed_at is not null);
    end if;
end $$;

-- A provider id is evidence of a send, so it cannot exist without one. Prevents
-- a half-written recovery leaving an id attached to an activation whose books
-- say nothing was ever sent.
do $$
begin
    if not exists (select 1 from pg_constraint
                    where conname = 'tpn_activation_email_provider_chk') then
        alter table tenant_phone_numbers
            add constraint tpn_activation_email_provider_chk
            check (activation_email_provider_id is null
                   or activation_email_sent_at is not null);
    end if;
end $$;

-- NO INDEX. Every read and write is by the phone row's primary key -- the
-- activation path always knows which row it is acting on -- and the table holds
-- seven rows in production. An index here would tax every phone-row write to
-- serve a query nobody makes. If a future reconciliation sweep ever scans for
-- unconfirmed claims, it can be added then, with the query that justifies it.

-- NO RLS CHANGE. tenant_phone_numbers already has row-level security enabled
-- with no policies (migration 027), so it is denied to anon and authenticated
-- and reachable only by service_role. Adding columns does not alter that, and
-- this migration deliberately does not touch table-level policy.

-- BACKFILL: none, deliberately. Existing rows get NULL/NULL/NULL, which reads as
-- "never claimed, never sent". That is accurate -- they predate this mechanism
-- -- and it is safe because nothing sweeps for unsent activations: the email is
-- only ever attempted by the Ireland activation path, for a row it has just
-- promoted. Stamping a fabricated sent_at on the seven existing CA/US rows to
-- make them "look done" would be inventing history to satisfy a query that does
-- not exist.

-- ---------------------------------------------------------------------------
-- Rollback. Dropping these re-opens the duplicate-email hole under concurrency,
-- so it is written down rather than made convenient:
--
--   alter table tenant_phone_numbers
--       drop constraint if exists tpn_activation_email_provider_chk,
--       drop constraint if exists tpn_activation_email_claim_chk;
--   alter table tenant_phone_numbers
--       drop column if exists activation_email_provider_id,
--       drop column if exists activation_email_sent_at,
--       drop column if exists activation_email_claimed_at;
-- ---------------------------------------------------------------------------
