-- Migration: 008 — AI Overflow Handling & AI Call Routing (data model, Phase 1 foundation)
-- Run this in your Supabase SQL editor or via psql. Idempotent (safe to re-run).
--
-- SAFETY: this migration is ADDITIVE and DARK. It creates new, unused tables and
-- adds nullable/defaulted columns. No existing row changes, no existing query
-- changes, and the feature stays inert until BOTH the ROUTING_ENABLED env flag is
-- set AND a tenant is individually opted in (tenants.routing_enabled). See
-- services/entitlements.py. First production activation: our own OpenLines tenant.
--
-- FK ordering: destinations -> profiles -> rules -> attempts/decisions/callbacks.
-- Deleting a destination NULLs references (never cascade-deletes a profile/rule),
-- so a destination removed mid-call degrades to the safe fallback path.

-- ---------------------------------------------------------------------------
-- 1) routing_destinations — the ONLY endpoints the AI may reach. Numbers are
--    stored encrypted (AES-256-GCM via services/security.encrypt), with a masked
--    display form and a keyed HMAC hash for duplicate detection + forwarding-loop
--    prevention (compared without decrypting). Raw numbers are never stored.
-- ---------------------------------------------------------------------------
create table if not exists routing_destinations (
    id             uuid        primary key default gen_random_uuid(),
    tenant_id      uuid        not null references tenants(id) on delete cascade,
    type           text        not null default 'phone',   -- phone | urgent | callback | ai
    label          text        null,
    e164_encrypted text        null,                        -- AES-256-GCM token (null for non-phone types)
    e164_masked    text        null,                        -- e.g. '+1•••1234' (display only)
    e164_hash      text        null,                        -- HMAC-SHA256(pepper, E.164) — dedup/loop guard
    country        text        null,
    enabled        boolean     not null default true,
    verified_at    timestamptz null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index if not exists routing_destinations_tenant_idx on routing_destinations (tenant_id);
create index if not exists routing_destinations_hash_idx   on routing_destinations (tenant_id, e164_hash);

-- ---------------------------------------------------------------------------
-- 2) call_handling_profiles — per-line handling config (mode + overflow + the
--    default/urgent destinations + fallback). Keyed to a phone number so future
--    multi-number/multi-location tenants get a profile per line without reshaping.
--    For today's single-number tenants, phone_number is that one number.
-- ---------------------------------------------------------------------------
create table if not exists call_handling_profiles (
    id                      uuid        primary key default gen_random_uuid(),
    tenant_id               uuid        not null references tenants(id) on delete cascade,
    phone_number            text        null,               -- the line this profile governs
    mode                    text        not null default 'ai_first',   -- ai_first | ai_overflow | ai_first_routing
    overflow_enabled        boolean     not null default false,
    after_hours_behavior    text        null,               -- handle_ai | transfer | manual gate (see plan §5.2)
    default_destination_id  uuid        null references routing_destinations(id) on delete set null,
    urgent_destination_id   uuid        null references routing_destinations(id) on delete set null,
    default_fallback_action text        not null default 'callback',    -- callback | message | voicemail
    low_confidence_action   text        not null default 'handle_ai',   -- handle_ai | callback
    confidence_threshold    numeric     not null default 0.6,
    manual_coverage_until   timestamptz null,               -- temporary "cover us now" override
    version                 int         not null default 1,
    is_active               boolean     not null default true,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);
create index if not exists call_handling_profiles_tenant_idx on call_handling_profiles (tenant_id);
create unique index if not exists call_handling_profiles_number_idx
    on call_handling_profiles (tenant_id, phone_number) where phone_number is not null;

-- ---------------------------------------------------------------------------
-- 3) routing_rules — ordered, deterministic conditions -> destination. The
--    profile is also the policy container (no separate routing_policies table in
--    the MVP). `match` holds structured conditions consumed by services/routing_engine.
-- ---------------------------------------------------------------------------
create table if not exists routing_rules (
    id                     uuid        primary key default gen_random_uuid(),
    tenant_id              uuid        not null references tenants(id) on delete cascade,
    profile_id             uuid        not null references call_handling_profiles(id) on delete cascade,
    priority               int         not null default 100,      -- lower = evaluated first
    enabled                boolean     not null default true,
    match                  jsonb       not null default '{}'::jsonb,
    destination_id         uuid        null references routing_destinations(id) on delete set null,
    fallback_destination_id uuid       null references routing_destinations(id) on delete set null,
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now()
);
create index if not exists routing_rules_eval_idx on routing_rules (tenant_id, profile_id, priority);

