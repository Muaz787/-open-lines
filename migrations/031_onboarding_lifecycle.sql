-- Migration: 031 — onboarding lifecycle + the onboarding idempotency key (W9I-B)
-- PROPOSED. NOT APPLIED.
--
-- SAFETY: ADDITIVE, IDEMPOTENT, NON-DESTRUCTIVE.
--   * two nullable columns on `tenants`, one CHECK, one partial unique index
--   * ONE backfill, and it is the narrow kind: it gives every EXISTING tenant the
--     state it already demonstrably has, derived from data already on the row. It
--     invents nothing. Without it the column would be NULL for every live tenant
--     and the application could not tell "finished long ago" from "never started".
--   * nothing is dropped or altered; migrations 029 and 030 are untouched
--
-- ── WHY A COLUMN AND NOT A TABLE ──────────────────────────────────────────
-- Until now the tenant row was the LAST thing signup wrote, so "a tenant exists"
-- and "onboarding finished" were one fact. Ireland breaks that: a local Irish
-- number needs a validated address and an approved Bundle, both keyed on
-- tenant_id by composite FK, so the tenant must exist FIRST and must be able to
-- rest there, valid and un-numbered.
--
-- This is one fact about one tenant. A table would add a join and a second place
-- for it to disagree with `tenants`, and the regulatory span is already a state
-- machine on tenant_regulatory_profiles.state -- duplicating any of it here would
-- give two answers to one question. So the column stops at the boundary: does a
-- number exist yet, and if not, why not.

-- ---------------------------------------------------------------------------
-- 1) Where the tenant is in onboarding.
--
--    NOT is_active. is_active says the account is not closed or suspended and is
--    what the trial and reclaim paths read; this says setup has finished. A
--    tenant can be is_active = true and still mid-onboarding, which is exactly
--    the Irish case.
--
--    Nullable rather than NOT NULL DEFAULT, for a specific reason: the currently
--    deployed application does not write this column, and a DEFAULT would make
--    every row it inserts claim a state it never chose. NULL means "written by a
--    build that predates the lifecycle", and the backfill below resolves every
--    such row that exists today.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists onboarding_state text null;

do $$ begin
    alter table tenants
        add constraint tenants_onboarding_state_chk check (
            onboarding_state is null
            or onboarding_state in ('provisioning', 'regulatory_required', 'active'));
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------------
-- 2) The onboarding idempotency key.
--
--    Moving the tenant insert to the FRONT of signup creates a hazard that did
--    not exist when it was last: a double-clicked form, a retried request or a
--    browser refresh would each mint a whole new tenant. The old flow was
--    accidentally protected -- it failed before the insert.
--
--    The key is what makes a retry a RESUME. One signup attempt carries one
--    opaque value; the partial unique index below lets the database decide which
--    concurrent request creates the tenant, and the loser re-reads it. Exactly
--    the claim-then-reread discipline W9H-QA.3/.4 proved for provider resources.
--
--    DELIBERATELY NOT email or business_name. Neither is unique in this product:
--    one person legitimately runs two businesses, and two businesses share a
--    name. Making either a uniqueness key would refuse real signups, and would
--    also turn "does this email exist" into an oracle on an unauthenticated
--    endpoint.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists onboarding_key text null;

-- Partial, so the overwhelming majority of rows (every tenant that predates the
-- key, and every tenant created by any other path) are simply not in the index.
create unique index if not exists tenants_onboarding_key_uq
    on tenants (onboarding_key)
    where onboarding_key is not null;

comment on column tenants.onboarding_state is
    'Where the tenant is in onboarding: provisioning | regulatory_required | active. NOT is_active, which is about closure/suspension. NULL means the row predates the lifecycle column.';
comment on column tenants.onboarding_key is
    'Opaque per-attempt idempotency key. A retry carrying the same key resumes the same tenant instead of minting another. Never an email or a business name.';

-- ---------------------------------------------------------------------------
-- 3) BACKFILL — narrow, derived, and inventing nothing.
--
--    Every existing tenant is given the state its own row already proves:
--      * holds a phone number  -> 'active'   (it has a working line today)
--      * holds none            -> 'provisioning'
--
--    The legacy scalar is the right signal here rather than the canonical table,
--    because it is what the currently deployed build writes and what routing
--    still falls back to. Verified against production before writing this: 11
--    tenants, 7 with a scalar number, 7 canonical rows, an exact 1:1 match on
--    E.164 with a provider SID on every one -- so for today's data the two
--    signals agree completely and neither is a guess.
--
--    No tenant is given 'regulatory_required': nobody has confirmed a regulated
--    country, and business_country_code is non-null on zero rows. Assigning that
--    state to anyone would be inventing a compliance obligation.
--
--    Guarded by IS NULL so a re-run cannot overwrite a state the application has
--    since set. That is what makes this file safe to apply twice.
-- ---------------------------------------------------------------------------
update tenants
   set onboarding_state = 'active'
 where onboarding_state is null
   and twilio_phone_number is not null
   and btrim(twilio_phone_number) <> '';

update tenants
   set onboarding_state = 'provisioning'
 where onboarding_state is null;

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting).
--
-- Additive and invisible to the currently deployed build, which reads neither
-- column. An application rollback does NOT require this: dropping
-- onboarding_key would discard the only thing that makes a retry resume rather
-- than duplicate, and dropping onboarding_state would lose the distinction
-- between a tenant awaiting compliance and a broken one.
-- ===========================================================================
-- drop index if exists tenants_onboarding_key_uq;
-- alter table tenants drop column if exists onboarding_key;
-- alter table tenants drop constraint if exists tenants_onboarding_state_chk;
-- alter table tenants drop column if exists onboarding_state;
