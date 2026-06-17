-- Migration: Square Connect integration
-- Run this in your Supabase SQL editor or via psql.

-- Square OAuth columns on tenants
alter table tenants
  add column if not exists square_access_token      text        null,
  add column if not exists square_refresh_token     text        null,
  add column if not exists square_token_expires_at  timestamptz null,
  add column if not exists square_merchant_id       text        null,
  add column if not exists square_location_id       text        null,
  add column if not exists square_deposits_enabled  boolean     not null default false,
  add column if not exists square_currency          text        null,
  add column if not exists square_oauth_state       text        null;

-- Provider column on payments (default 'stripe' so existing rows are unaffected)
alter table payments
  add column if not exists provider text not null default 'stripe';
