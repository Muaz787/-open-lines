-- Migration: allow Square payments (no Stripe account)
-- Run this in your Supabase SQL editor or via psql.

-- Square deposits have no stripe_account_id, so the legacy NOT NULL
-- constraint must be dropped.
alter table payments
  alter column stripe_account_id drop not null;
