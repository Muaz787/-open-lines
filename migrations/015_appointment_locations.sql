-- Migration: 015 — which location an appointment belongs to (W5)
-- Run in the Supabase SQL editor or via psql. Idempotent.
--
-- SAFETY: additive, both columns nullable, no backfill. Existing rows (19 on the
-- one Square-connected tenant) stay NULL and every legacy path keeps working —
-- nothing reads these until the multi-location booking path writes them.
--
-- WHY BOTH: tenant_location_id is the durable business identity and survives a
-- provider re-mapping or a move to a different booking system; provider_location_id
-- is the immutable fact of what we actually sent Square, which is what you need
-- when reconciling our records against a Square report a year later. Neither
-- substitutes for the other.
--
-- ON DELETE SET NULL, as in 014: removing a location must not take booking history
-- with it. An appointment that happened, happened.
--
-- NOT IN SCOPE: appointments.google_event_id still holds the Square booking id for
-- Square tenants. That overload predates W5 and is deliberately left alone.

alter table appointments
  add column if not exists tenant_location_id   uuid null references tenant_locations(id) on delete set null,
  add column if not exists provider_location_id text null;

create index if not exists idx_appointments_tenant_location
  on appointments (tenant_location_id);

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting).
-- ===========================================================================
-- drop index if exists idx_appointments_tenant_location;
-- alter table appointments
--   drop column if exists tenant_location_id,
--   drop column if exists provider_location_id;
