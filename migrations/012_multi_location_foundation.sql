-- Migration: 012 — Multi-location foundation (W1)
-- Run this in your Supabase SQL editor or via psql. Idempotent (safe to re-run).
--
-- SAFETY: this migration is ADDITIVE and DARK. It creates two new, unused tables.
-- It adds no column to an existing table, changes no existing row, and alters no
-- existing query. Nothing in the application reads these tables after W1 — the
-- authoritative sources are unchanged:
--
--     tenants.square_location_id   still authoritative for Square
--     tenants.calendar_timezone    still authoritative for timezone
--     tenants.twilio_phone_number  still authoritative for inbound routing
--     tenants.business_hours_*     still authoritative for hours
--
-- Applying this migration on its own changes NOTHING observable. The row backfill
-- is deliberately NOT in this file — it lives in backend/services/location_backfill.py
-- and is run by backend/scripts/backfill_locations.py, which is dry-run by default.
-- Keeping it there means one implementation of the logic, covered by the test suite,
-- rather than a second copy in SQL that no test can reach.
--
-- WHY TWO TABLES: a physical shop is a BUSINESS concept — it owns hours, a timezone,
-- an address, aliases the AI speaks aloud, and (later) phone numbers. A Square
-- location id is a PROVIDER detail. Conflating them would make multi-location a
-- Square-only feature, when the next multi-location customer is as likely to be a
-- clinic group with one Google calendar per branch. tenant_locations is the identity;
-- location_provider_bindings maps that identity onto whichever provider holds the
-- calendar.

-- ---------------------------------------------------------------------------
-- 1) tenant_locations — the provider-neutral business location.
--
--    IDENTITY IS THE UUID. Never the address, never the name, never the provider
--    id. The address exists for the knowledge base and the dashboard only: test
--    locations can carry placeholder addresses while being perfectly valid, and a
--    real location can be renamed or move premises without becoming a different
--    location.
--
--    slug  — stable machine key used in logs and (later) analytics. Set once,
--            never re-slugged, because a rename must not orphan history.
--    name  — what the caller hears. May change freely.
--    aliases — everything else a caller might say for this place ("the Cork shop",
--            "Patrick Street"). Array rather than a child table: a handful of values,
--            always read with the row, never queried alone — matching the existing
--            square_services.team_member_ids / tenants.operating_priorities shape.
-- ---------------------------------------------------------------------------
create table if not exists tenant_locations (
    id              uuid        primary key default gen_random_uuid(),
    tenant_id       uuid        not null references tenants(id) on delete cascade,
    slug            text        not null,
    name            text        not null,
    aliases         text[]      not null default '{}',
    country         text        null,
    timezone        text        null,           -- IANA; null = inherit tenants.calendar_timezone
    address_line1   text        null,           -- display / KB only. NEVER identity.
    address_line2   text        null,
    address_city    text        null,
    address_region  text        null,
    address_postal  text        null,
    business_hours  jsonb       null,           -- null = inherit tenant / provider owns them
    booking_enabled boolean     not null default false,
    is_default      boolean     not null default false,
    active          boolean     not null default true,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- One slug per tenant. Two tenants may both have a "cork".
create unique index if not exists tenant_locations_tenant_slug_idx
    on tenant_locations (tenant_id, slug);

-- EXACTLY ONE default per tenant, enforced by the database rather than by
-- convention. A partial unique index is what makes the backfill safe to re-run:
-- a second default is rejected by Postgres, not merely avoided by application code.
create unique index if not exists tenant_locations_one_default_idx
    on tenant_locations (tenant_id) where is_default;

create index if not exists tenant_locations_tenant_active_idx
    on tenant_locations (tenant_id, active);

-- ---------------------------------------------------------------------------
-- 2) location_provider_bindings — maps one business location onto one provider's
--    own location/calendar identifier.
--
--    PROVIDER-NEUTRAL BY CONSTRUCTION. 'provider' is free text, not an enum, and
--    provider_location_id is text, so Square location ids, Google calendar ids and
--    Microsoft calendar ids all fit without a schema change. There is deliberately
--    no square_* column anywhere in this table.
--
--    tenant_location_id is NULLABLE: sync discovers a provider's locations before
--    anyone has decided which business location they correspond to. An unmapped
--    binding is visible in the dashboard as "found, not yet set up" and is unusable
--    for booking.
--
--    provider_location_name is a LAST-SEEN COPY for drift detection only ("Cork was
--    renamed to X in Square"). It is never an identity or a lookup key.
-- ---------------------------------------------------------------------------
create table if not exists location_provider_bindings (
    id                     uuid        primary key default gen_random_uuid(),
    tenant_id              uuid        not null references tenants(id) on delete cascade,
    tenant_location_id     uuid        null references tenant_locations(id) on delete cascade,
    provider               text        not null,        -- 'square' | 'google' | 'microsoft' | …
    provider_location_id   text        not null,        -- the provider's immutable id
    provider_location_name text        null,            -- last seen; drift detection only
    provider_timezone      text        null,
    provider_currency      text        null,
    provider_status        text        null,            -- provider's own status, verbatim
    capabilities           jsonb       null,
    raw                    jsonb       null,            -- last provider payload, for debugging
    last_seen_at           timestamptz null,            -- null = never confirmed against the provider
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now()
);

-- A provider location belongs to a tenant once. This is what makes the backfill
-- and every future sync idempotent at the database level.
create unique index if not exists lpb_tenant_provider_location_idx
    on location_provider_bindings (tenant_id, provider, provider_location_id);

-- A business location has at most one binding per provider. Partial, because
-- unmapped bindings (tenant_location_id null) may legitimately be many.
create unique index if not exists lpb_location_provider_idx
    on location_provider_bindings (tenant_location_id, provider)
    where tenant_location_id is not null;

create index if not exists lpb_tenant_provider_idx
    on location_provider_bindings (tenant_id, provider);

-- ---------------------------------------------------------------------------
-- 3) Row-level security, matching the project convention: the backend uses the
--    service-role key (which bypasses RLS) and anon is blocked.
-- ---------------------------------------------------------------------------
alter table tenant_locations            enable row level security;
alter table location_provider_bindings  enable row level security;

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting). Drops only what this migration made.
-- No existing table loses a column, because none gained one. Order respects the
-- FK: bindings reference locations.
-- ===========================================================================
-- drop table if exists location_provider_bindings cascade;
-- drop table if exists tenant_locations           cascade;
