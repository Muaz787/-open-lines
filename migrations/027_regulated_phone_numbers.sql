-- Migration: 027 — Regulated phone numbers + Ireland regulatory foundation (W9D)
-- Run this in the Supabase SQL editor or via psql. Idempotent (safe to re-run).
--
-- SAFETY: ADDITIVE, IDEMPOTENT, NON-DESTRUCTIVE, DARK.
--   * one nullable column is added to tenants; nothing existing is altered,
--     retyped or dropped
--   * four new tables, unread by the application except the inbound-lookup path
--     added in W9D, which falls back to the scalar and therefore behaves
--     identically while these tables are empty
--   * NO rows are written here. The backfill lives in
--     backend/services/phone_backfill.py so the test suite can reach it —
--     migration 012's precedent, for the same reason: SQL in a migration file is
--     a second implementation no test can run.
--
-- THE AUTHORITATIVE SOURCES ARE UNCHANGED BY THIS MIGRATION:
--     tenants.twilio_phone_number   still the mirror inbound routing falls back to
--     tenants.twilio_subaccount_sid still the provider account of record
--     tenants.country               still the analyzer's guess, and STILL NOT
--                                   compliance authority — that is what
--                                   business_country_code below is for
--
-- ── PROVIDER EVIDENCE THIS SCHEMA IS BUILT ON (W9C, all measured) ──────────
--  1. Twilio regulatory objects are ACCOUNT-SCOPED. A sub-account purchase
--     resolved its own bundle ("status is not twilio-approved") and reported the
--     parent's as "Bundle not found"; fetching a parent bundle or end user under
--     sub-account credentials returns 404/20404; assigning a parent EndUser into
--     a sub-account bundle returns 70002. Hence provider_account_sid on every
--     table that holds a provider SID: a SID is only meaningful with its account.
--  2. Ireland Local/Business needs 9 EndUser fields and exactly one
--     business_address SupportingDocument, which is satisfied by an Address SID —
--     no uploaded document. So no document contents are stored anywhere here.
--  3. Irish Address creation HARD-VALIDATES: a synthetic street failed 21628, and
--     a real street without an Eircode failed 21628 too. A validated address is a
--     precondition, not a formality — hence `validated` and `validation_error`.
--  4. ONE effective address per bundle. Two address SIDs in one document store
--     fine but reproducibly 500 on Evaluation (5 attempts); two business_address
--     documents in one bundle are rejected 70002. Hence one profile per address.
--  5. Purchase validates the AddressSid against the NUMBER'S OWN accepted
--     locality set (21615), independently of the bundle's approval (21649).
--  6. Twilio's search `locality` is NOT that set: a number labelled "Dublin"
--     demanded Celbridge/Leixlip/Lucan/Maynooth/…. Provider normalisation also
--     rewrites city ("Wood Quay, Dublin" -> "Dublin 8"). THEREFORE LOCALITY TEXT
--     IS METADATA AND NEVER IDENTITY — see the profile table.

-- ---------------------------------------------------------------------------
-- 1) tenants.business_country_code — the ONLY compliance country authority.
--
--    NOT tenants.country: that is derived by the website analyzer and is NULL for
--    3 of 11 production tenants, two of which hold a live number. A regulator's
--    question ("who is this and where are they") may not be answered by a scrape.
--    NOT the billing country, NOT Square's country.
--
--    text + CHECK rather than char(2): the repository has no char(n) column
--    anywhere and tenant_locations.country is already text. Consistency beats two
--    characters of storage.
--
--    Nullable: legacy tenants have never been asked. The requirement is enforced
--    by the provisioning path when it needs it, not by the column.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists business_country_code text null;

do $$ begin
    alter table tenants add constraint tenants_business_country_code_chk
        check (business_country_code is null
               or business_country_code ~ '^[A-Z]{2}$');
exception when duplicate_object then null; end $$;

