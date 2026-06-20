-- Migration: Zapier integration foundation
-- Run this in your Supabase SQL editor or via psql.

-- Per-tenant API keys (Zapier / public API auth). Only the hash is stored;
-- the raw key is shown to the owner once at creation time.
create table if not exists tenant_api_keys (
  id           uuid        primary key default gen_random_uuid(),
  tenant_id    uuid        not null references tenants(id) on delete cascade,
  key_hash     text        not null unique,
  key_prefix   text        not null,            -- first chars, for display ("ol_live_AbСd…")
  label        text        null,
  last_used_at timestamptz null,
  revoked_at   timestamptz null,
  created_at   timestamptz not null default now()
);
create index if not exists tenant_api_keys_tenant_idx on tenant_api_keys (tenant_id);
create index if not exists tenant_api_keys_hash_idx   on tenant_api_keys (key_hash);

-- Zapier REST Hook subscriptions: Zapier registers a target_url per event.
create table if not exists zapier_subscriptions (
  id          uuid        primary key default gen_random_uuid(),
  tenant_id   uuid        not null references tenants(id) on delete cascade,
  event       text        not null,             -- e.g. 'call_completed', 'deposit_paid'
  target_url  text        not null,             -- Zapier-provided hook URL
  created_at  timestamptz not null default now()
);
create index if not exists zapier_subscriptions_tenant_event_idx on zapier_subscriptions (tenant_id, event);

alter table tenant_api_keys      enable row level security;
alter table zapier_subscriptions enable row level security;
