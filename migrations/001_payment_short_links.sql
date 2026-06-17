-- Migration: payment_short_links
-- Run this in your Supabase SQL editor or via psql.

create table if not exists payment_short_links (
  id                  uuid        primary key default gen_random_uuid(),
  tenant_id           uuid        not null references tenants(id) on delete cascade,
  appointment_id      uuid        null,
  short_code          text        not null unique,
  stripe_checkout_url text        not null,
  stripe_session_id   text        null,
  amount_cents        integer     null,
  currency            text        not null default 'cad',
  purpose             text        not null default 'appointment_deposit',
  expires_at          timestamptz not null,
  clicked_at          timestamptz null,
  click_count         integer     not null default 0,
  created_at          timestamptz not null default now()
);

create index if not exists payment_short_links_short_code_idx  on payment_short_links (short_code);
create index if not exists payment_short_links_tenant_id_idx   on payment_short_links (tenant_id);
create index if not exists payment_short_links_expires_at_idx  on payment_short_links (expires_at);

-- Enable Row Level Security (optional but recommended for Supabase)
alter table payment_short_links enable row level security;
