-- Migration: 014 — authoritative per-call location state (W4)
-- Run this in your Supabase SQL editor or via psql. Idempotent (safe to re-run).
--
-- SAFETY: additive. One new table, no backfill, nothing else altered. Unlike 013
-- there is no delete-then-insert anywhere, so a mis-ordered deploy fails safe: the
-- multi-location branch simply errors and falls to its own fail-closed path, and no
-- tenant has >=2 adopted locations yet, so nothing reaches it.
--
-- WHY POSTGRES AND NOT PROCESS MEMORY: backend/Dockerfile runs uvicorn with no
-- --workers flag, but railway.json pins no replica count and a restart clears
-- memory mid-call. The only in-process state in the codebase (_recent_events in
-- routers/webhooks) is explicitly diagnostic. Authoritative call state cannot live
-- somewhere a redeploy silently empties.
--
-- LIFECYCLE: rows are short-lived. Deleted on end-of-call-report, with expires_at
-- as the backstop for calls whose report never arrives — swept by the existing
-- services/retention.run_retention(), not a new scheduler.

create table if not exists call_location_state (
    -- Vapi's message.call.id. Proven present on tool calls and end-of-call-report;
    -- rows are created lazily on the first tool call for exactly that reason.
    vapi_call_id        text        primary key,
    tenant_id           uuid        not null references tenants(id) on delete cascade,
    called_number       text        null,

    -- ON DELETE SET NULL, deliberately. If a location is removed mid-call the
    -- state must lose its authority rather than keep pointing at a row that no
    -- longer exists — a dangling id that still looked authoritative is precisely
    -- how a caller would get availability for somewhere the tenant no longer has.
    initial_location_id uuid        null references tenant_locations(id) on delete set null,
    active_location_id  uuid        null references tenant_locations(id) on delete set null,

    -- how active_location_id came to be what it is:
    --   unknown                 nothing resolved yet (multi-location, caller has not said)
    --   phone_number            seeded from the dialled line (W7; nothing sets this in W4)
    --   caller_selected         the caller named it
    --   sole_location           the tenant has exactly one eligible location
    --   legacy_single_location  single-location tenant on the legacy path
    location_source     text        not null default 'unknown',

    -- only incremented when the location genuinely changes, so it measures caller
    -- indecision rather than how many times a tool happened to pass an argument.
    switch_count        integer     not null default 0,

    expires_at          timestamptz not null,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index if not exists call_location_state_tenant_idx
    on call_location_state (tenant_id);

-- Drives the TTL sweep.
create index if not exists call_location_state_expires_idx
    on call_location_state (expires_at);

alter table call_location_state enable row level security;

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting). The table holds only in-flight call
-- state; dropping it loses nothing durable.
-- ===========================================================================
-- drop table if exists call_location_state cascade;
