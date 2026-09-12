-- Migration: 028 — Requirement-drift durability + collected business details (W9G.1)
-- Run this in the Supabase SQL editor or via psql. Idempotent (safe to re-run).
--
-- SAFETY: ADDITIVE, IDEMPOTENT, NON-DESTRUCTIVE, DARK.
--   * two nullable columns on tenant_regulatory_profiles
--   * one new table
--   * no existing column is altered, retyped or dropped
--   * no rows written; all three regulatory tables are empty in production
--
-- ── WHY THIS EXISTS: TWO DEFECTS W9G SHIPPED ──────────────────────────────
--
-- 1. REQUIREMENT DRIFT WAS NOT DURABLE.
--    W9G computed a requirements fingerprint and returned it in an HTTP response
--    body. Nothing persisted it. The submit path the router actually calls compared
--    only regulation_sid, so Twilio could change a regulation's FIELD SHAPE under
--    the same SID -- which W9G's own design notes said it can -- and a submission
--    built on the old shape would have gone through. Comparing two in-memory
--    objects inside one request proves nothing across a restart, and the response
--    body is not storage. Hence requirements_fingerprint below.
--
-- 2. NOTHING COLLECTED FROM THE CUSTOMER WAS RECOVERABLE.
--    W9G forwarded the EndUser attribute bag to Twilio and stored none of it,
--    presented as PII minimisation. In practice it made the workflow unusable:
--    if EndUser.create failed, if the provider object later 404'd, if Twilio
--    rejected the filing and the CRO number needed correcting, or if a sibling
--    EndUser turned out inconsistent, there was nowhere to read the answers back
--    from and the customer had to retype everything. "Ask Twilio for it" only
--    works while Twilio has it and is reachable, which is exactly when it is not
--    needed. Hence tenant_regulatory_business_details.
--
-- ── WHAT IS DELIBERATELY *NOT* STORED ─────────────────────────────────────
--    No provider response blobs. No auth tokens. No document contents. No raw
--    callback bodies. Only the named answers a person typed, which are the same
--    values that must be shown back to them to be corrected.

-- ---------------------------------------------------------------------------
-- 1) Durable requirement identity on the profile.
--
--    regulation_sid alone is insufficient: Twilio can alter a regulation's
--    required fields without reissuing it, so the SID can be stable while the
--    obligation changes. The fingerprint is a sha256 over the normalised
--    requirement SHAPE -- field names and document types -- and contains no
--    customer data whatsoever, which is why it is safe to store and compare.
--
--    requirements_observed_at answers "as of when", so an operator looking at a
--    rejected filing can tell whether the requirements were months old.
-- ---------------------------------------------------------------------------
alter table tenant_regulatory_profiles
    add column if not exists requirements_fingerprint text null;
alter table tenant_regulatory_profiles
    add column if not exists requirements_observed_at timestamptz null;

do $$ begin
    alter table tenant_regulatory_profiles
        add constraint trp_requirements_fingerprint_chk
        check (requirements_fingerprint is null
               or requirements_fingerprint ~ '^[0-9a-f]{64}$');
exception when duplicate_object then null; end $$;

-- A profile that has reached the provider must know which requirement shape it
-- was built against. Draft states are exempt: nothing has been filed yet.
do $$ begin
    alter table tenant_regulatory_profiles
        add constraint trp_submitted_requirements_chk
        check (state not in ('pending_review', 'more_information_required',
                            'approved', 'rejected', 'number_provisioning', 'active')
               or requirements_fingerprint is not null);
exception when duplicate_object then null; end $$;

comment on column tenant_regulatory_profiles.requirements_fingerprint is
    'sha256 of the normalised requirement SHAPE (field names + document types) this profile was built against. Contains no customer data. Compared before submission to detect a provider requirement change under an unchanged regulation_sid.';