comment on column tenants.business_country_code is 'Explicitly confirmed ISO-3166-1 alpha-2 country of the business. The ONLY compliance authority. Never tenants.country (analyzer-derived), never the billing country, never Square''s country.';

-- ---------------------------------------------------------------------------
-- 2) Composite ownership keys.
--
--    A plain FK to tenant_locations(id) proves the location exists. It does NOT
--    prove the location belongs to the SAME tenant as the referencing row, which
--    is the invariant that matters: a cross-tenant location binding would leak one
--    customer's premises into another's regulatory filing.
--
--    id is already the primary key, so this unique constraint can never fail on
--    existing data — it exists only so child tables can reference (tenant_id, id)
--    and have Postgres prove co-ownership.
-- ---------------------------------------------------------------------------
do $$ begin
    alter table tenant_locations
        add constraint tenant_locations_tenant_id_id_key unique (tenant_id, id);
exception when duplicate_object then null; when duplicate_table then null; end $$;

-- ---------------------------------------------------------------------------
-- 3) tenant_regulatory_addresses — a Twilio Address and its SupportingDocument.
--
--    WHY ONE TABLE FOR BOTH: because the provider makes them 1:1. A
--    business_address document carries exactly one usable address (evidence 4),
--    and a bundle refuses a second such document. Two tables would model a
--    cardinality Twilio does not have, and would invite a "which document holds
--    this address" query that can only ever have one answer.
--
--    NOT ONE ADDRESS PER CITY. A tenant may legitimately hold two Dublin premises
--    with different Eircodes; a regulated number for each needs an address for
--    each. Identity is therefore the BUSINESS LOCATION, not the city name:
--      * tenant_location_id present -> one regulatory address per location,
--        country and provider
--      * tenant_location_id null    -> one tenant-level (head-office) address per
--        country and provider, for single-site tenants that have no location row
--        of their own worth pointing at
--    locality/city are last-seen provider normalisation, kept for display and
--    diagnosis only. Nothing keys on them.
--
--    The submitted fields are stored so a re-validation, a resubmission after a
--    rejection, or a move of premises never has to interrogate the customer
--    again. Document CONTENTS are never stored — on the Irish path none exist.
-- ---------------------------------------------------------------------------
create table if not exists tenant_regulatory_addresses (
    id                      uuid        primary key default gen_random_uuid(),
    tenant_id               uuid        not null references tenants(id) on delete cascade,
    tenant_location_id      uuid        null,
    provider                text        not null default 'twilio',
    provider_account_sid    text        null,   -- identity metadata. NEVER a token.
    iso_country             text        not null,
    address_sid             text        null,   -- Twilio Address SID
    supporting_document_sid text        null,   -- the business_address document
    validated               boolean     not null default false,
    validation_error        text        null,
    -- what we submitted, verbatim, so nothing has to be asked twice
    customer_name    text null,
    street           text null,
    street_secondary text null,
    city             text null,
    region           text null,
    postal_code      text null,              -- Eircode for IE, where it is required
    -- last-seen provider normalisation. METADATA. Never identity, never a key.
    provider_locality text null,             -- e.g. 'Dublin 8' for 'Wood Quay, Dublin'
    provider_region   text null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint tra_iso_chk      check (iso_country ~ '^[A-Z]{2}$'),
    constraint tra_provider_chk check (provider in ('twilio')),
    -- A validated address MUST name the provider object that validated it, and a
    -- provider object is meaningless without the account that holds it. Draft
    -- rows (nothing created at the provider yet) are deliberately exempt.
    constraint tra_validated_identity_chk check (
        validated is false
        or (address_sid is not null and provider_account_sid is not null)),
    -- so profiles can prove co-ownership
    constraint tra_tenant_id_id_key unique (tenant_id, id),
    -- NO ACTION (the default), not RESTRICT: NO ACTION is checked at end of
    -- statement, so deleting a tenant — which cascades to both the locations and
    -- these rows in one statement — still succeeds, while deleting a single
    -- location that a regulatory address still points at correctly fails rather
    -- than silently detaching a filed address.
    constraint tra_location_owner_fk
        foreign key (tenant_id, tenant_location_id)
        references tenant_locations (tenant_id, id)
);

