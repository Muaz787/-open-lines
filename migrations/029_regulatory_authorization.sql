-- Migration: 029 — customer authorisation for a regulatory filing (W9H.1A)
-- PROPOSED. NOT APPLIED ANYWHERE.
--
-- THIS REPLACES AN EARLIER, NEVER-APPLIED 029 PROPOSAL that put five authorisation
-- columns on tenant_regulatory_business_details. That design was withdrawn in
-- review, not because of a defect in its constraints, but because its SCOPE was
-- wrong: business details are keyed (tenant_id, iso_country, end_user_type), one
-- row per country. Once authorisation covers the ADDRESS -- and it must, because
-- the customer authorises us to submit "their business identity AND address" -- one
-- row per country cannot hold a live Limerick authorisation and a live Cork one at
-- the same time. Authorising Cork would have overwritten Limerick. DANI is
-- multi-location, so that is not hypothetical.
--
-- SAFETY: ADDITIVE, IDEMPOTENT, NON-DESTRUCTIVE, DARK.
--   * one new table, plus one nullable column on tenant_regulatory_profiles
--   * NO backfill, NO UPDATE, NO INSERT. Consent cannot be inferred from data we
--     already hold, and a migration that manufactured it would be worse than no
--     table at all. Every existing row keeps authorisation absent, which is true:
--     nobody has authorised anything yet.
--   * nothing existing is altered or dropped
--   * RLS on, no policies -- matching every other regulatory table

-- ---------------------------------------------------------------------------
-- 1) tenant_regulatory_authorizations — one row per AUTHORISATION EVENT.
--
--    Append-oriented. A row records that a named customer representative, at a
--    moment, by a stated method, authorised one exact set of facts for one exact
--    regulatory scope. Rows are never rewritten to reflect new facts; a change of
--    facts is a NEW authorisation, and the old one remains queryable as history.
-- ---------------------------------------------------------------------------
create table if not exists tenant_regulatory_authorizations (
    id            uuid        primary key default gen_random_uuid(),
    tenant_id     uuid        not null references tenants(id) on delete cascade,

    -- THE SCOPE. iso_country and end_user_type match the business-details row the
    -- identity facts came from; the address pins WHICH premises was authorised.
    iso_country   text        not null,
    end_user_type text        not null,

    -- NOT NULL on purpose. An authorisation that names no premises is exactly the
    -- ambiguity this migration exists to remove -- it would be the old design
    -- again, wearing a new table.
    tenant_regulatory_address_id uuid not null,

    -- WHAT WAS AUTHORISED. sha256 over the 12 customer-supplied facts, under the
    -- versioned scheme in services/regulatory_authorization.py. This is the
    -- integrity mechanism: every field it covers is mutable by design, so the
    -- digest is what stops an authorisation attaching to facts the customer never
    -- saw. Recomputed and compared before any filing.
    authorized_details_fingerprint text not null,

    -- WHO, WHEN, HOW.
    -- authorized_by IS THE CUSTOMER'S REPRESENTATIVE. Never an OpenLines operator,
    -- employee or system actor, even when an operator recorded an authorisation
    -- given over the phone -- authorization_method is what says how it reached us.
    -- Free text rather than a foreign key because the authoriser has no account
    -- here, and it doubles as a snapshot: it does not follow later edits to the
    -- authorized_rep_* columns.
    authorized_by        text        not null,
    authorization_method text        not null,
    authorized_at        timestamptz not null,

    -- WITHDRAWAL. A timestamp rather than a deletion or a cleared authorized_at,
    -- so the history stays legible: authorisation was given, by whom, and was
    -- later withdrawn. Erasing it would destroy the audit trail the table exists
    -- for. After submission this does NOT pretend the filing was undone -- see the
    -- application gates below.
    authorization_revoked_at timestamptz null,

    -- THE HUMAN-READABLE REMNANT.
    -- The fingerprint proves integrity but is unreadable: confronted with a revoked
    -- authorisation, an auditor could not tell which premises it covered, because
    -- the address row it points at is mutable and may since have been corrected.
    -- Two narrow columns fix that -- enough to tell Limerick from Cork, and nothing
    -- more. Deliberately NOT a copy of the street, the representative or their
    -- email: duplicating personal data to make an audit prettier is not a trade we
    -- should make when the digest already carries the integrity.
    authorized_address_city        text not null,
    authorized_address_postal_code text null,

    created_at timestamptz not null default now(),

    constraint tra_auth_iso_chk  check (iso_country ~ '^[A-Z]{2}$'),
    constraint tra_auth_type_chk check (end_user_type in ('business', 'individual')),
    constraint tra_auth_method_chk check
        (authorization_method in ('dashboard', 'email', 'phone', 'written_other')),
    constraint tra_auth_fingerprint_chk check
        (authorized_details_fingerprint ~ '^[0-9a-f]{64}$'),
    -- An authorisation attributed to nobody is not a record of consent.
    constraint tra_auth_by_chk check (length(btrim(authorized_by)) > 0),
    constraint tra_auth_city_chk check (length(btrim(authorized_address_city)) > 0),
    -- Nothing can be withdrawn before it was given.
    constraint tra_auth_revoked_after_chk check
        (authorization_revoked_at is null or authorization_revoked_at >= authorized_at),

    -- so a profile can prove it cites an authorisation of the SAME tenant
    constraint tra_auth_tenant_id_id_key unique (tenant_id, id),

    -- THE CROSS-TENANT GUARD, structural rather than a code check. A plain FK to
    -- tenant_regulatory_addresses(id) would let tenant A authorise tenant B's
    -- validated premises. Composite, exactly as migration 027 does it.
    -- NO ACTION (the default) rather than RESTRICT: it is checked at end of
    -- statement, so deleting a tenant -- which cascades to the addresses and these
    -- rows in one statement -- still succeeds, while deleting a single address a
    -- live authorisation still cites correctly fails.
    constraint tra_auth_address_owner_fk
        foreign key (tenant_id, tenant_regulatory_address_id)
        references tenant_regulatory_addresses (tenant_id, id)
);