-- ---------------------------------------------------------------------------
-- 4) transfer_attempts — one row per transfer attempt (audit + analytics).
--    Idempotent on (vapi_call_id, attempt_index) so duplicated/re-ordered provider
--    events collapse to a single row (fixes the webhook_events dedup gap for
--    multi-attempt calls).
-- ---------------------------------------------------------------------------
create table if not exists transfer_attempts (
    id             uuid        primary key default gen_random_uuid(),
    tenant_id      uuid        not null references tenants(id) on delete cascade,
    call_id        uuid        null references calls(id) on delete set null,
    vapi_call_id   text        null,
    destination_id uuid        null references routing_destinations(id) on delete set null,
    mode           text        null,                        -- warm | blind
    attempt_index  int         not null default 0,
    outcome        text        null,   -- answered | busy | no_answer | declined | failed | voicemail | caller_abandoned
    reason         text        null,
    duration_secs  int         null,
    started_at     timestamptz null,
    ended_at       timestamptz null,
    created_at     timestamptz not null default now()
);
create unique index if not exists transfer_attempts_dedup_idx
    on transfer_attempts (vapi_call_id, attempt_index) where vapi_call_id is not null;
create index if not exists transfer_attempts_tenant_outcome_idx
    on transfer_attempts (tenant_id, outcome, created_at);

-- ---------------------------------------------------------------------------
-- 5) routing_decisions — immutable audit of WHY a destination was chosen.
-- ---------------------------------------------------------------------------
create table if not exists routing_decisions (
    id                   uuid        primary key default gen_random_uuid(),
    tenant_id            uuid        not null references tenants(id) on delete cascade,
    call_id              uuid        null references calls(id) on delete set null,
    vapi_call_id         text        null,
    source               text        null,   -- direct | forwarded | unknown
    intent               text        null,
    urgency              text        null,
    confidence           numeric     null,
    matched_rule_id      uuid        null references routing_rules(id) on delete set null,
    chosen_destination_id uuid       null references routing_destinations(id) on delete set null,
    decision             text        null,   -- handled_ai | transfer | callback | fallback
    evaluated            jsonb       null,    -- rule-trace snapshot
    created_at           timestamptz not null default now()
);
create index if not exists routing_decisions_tenant_idx on routing_decisions (tenant_id, created_at);

-- ---------------------------------------------------------------------------
-- 6) callback_requests — structured callbacks (the always-safe fallback).
-- ---------------------------------------------------------------------------
create table if not exists callback_requests (
    id                     uuid        primary key default gen_random_uuid(),
    tenant_id              uuid        not null references tenants(id) on delete cascade,
    call_id                uuid        null references calls(id) on delete set null,
    caller_name            text        null,
    caller_phone           text        null,
    reason                 text        null,
    urgency                text        null,
    status                 text        not null default 'open',   -- open | done | cancelled
    assigned_destination_id uuid       null references routing_destinations(id) on delete set null,
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now()
);
create index if not exists callback_requests_tenant_status_idx on callback_requests (tenant_id, status);

-- ---------------------------------------------------------------------------
-- 7) calls — additive columns for source + disposition + transfer linkage.
-- ---------------------------------------------------------------------------
alter table calls add column if not exists source              text default 'unknown';   -- direct | forwarded | unknown
alter table calls add column if not exists overflow_reason     text;                      -- best-effort only
alter table calls add column if not exists disposition         text;                      -- inbox disposition (plan §11)
alter table calls add column if not exists transferred         boolean default false;
alter table calls add column if not exists final_destination_id uuid;

-- ---------------------------------------------------------------------------
-- 8) tenants — per-tenant activation flag (dark by default). Master switch is the
--    ROUTING_ENABLED env var (services/entitlements.py); this is the per-tenant gate.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists routing_enabled boolean default false;

-- ---------------------------------------------------------------------------
-- Row-level security on the new tables (matches the project convention; the
-- backend uses the service-role key which bypasses RLS, anon is blocked).
-- ---------------------------------------------------------------------------
alter table routing_destinations   enable row level security;
alter table call_handling_profiles enable row level security;
alter table routing_rules          enable row level security;
alter table transfer_attempts      enable row level security;
alter table routing_decisions      enable row level security;
alter table callback_requests      enable row level security;

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting). Drops only the objects this migration
-- created. Data loss in the new tables is expected; existing tables are only
-- losing the additive columns. Order respects FKs (CASCADE handles refs).
-- ===========================================================================
-- alter table tenants drop column if exists routing_enabled;
-- alter table calls   drop column if exists source;
-- alter table calls   drop column if exists overflow_reason;
-- alter table calls   drop column if exists disposition;
-- alter table calls   drop column if exists transferred;
-- alter table calls   drop column if exists final_destination_id;
-- drop table if exists callback_requests   cascade;
-- drop table if exists routing_decisions   cascade;
-- drop table if exists transfer_attempts   cascade;
-- drop table if exists routing_rules       cascade;
-- drop table if exists call_handling_profiles cascade;
-- drop table if exists routing_destinations cascade;