-- One regulatory address per business location, per country, per provider.
create unique index if not exists tra_location_scope_key
    on tenant_regulatory_addresses (tenant_id, provider, iso_country, tenant_location_id)
    where tenant_location_id is not null;

-- One tenant-level address per country, per provider, for tenants that pin no
-- location. Separate partial index because a NULL never conflicts in a unique
-- index, so the index above cannot express this case at all.
create unique index if not exists tra_tenant_scope_key
    on tenant_regulatory_addresses (tenant_id, provider, iso_country)
    where tenant_location_id is null;

-- A SID is unique WITHIN the account that holds it. Scoped by account rather than
-- global because that is the provider's actual namespace (evidence 1), and
-- because a future clone into another account legitimately duplicates neither.
create unique index if not exists tra_address_sid_key
    on tenant_regulatory_addresses (provider, provider_account_sid, address_sid)
    where address_sid is not null;

create unique index if not exists tra_document_sid_key
    on tenant_regulatory_addresses (provider, provider_account_sid, supporting_document_sid)
    where supporting_document_sid is not null;

create index if not exists tra_tenant_idx
    on tenant_regulatory_addresses (tenant_id, iso_country);

-- ---------------------------------------------------------------------------
-- 4) tenant_regulatory_profiles — one row per Twilio Bundle workflow.
--
--    IDENTITY IS THE REGULATORY ADDRESS, NOT A LOCALITY STRING.
--    An earlier draft keyed this on (tenant, country, number_type, locality_text).
--    W9C killed that: Twilio's search locality is not the locality the address
--    must satisfy (evidence 5, 6), and provider normalisation rewrites the string
--    anyway. A workflow's durable identity is the address that actually satisfies
--    compliance — a row in this database with a foreign key — so that is the key.
--
--      regulatory_address_id NOT NULL -> an address-scoped workflow (Ireland local)
--      regulatory_address_id NULL     -> a country-wide workflow, for regulations
--                                        that need no local address
--
--    Two partial unique indexes rather than one index over a magic '' scope key:
--    NULL already means "no address", and inventing an empty string to stand in
--    for it would be a second, weaker spelling of the same fact.
--
--    state is OURS. bundle_status is TWILIO'S, verbatim. Deliberately two columns:
--    our vocabulary must never have to track theirs, and theirs must never be
--    paraphrased. Note what is ABSENT from the state CHECK: provisionally_approved.
--    The SDK has the enum, Twilio's documented status table does not list it, and
--    a purchase rejection read "status is not twilio-approved". An undocumented
--    enum name is not a licence to provision, so a bundle sitting in that provider
--    status stays in OUR state pending_review while bundle_status records it
--    exactly. If Twilio later documents it as purchasable, that is a code change,
--    not a migration.
-- ---------------------------------------------------------------------------
create table if not exists tenant_regulatory_profiles (
    id                    uuid        primary key default gen_random_uuid(),
    tenant_id             uuid        not null references tenants(id) on delete cascade,
    tenant_location_id    uuid        null,
    regulatory_address_id uuid        null,
    provider              text        not null default 'twilio',
    provider_account_sid  text        null,
    iso_country           text        not null,
    number_type           text        not null default 'local',
    end_user_type         text        not null default 'business',
    regulation_sid        text        null,   -- WHICH regulation this was built for
    regulation_friendly_name text     null,   -- last seen, for diagnosis
    bundle_sid            text        null,
    end_user_sid          text        null,   -- shared across a tenant's siblings
    state                 text        not null default 'not_started',
    bundle_status         text        null,   -- Twilio's own value, verbatim
    evaluation_status     text        null,   -- 'compliant' | 'noncompliant'
    failure_code          text        null,
    failure_reason        text        null,   -- never logged verbatim
    submitted_at          timestamptz null,
    decided_at            timestamptz null,
    valid_until           timestamptz null,   -- Twilio's ValidUntil
    attempts              int         not null default 0,
    last_synced_at        timestamptz null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint trp_iso_chk       check (iso_country ~ '^[A-Z]{2}$'),
    constraint trp_provider_chk  check (provider in ('twilio')),
    constraint trp_attempts_chk  check (attempts >= 0),
    constraint trp_state_chk     check (state in (
        'not_started',                -- nothing collected
        'details_required',           -- requirements discovered, awaiting the customer
        'address_validation_failed',  -- Twilio refused the address (21628)
        'ready_to_submit',            -- evaluation compliant, not yet submitted
        'submitting',                 -- submit in flight
        'pending_review',             -- with Twilio. Also where provisionally-approved sits.
        'more_information_required',  -- Twilio asked for a correction
        'approved',                   -- twilio-approved: purchase permitted
        'rejected',                   -- twilio-rejected
        'number_provisioning',        -- buying / configuring the number
        'active',                     -- number live against this profile
        'failed')),
    -- A bundle SID is only meaningful with the account that holds it.
    constraint trp_bundle_account_chk check
        (bundle_sid is null or provider_account_sid is not null),
    -- Once the workflow has reached the provider, it must name its bundle. Draft
    -- states are exempt: nothing exists at the provider yet.
    constraint trp_submitted_identity_chk check (
        state not in ('pending_review', 'more_information_required', 'approved',
                      'rejected', 'number_provisioning', 'active')
        or bundle_sid is not null),
    constraint trp_tenant_id_id_key unique (tenant_id, id),
    constraint trp_location_owner_fk
        foreign key (tenant_id, tenant_location_id)
        references tenant_locations (tenant_id, id),
    -- THE CROSS-TENANT GUARD. A plain FK to tenant_regulatory_addresses(id) would
    -- have let tenant A's profile cite tenant B's validated premises.
    constraint trp_address_owner_fk
        foreign key (tenant_id, regulatory_address_id)
        references tenant_regulatory_addresses (tenant_id, id)
);