-- HISTORY IS THE POINT, so (tenant, country, end_user_type) is deliberately NOT
-- unique. What is unique is one ACTIVE authorisation per exact scope and exact
-- facts:
--
--   * Limerick active and Cork active at the same time -- different addresses.
--   * Limerick v1 revoked and Limerick v2 active -- revoked rows leave the index.
--   * two simultaneous identical submissions -- the second loses, which is the
--     idempotency we want: a double-click records one authorisation, not two.
--
-- The fingerprint is IN the key on purpose. Without it, re-authorising after a
-- corrected representative would collide with the still-active old authorisation
-- and the customer could not re-consent without first revoking.
create unique index if not exists tra_auth_active_key
    on tenant_regulatory_authorizations
       (tenant_id, iso_country, end_user_type, tenant_regulatory_address_id,
        authorized_details_fingerprint)
    where authorization_revoked_at is null;

-- The gate's lookup: the active authorisation for this scope.
create index if not exists tra_auth_scope_idx
    on tenant_regulatory_authorizations
       (tenant_id, iso_country, end_user_type, tenant_regulatory_address_id);

alter table tenant_regulatory_authorizations enable row level security;

comment on table tenant_regulatory_authorizations is
    'One row per customer authorisation EVENT. Append-oriented: facts never change, a change of facts is a new row, and revocation is the only intended later mutation.';
comment on column tenant_regulatory_authorizations.authorized_by is
    'The CUSTOMER REPRESENTATIVE who authorised the filing. Never an OpenLines operator or system actor, even when an operator recorded it.';
comment on column tenant_regulatory_authorizations.authorized_details_fingerprint is
    'sha256 over the 12 customer-supplied identity and address facts, scheme openlines.authorization.v1. Recomputed before filing; a mismatch means the facts moved and the authorisation no longer applies.';