-- ---------------------------------------------------------------------------
-- 2) tenant_regulatory_business_details — the answers, so they can be shown back.
--
--    ONE ROW PER (tenant, country, end-user type), matching the EndUser scope
--    W9C established: EndUsers are reusable across a tenant's bundles, so the
--    answers behind them are too.
--
--    NAMED COLUMNS, NOT A JSON BAG. A blob would let a future provider field land
--    in untyped storage nobody reviewed, and personal data is exactly what should
--    not accumulate that way. If the Regulation API starts requiring a field with
--    no column here, the engine stops with unsupported_requirement_field rather
--    than inventing a home for it -- the same discipline already applied to an
--    unexpected document requirement.
--
--    WHY THESE ARE NOT READ FROM tenants. Related columns exist and are NOT
--    authoritative for a regulatory filing:
--      tenants.business_name  is the trading name; a filing needs the name as
--                             registered with the CRO, which may differ
--      tenants.website_url    is the analyzer's scrape target
--      tenants.email          is the account owner; the authorised representative
--                             must be a senior manager responsible for the
--                             numbers, who may be someone else
--      tenants.owner_name     likewise
--    Reading any of them would repeat the W9D/W9F mistake of treating an
--    adjacent value as an authority.
--
--    NOT ENCRYPTED, DELIBERATELY. The repository encrypts CREDENTIALS (Square
--    tokens, Vapi sub-org keys, routing destinations) and stores personal data in
--    plaintext behind RLS and the service role -- appointments.caller_name,
--    caller_phone, leads, tenants.email. An authorised representative's name and
--    email are of that second kind, and encrypting them here would introduce a
--    pattern the codebase does not have, break the operator review of a rejected
--    filing that is the whole point of storing them, and give no protection
--    against the threat that actually matters (service-role key compromise, which
--    also holds the encryption key). Protection is: RLS on, no policies, no
--    client path, never logged.
-- ---------------------------------------------------------------------------
create table if not exists tenant_regulatory_business_details (
    id            uuid        primary key default gen_random_uuid(),
    tenant_id     uuid        not null references tenants(id) on delete cascade,
    iso_country   text        not null,
    end_user_type text        not null default 'business',

    -- the business, as it must appear to a regulator
    business_name                text null,
    business_website             text null,
    business_registration_number text null,   -- CRO / RCN / public-body name

    -- the authorised representative: a senior manager responsible for the numbers
    authorized_rep_first_name text null,
    authorized_rep_last_name  text null,
    authorized_rep_email      text null,

    -- the compliance DECLARATION about the OpenLines/tenant relationship.
    -- Nullable on purpose and never defaulted: W9G.1 could not establish from
    -- Twilio's documentation which actor each field describes, so these stay
    -- empty until an operator answers them, and submission is blocked while they
    -- are. A guessed value here would be a false statement to a regulator.
    business_identity text null,
    is_subassigned    text null,

    comments text null,

    -- which requirement shape these answers were collected against
    requirements_fingerprint text null,
    collected_at timestamptz null,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint trbd_iso_chk check (iso_country ~ '^[A-Z]{2}$'),
    constraint trbd_fingerprint_chk check (requirements_fingerprint is null
        or requirements_fingerprint ~ '^[0-9a-f]{64}$'),
    -- Only the provider's own enumerated values, or nothing at all. This is what
    -- makes "unresolved" a distinguishable state rather than a typo.
    constraint trbd_business_identity_chk check (business_identity is null
        or business_identity in ('DIRECT_CUSTOMER', 'INDEPENDENT_SOFTWARE_VENDOR')),
    constraint trbd_is_subassigned_chk check (is_subassigned is null
        or is_subassigned in ('YES', 'NO')),
    constraint trbd_tenant_id_id_key unique (tenant_id, id)
);

-- One set of answers per tenant, country and end-user type -- the same scope as
-- the EndUser they build.
create unique index if not exists trbd_scope_key
    on tenant_regulatory_business_details (tenant_id, iso_country, end_user_type);

-- ---------------------------------------------------------------------------
-- 3) RLS: enabled, no policies -- the project convention. The backend uses the
--    service-role key (which bypasses RLS) and the frontend's anon client is used
--    only for supabase.auth, so there is no client read path to grant. With RLS on
--    and no policy, anon is denied by default. This table holds a named person's
--    contact details, so that default matters more here than anywhere else in the
--    schema.
-- ---------------------------------------------------------------------------
alter table tenant_regulatory_business_details enable row level security;

comment on table tenant_regulatory_business_details is
    'The answers a customer gave for a regulatory filing, kept so a failed create can be retried, a rejected filing corrected, and a lost provider object rebuilt -- without asking the customer to retype. Named columns only, never a provider blob. business_identity and is_subassigned are NULL until an operator resolves the declaration.';

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting).
--
-- Dropping the table loses collected answers and forces customers to retype;
-- dropping requirements_fingerprint re-opens the drift hole. Neither is required
-- for an application rollback, because both are additive and a pre-W9G.1 build
-- simply does not read them.
-- ===========================================================================
-- drop table if exists tenant_regulatory_business_details cascade;
-- alter table tenant_regulatory_profiles
--     drop constraint if exists trp_submitted_requirements_chk;
-- alter table tenant_regulatory_profiles
--     drop constraint if exists trp_requirements_fingerprint_chk;
-- alter table tenant_regulatory_profiles drop column if exists requirements_observed_at;
-- alter table tenant_regulatory_profiles drop column if exists requirements_fingerprint;