-- One country-wide workflow per tenant, country, number type and end-user type.
create unique index if not exists trp_country_scope_key
    on tenant_regulatory_profiles
       (tenant_id, iso_country, number_type, end_user_type)
    where regulatory_address_id is null;

-- One address-scoped workflow per address. This is what lets Dublin, Cork and
-- Limerick coexist: three addresses, three profiles, no naming collision, and no
-- dependence on what Twilio decides to call the locality this week.
create unique index if not exists trp_address_scope_key
    on tenant_regulatory_profiles
       (tenant_id, iso_country, number_type, end_user_type, regulatory_address_id)
    where regulatory_address_id is not null;

-- THIS INDEX IS WHAT MAKES THE STATUS CALLBACK SAFE. Twilio's callback carries
-- AccountSid, BundleSid, Status and FailureReason — and no tenant of ours. The
-- tenant is therefore looked up FROM the bundle SID, never from anything the
-- caller sends. Global rather than account-scoped on purpose: a bundle lives in
-- exactly one Twilio account, which belongs to exactly one tenant, so two
-- profiles claiming one bundle SID is always corruption.
create unique index if not exists trp_bundle_sid_key
    on tenant_regulatory_profiles (bundle_sid)
    where bundle_sid is not null;

-- The reconciliation sweep reads only non-terminal profiles. Terminal ones
-- (approved / rejected / active / failed) are never polled again.
create index if not exists trp_nonterminal_idx
    on tenant_regulatory_profiles (state, last_synced_at)
    where state in ('submitting', 'pending_review', 'more_information_required',
                    'number_provisioning');

