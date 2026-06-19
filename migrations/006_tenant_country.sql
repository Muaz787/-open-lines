-- Migration: persist tenant country (onboarding auto-detect + override)
-- Run this in your Supabase SQL editor or via psql.

-- Country was previously only used transiently to pick a phone number;
-- persist it so the detected/overridden value survives provisioning.
alter table tenants
  add column if not exists country text null;