-- ---------------------------------------------------------------------------
-- 2) Which authorisation a filing relied on.
--
--    Written when the profile first acquires a provider identity, and never
--    rewritten afterwards: a submitted filing must keep naming the authorisation
--    it was actually made under, even after the customer revokes it or authorises
--    something new. A later authorisation does not retroactively re-authorise a
--    filing that was made under a different one.
-- ---------------------------------------------------------------------------
alter table tenant_regulatory_profiles
    add column if not exists authorization_id uuid null;

do $$ begin
    alter table tenant_regulatory_profiles
        add constraint trp_authorization_owner_fk
        foreign key (tenant_id, authorization_id)
        references tenant_regulatory_authorizations (tenant_id, id);
exception when duplicate_object then null; end $$;

do $$ begin
    -- Once the workflow has reached the provider it must name its authorisation.
    -- Draft states are exempt: nothing has been filed, so there is nothing that
    -- needed authorising yet. Mirrors trp_submitted_identity_chk in 027.
    alter table tenant_regulatory_profiles
        add constraint trp_submitted_authorization_chk check (
            state not in ('pending_review', 'more_information_required', 'approved',
                          'rejected', 'number_provisioning', 'active')
            or authorization_id is not null);
exception when duplicate_object then null; end $$;

comment on column tenant_regulatory_profiles.authorization_id is
    'The exact authorisation this filing relied on. Written once, never rewritten -- a revocation or a later authorisation must not rewrite what a submitted filing was made under.';

-- ── APPLICATION GATES THIS MIGRATION REQUIRES (not part of the DDL) ────────
-- The database can refuse an incoherent row; it cannot know whether a Bundle has
-- been filed, nor recompute a sha256 over two tables. These live in
-- services/regulatory_engine.py, beside the declaration policy:
--
--   BEFORE the first provider identity (EndUser):
--     an authorisation must exist for this tenant + country + end_user_type +
--     ADDRESS, not be revoked, and its fingerprint must equal the digest of the
--     facts as they stand now. Failures are distinguished:
--       authorization_not_recorded / authorization_revoked /
--       authorization_stale / authorization_wrong_scope
--   BEFORE Bundle submission: every check repeated.
--   BEFORE number acquisition (W9I): the same reusable check.
--
--   REVOCATION AFTER SUBMISSION records the withdrawal and blocks further
--   regulated action, but never pretends the filing disappeared and never erases
--   authorized_at. Whether a revocation preceded or followed submission is
--   DERIVABLE -- tenant_regulatory_profiles.submitted_at already exists -- so it
--   needs no column, and deliberately no new profile state: provider bundle status
--   and authorisation status are orthogonal facts, and Twilio may well approve a
--   bundle after a customer withdrew. Collapsing both into `state` would force one
--   truth to overwrite the other.
--
--   IMMUTABILITY is engine-enforced, through an append-only repository interface
--   whose only UPDATE is revoke. A trigger was considered and rejected: this
--   repository contains none, and a CHECK cannot compare OLD to NEW. The residual
--   risk is stated honestly rather than papered over -- RLS is on with no policies,
--   so no anon or authenticated caller can touch these rows at all, but our own
--   service role could rewrite an authorisation, and nothing in the database would
--   stop it.
--
-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting). Dropping this table destroys the record
-- that customers authorised their filings, which is not recoverable from anything
-- else. An application rollback does not require it: the table is additive and the
-- profile column nullable, so a pre-W9H.1A build simply does not read them.
-- ===========================================================================
-- alter table tenant_regulatory_profiles
--     drop constraint if exists trp_submitted_authorization_chk;
-- alter table tenant_regulatory_profiles
--     drop constraint if exists trp_authorization_owner_fk;
-- alter table tenant_regulatory_profiles drop column if exists authorization_id;
-- drop index if exists tra_auth_scope_idx;
-- drop index if exists tra_auth_active_key;
-- drop table if exists tenant_regulatory_authorizations;
