-- Migration: cancellation refund policy
-- Run this in your Supabase SQL editor or via psql.

-- Full deposit refund when a caller cancels at least this many hours before
-- the appointment; cancellations inside the window forfeit the deposit.
-- 0 = always refund. A large value (e.g. 9999) effectively = never auto-refund.
alter table tenants
  add column if not exists cancellation_refund_hours int not null default 24;
