-- Migration: refund tracking on payments
-- Run this in your Supabase SQL editor or via psql.

-- Records when a deposit was refunded (status moves to 'refunded').
alter table payments
  add column if not exists refunded_at timestamptz null;