create index if not exists trp_tenant_idx
    on tenant_regulatory_profiles (tenant_id, iso_country, number_type);

-- ---------------------------------------------------------------------------
-- 5) tenant_phone_numbers — every number a tenant holds, and why.
--
--    PURPOSE AND STATUS ARE SEPARATE COLUMNS, and the split is not cosmetic. With
--    one `role` column, temporary_test and primary_active were alternative values
--    of the same field, so no index could constrain them independently and "at
--    most one temporary test number" was inexpressible. Splitting them makes both
--    invariants a one-line partial index each.
--
--    THE TWO LIFECYCLE POLICIES DIFFER ON PURPOSE:
--      permanent      — one CURRENT (provisioning|active). A retiring predecessor
--                       may coexist, because replacing a number requires the old
--                       one to keep ringing through its grace period.
--      temporary_test — one, full stop, across provisioning|active|retiring. A
--                       test number has no replacement story: it exists until the
--                       permanent arrives, then retires and is released. Allowing
--                       a retiring temporary alongside a new active one would let
--                       a tenant accumulate rented numbers for free, which is a
--                       billing leak dressed as a lifecycle.
-- ---------------------------------------------------------------------------
create table if not exists tenant_phone_numbers (
    id                    uuid        primary key default gen_random_uuid(),
    tenant_id             uuid        not null references tenants(id) on delete cascade,
    tenant_location_id    uuid        null,
    regulatory_profile_id uuid        null,
    e164                  text        not null,
    purpose               text        not null,
    status                text        not null,
    provider              text        not null default 'twilio',
    provider_account_sid  text        null,   -- the Twilio (sub)account that owns it
    provider_sid          text        null,   -- IncomingPhoneNumber SID
    iso_country           text        null,   -- null = legacy, never reconstructed
    vapi_phone_number_id  text        null,
    activated_at          timestamptz null,
    activated_at_source   text        null,   -- provenance. See the CHECK below.
    retiring_since        timestamptz null,
    released_at           timestamptz null,
    last_error            text        null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint tpn_purpose_chk  check (purpose in ('temporary_test', 'permanent')),
    constraint tpn_status_chk   check (status in
        ('provisioning', 'active', 'retiring', 'released', 'failed')),
    constraint tpn_e164_chk     check (e164 ~ '^\+[1-9][0-9]{6,14}$'),
    constraint tpn_iso_chk      check (iso_country is null or iso_country ~ '^[A-Z]{2}$'),
    constraint tpn_provider_chk check (provider in ('twilio')),
    -- activated_at must say where it came from, so a backfilled guess can never
    -- be mistaken for an observed activation. 'tenant_created_at' is deliberately
    -- NOT an allowed value: tenant creation is not phone activation, and the
    -- backfill writes NULL rather than inventing history.
    constraint tpn_activated_source_chk check (
        (activated_at is null and activated_at_source is null)
        or activated_at_source in ('provider_date_created', 'promotion')),
    -- A number we can route a call to must name the provider object it IS, and
    -- the account that owns it. Anything else is a live number with unknown
    -- ownership, which is exactly the state that makes a release unsafe.
    constraint tpn_live_identity_chk check (
        status not in ('active', 'retiring')
        or (provider_sid is not null and provider_account_sid is not null)),
    constraint tpn_tenant_id_id_key unique (tenant_id, id),
    constraint tpn_location_owner_fk
        foreign key (tenant_id, tenant_location_id)
        references tenant_locations (tenant_id, id),
    constraint tpn_profile_owner_fk
        foreign key (tenant_id, regulatory_profile_id)
        references tenant_regulatory_profiles (tenant_id, id)
);

-- One CURRENT permanent number per tenant. Includes 'provisioning', which is what
-- makes a retried promotion idempotent: the second attempt cannot insert a second
-- row, so it cannot buy or import a second number.
create unique index if not exists tpn_one_current_permanent
    on tenant_phone_numbers (tenant_id)
    where purpose = 'permanent' and status in ('provisioning', 'active');

