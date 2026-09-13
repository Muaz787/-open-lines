-- ---------------------------------------------------------------------------
-- 034 — one Stripe Customer per signup attempt, decided before Stripe is called
--       (W9I-H.0.2)
--
-- WHAT /setup-card DOES TODAY
-- It calls stripe.Customer.create unconditionally, then SetupIntent.create, and
-- persists NOTHING. The only binding between a signup and its Customer is the
-- `card_setup_token` -- an encrypted blob handed to the browser. So:
--
--   * every call creates a NEW Customer. A customer who reloads the card step,
--     clicks "Try again", or comes back tomorrow leaves another one behind. The
--     frontend re-runs setup-card on mount, so this is the normal path, not an
--     edge case.
--   * nothing server-side can answer "which Customer belongs to this signup?".
--     At tenant creation we trust the token the client hands back.
--
-- WHY THIS CANNOT BE FIXED WITHOUT DURABLE STATE
-- Three provider-only strategies were considered and each fails a property the
-- gate requires:
--
--   * Customer.search on metadata -- Stripe documents search as EVENTUALLY
--     consistent. Two concurrent calls both find nothing and both create. That
--     is precisely the concurrency case that must not produce two Customers.
--   * A Stripe idempotency key alone -- correct for concurrent and same-day
--     retries, and retained for about 24 hours. A customer returning the next
--     day gets a second Customer.
--   * Both together -- covers most of it, and leans on eventual-consistency
--     search for exactly the long-window case the idempotency key cannot reach.
--     This workstream has been burned twice by assuming a provider read was
--     strongly consistent (W9C's credential scoping, W9H's FriendlyName filter
--     limit), and this is the same shape of assumption.
--
-- A durable row also buys something the token cannot: at tenant creation the
-- server can resolve the Customer from the onboarding key it already trusts,
-- instead of believing an identifier the client handed back.
--
-- THE ORDER IS CLAIM, THEN PROVIDER, THEN FENCED ATTACH -- the pattern W9H-QA.3
-- established after measuring two processes both crossing Address.create before
-- either owned a row:
--
--   insert (key, country, NULL)   the primary key elects one winner
--   -> Customer.create            with an idempotency key AND a metadata marker
--   -> fenced attach              WHERE stripe_customer_id IS NULL
--
-- A loser re-reads and uses the winner's Customer. A create whose response was
-- lost is recovered by retrying the same idempotency key inside its window, or
-- by the metadata marker outside it -- and if neither answers, the claim simply
-- stays unattached and the next attempt tries again. It never creates a second.
--
-- NOT A FOREIGN KEY TO TENANTS, and not nullable-tenant either: this row exists
-- BEFORE a tenant does, and most signups that reach the card step never become
-- one. The link is the onboarding_key, which migration 031 already made unique
-- on tenants.
-- ---------------------------------------------------------------------------

create table if not exists onboarding_payment_sessions (
    -- The signup attempt. Same identity the tenant claim and the Ireland pilot
    -- grant use, so one key names one signup everywhere.
    onboarding_key text primary key,

    -- The country this session was approved for, recorded at claim time.
    -- /setup-card now decides country access BEFORE creating anything (W9I-H.0.1
    -- did the same for /onboarding/provision), and this is the evidence of what
    -- was approved -- useful when a later provision arrives naming a different
    -- country.
    iso_country text not null,

    -- NULL until the provider call returns. That nullability is the whole point:
    -- the row is claimed BEFORE Stripe is touched, so two concurrent callers
    -- cannot both believe they are the creator.
    stripe_customer_id text null,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint ops_key_is_uuid_chk check (
        onboarding_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    constraint ops_country_chk check (iso_country ~ '^[A-Z]{2}$'),
    -- Stripe's own shape. Stops a malformed or spoofed value being attached and
    -- then handed to the billing path as though it were a real Customer.
    constraint ops_customer_shape_chk check (
        stripe_customer_id is null or stripe_customer_id ~ '^cus_[A-Za-z0-9]+$')
);

-- One Customer belongs to at most one signup. Without this, a bug that attached
-- the same Customer to two sessions would give two businesses one billing
-- identity -- and the first anyone would know is a charge on the wrong card.
create unique index if not exists ops_customer_key
    on onboarding_payment_sessions (stripe_customer_id)
    where stripe_customer_id is not null;

comment on table onboarding_payment_sessions is
    'W9I-H.0.2: binds one signup attempt (onboarding_key) to at most one Stripe '
    'Customer, claimed before the provider is called. Pre-tenant and short-lived '
    'by nature -- most rows belong to signups that never became tenants.';

comment on column onboarding_payment_sessions.stripe_customer_id is
    'NULL between the claim and the provider''s reply. A row that stays NULL is a '
    'create whose outcome was never confirmed; the next attempt reconciles it by '
    'idempotency key or metadata marker rather than creating a second Customer.';

-- RLS ON, NO POLICIES -- the shape every table added since 027 uses. Denied to
-- anon and authenticated, reachable only by service_role. A customer cannot read
-- another signup's Customer id, and cannot write their own.
alter table onboarding_payment_sessions enable row level security;

-- NO OTHER INDEX. Reads are by primary key, plus the unique index above which
-- exists for its constraint rather than for a query.

-- BACKFILL: none. Existing signups in flight hold a card_setup_token and are
-- unaffected: /setup-card keeps returning one, and provision keeps accepting it.
-- Sessions begin accumulating from the first call after this is live.
--
-- ABANDONED SIGNUPS: rows for signups that never become tenants are expected and
-- harmless -- an opaque key and a Stripe id, no personal data. No retention
-- period is encoded here, deliberately: choosing one would be inventing product
-- policy, and created_at supports any sweep a later decision calls for. The same
-- discipline as the temporary-number grace, which is also still undecided.
--
-- ---------------------------------------------------------------------------
-- Rollback:
--   drop table if exists onboarding_payment_sessions;
-- ---------------------------------------------------------------------------
