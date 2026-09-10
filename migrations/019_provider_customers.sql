-- W6B — OpenLines owns caller -> provider-customer identity.
--
-- Square's customer SEARCH index is eventually consistent; GET by id is not.
-- Two rapid resolutions for one phone therefore both miss and both create. That
-- is not theoretical: a W5.2 probe produced two customers for one caller.
--
-- PostgreSQL advisory locks are unavailable through this repository's PostgREST
-- data layer, so uniqueness IS the lock. claim_token is what makes ownership of
-- an unfinished claim provable rather than merely likely -- provider_customer_id
-- being NULL says the mapping is unfinished, not who is allowed to finish it.
--
-- The row's own id is the stable Square idempotency identity: it exists before
-- the provider call and is untouched by takeover. claim_token must never be used
-- for that, because it changes hands.

create table if not exists provider_customers (
    id                   uuid        primary key default gen_random_uuid(),
    tenant_id            uuid        not null references tenants(id) on delete cascade,
    provider             text        not null default 'square',
    -- Trusted E.164 only. Never telephony.normalize_phone(), which infers +1
    -- from a 10-digit string and would turn an Irish number into a US one.
    normalized_phone     text        not null,

    -- NULL here IS the claim. Nullable by design.
    provider_customer_id text        null,
    provider_merchant_id text        null,

    claim_token          uuid        null,
    claimed_at           timestamptz not null default now(),

    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

-- The concurrency mechanism: elects exactly one claim winner per
-- (tenant, provider, phone). Keyed per tenant -- the same phone legitimately
-- exists across tenants.
create unique index if not exists provider_customers_phone_key
    on provider_customers (tenant_id, provider, normalized_phone);

-- One Square customer maps to one row. Partial, so claims in flight (NULL id)
-- never collide with each other.
create unique index if not exists provider_customers_provider_key
    on provider_customers (tenant_id, provider, provider_customer_id)
    where provider_customer_id is not null;

-- Small partial index over only the claims still in flight, for stale sweeps.
create index if not exists provider_customers_unfinished_claim_idx
    on provider_customers (claimed_at)
    where provider_customer_id is null;

alter table provider_customers enable row level security;