-- One temporary test number per tenant, INCLUDING while it retires.
create unique index if not exists tpn_one_live_temporary
    on tenant_phone_numbers (tenant_id)
    where purpose = 'temporary_test'
      and status in ('provisioning', 'active', 'retiring');

-- A number we currently own belongs to exactly one tenant. 'released' and
-- 'failed' are EXCLUDED deliberately: a released number must be re-purchasable
-- later (by us or anyone), and a failed purchase must not squat an E.164 we never
-- owned. (This index also serves the equality lookup inbound routing does, so
-- there is no second index on e164.)
create unique index if not exists tpn_owned_e164_key
    on tenant_phone_numbers (e164)
    where status in ('provisioning', 'active', 'retiring');

-- One row per provider object, within the account that holds it.
create unique index if not exists tpn_provider_object_key
    on tenant_phone_numbers (provider, provider_account_sid, provider_sid)
    where provider_sid is not null;

create index if not exists tpn_tenant_idx
    on tenant_phone_numbers (tenant_id, purpose, status);

-- ---------------------------------------------------------------------------
-- 6) tenant_regulatory_events — the durable callback ledger.
--
--    NOT provider_webhook_events. That table is `check (provider in ('square'))`,
--    its columns are Square-shaped (merchant_id, object_type, provider_version),
--    and its dedup key is (provider, provider_event_id) — but Twilio's regulatory
--    callback carries NO event id at all: AccountSid, BundleSid, Status,
--    FailureReason. Forcing it in would mean widening a CHECK, leaving a required
--    column permanently empty, and distorting the Square ledger's semantics for a
--    payload that cannot satisfy its key.
--
--    WHY A FINGERPRINT AND AN OCCURRENCE, NOT (bundle_sid, status).
--    A bundle can legitimately reach the same status twice:
--        pending-review -> twilio-rejected -> (corrected) -> pending-review -> ...
--    Keying on status alone would collapse the second, genuine pending-review into
--    the first and lose the transition. But keying on nothing would turn every
--    HTTP retry of one transition into a new row. So:
--        fingerprint = hash of the canonical callback fields (bundle, status,
--                      failure reason, valid_until) — identifies the CONTENT
--        occurrence  = which time this content has been seen
--    A redelivery matches the fingerprint of the LATEST row for that bundle and
--    increments delivery_count. A recurrence after the bundle moved elsewhere does
--    not match the latest row, so it lands as occurrence + 1. A changed failure
--    reason changes the fingerprint, so corrections are never silently lost.
--    No OpenLines-side timestamp takes part in identity.
--
--    The raw request body is deliberately NOT stored. FailureReason IS stored in
--    its own column, because the customer has to be told what to correct -- but as
--    a named field we can redact in logs, not as an opaque blob that would also
--    carry Email and whatever else Twilio adds to the form later.
-- ---------------------------------------------------------------------------
create table if not exists tenant_regulatory_events (
    id                    uuid        primary key default gen_random_uuid(),
    provider              text        not null default 'twilio',
    provider_account_sid  text        null,   -- callback's AccountSid, as received
    bundle_sid            text        not null,
    bundle_status         text        not null,  -- Twilio's value, verbatim
    fingerprint           text        not null,  -- sha256 hex of canonical fields
    occurrence            int         not null default 1,
    tenant_id             uuid        null references tenants(id) on delete set null,
    regulatory_profile_id uuid        null,
    failure_reason        text        null,
    valid_until           timestamptz null,
    signature_valid       boolean     not null,
    applied               boolean     not null default false,
    apply_detail          text        null,
    delivery_count        int         not null default 1,
    first_received_at timestamptz not null default now(),
    last_received_at  timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint tre_provider_chk    check (provider in ('twilio')),
    constraint tre_delivery_chk    check (delivery_count >= 1),
    constraint tre_occurrence_chk  check (occurrence >= 1),
    constraint tre_fingerprint_chk check (fingerprint ~ '^[0-9a-f]{64}$'),
    -- A resolved profile implies a resolved tenant. Without this, the composite FK
    -- below is silently skipped (MATCH SIMPLE ignores a row with any NULL key
    -- column), which is precisely how "tenant A, tenant B's profile" would slip in.
    constraint tre_profile_needs_tenant_chk check
        (regulatory_profile_id is null or tenant_id is not null),
    -- ON DELETE SET NULL clears BOTH columns together, so a deleted profile can
    -- never leave a half-resolved event behind.
    constraint tre_profile_owner_fk
        foreign key (tenant_id, regulatory_profile_id)
        references tenant_regulatory_profiles (tenant_id, id)
        on delete set null
);

