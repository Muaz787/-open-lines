-- Migration: 016 — server-side slot binding + per-call service context (W5)
-- Run in the Supabase SQL editor or via psql. Idempotent.
--
-- SAFETY: one new table plus two nullable columns on call_location_state, which
-- holds only in-flight call state. No backfill. Nothing existing changes.
--
-- WHY THIS TABLE EXISTS
-- Availability and booking were two independent derivations: the booking path
-- re-matched the service, re-resolved the staff and re-read the location pointer,
-- so nothing linked what a caller was OFFERED to what they got BOOKED into. Adding
-- a location argument without fixing that would have created a new silent failure —
-- hear Dublin, get booked in Cork.
--
-- A slot offer is the binding. Availability writes down exactly what it offered;
-- booking consumes an offer by reference and uses ONLY the identifiers inside it.
-- The model never supplies a Square id, so it cannot construct a booking we did
-- not offer.

create table if not exists call_slot_offers (
    -- Short and caller-safe ('slot_1'), unique within a call. Monotonic across the
    -- whole call, never restarted per location: reusing 'slot_1' for Dublin after
    -- Cork had one is exactly the confusion this table prevents.
    slot_ref                  text        not null,
    vapi_call_id              text        not null,
    tenant_id                 uuid        not null references tenants(id) on delete cascade,

    -- Everything CreateBooking needs, captured at the moment of the offer.
    tenant_location_id        uuid        null references tenant_locations(id) on delete set null,
    provider_location_id      text        not null,
    service_variation_id      text        not null,
    service_variation_version bigint      null,
    service_name              text        null,
    team_member_id            text        null,
    start_at_utc              timestamptz not null,
    duration_minutes          int         null,

    expires_at                timestamptz not null,
    consumed_at               timestamptz null,
    -- Set when the offer is consumed. Makes a retried tool call idempotent: the
    -- same slot_ref returns the booking that already exists instead of making a
    -- second one.
    booking_id                text        null,

    created_at                timestamptz not null default now(),

    primary key (vapi_call_id, slot_ref)
);

create index if not exists call_slot_offers_tenant_idx  on call_slot_offers (tenant_id, vapi_call_id);
create index if not exists call_slot_offers_expires_idx on call_slot_offers (expires_at);

alter table call_slot_offers enable row level security;

-- ---------------------------------------------------------------------------
-- Per-call service context. Same rationale as active_location_id: the service the
-- caller asked for must survive a location switch, so "dress fitting" still means
-- dress fitting when they ask "what about Dublin?". The variation id is the
-- authority; the name is for speech and is never used for matching.
-- ---------------------------------------------------------------------------
alter table call_location_state
  add column if not exists active_service_variation_id text null,
  add column if not exists active_service_name         text null;

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting).
-- ===========================================================================
-- drop table if exists call_slot_offers cascade;
-- alter table call_location_state
--   drop column if exists active_service_variation_id,
--   drop column if exists active_service_name;