-- One row per (content, occurrence) of a bundle's callback.
create unique index if not exists tre_fingerprint_occurrence_key
    on tenant_regulatory_events (provider, bundle_sid, fingerprint, occurrence);

-- The redelivery check reads the latest row for a bundle.
create index if not exists tre_bundle_latest_idx
    on tenant_regulatory_events (provider, bundle_sid, last_received_at desc);

create index if not exists tre_unapplied_idx
    on tenant_regulatory_events (applied, last_received_at) where applied is false;

-- ---------------------------------------------------------------------------
-- 7) Row-level security, matching the project convention: RLS on, NO policies.
--
--    Verified before writing this, not assumed: the backend uses the service-role
--    key (which bypasses RLS), and the frontend's anon client is used ONLY for
--    supabase.auth — there is not one `.from(` call on the anon client anywhere in
--    the app. All 27 table reads in the frontend are server-side admin routes.
--    So there is no client read path to write a policy for, and with RLS on and no
--    policy, anon is denied by default. No provider SID is ever client-visible.
-- ---------------------------------------------------------------------------
alter table tenant_regulatory_addresses enable row level security;
alter table tenant_regulatory_profiles  enable row level security;
alter table tenant_phone_numbers        enable row level security;
alter table tenant_regulatory_events    enable row level security;

comment on table tenant_phone_numbers is 'Canonical model for every number a tenant holds. purpose = why it exists, status = where it is in its lifecycle. tenants.twilio_phone_number remains a COMPATIBILITY MIRROR of the current permanent number during the transition.';
comment on table tenant_regulatory_profiles is 'One row per Twilio Bundle workflow. state is ours, bundle_status is Twilio''s stored verbatim. Identity is the regulatory address, never a locality string.';
comment on table tenant_regulatory_addresses is 'A Twilio Address and the business_address SupportingDocument that wraps it - 1:1 because the provider makes them so. provider_locality is metadata only.';
comment on table tenant_regulatory_events is 'Twilio regulatory status-callback ledger. Identity is (bundle, fingerprint, occurrence). No raw body is stored because FailureReason can quote identity.';

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting).
--
-- NON-DESTRUCTIVE BY CONSTRUCTION. The application keeps writing
-- tenants.twilio_phone_number as the mirror throughout, so the scalar remains a
-- complete description of every tenant's current permanent number at all times.
-- Rolling the application back to a scalar-only build therefore needs NONE of
-- this, and loses no routing. Nothing below is required; it is here for
-- completeness.
-- ===========================================================================
-- drop table if exists tenant_regulatory_events    cascade;
-- drop table if exists tenant_phone_numbers        cascade;
-- drop table if exists tenant_regulatory_profiles  cascade;
-- drop table if exists tenant_regulatory_addresses cascade;
-- alter table tenant_locations drop constraint if exists tenant_locations_tenant_id_id_key;
-- alter table tenants drop constraint if exists tenants_business_country_code_chk;
-- alter table tenants drop column if exists business_country_code;
