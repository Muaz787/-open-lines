-- Migration: 013 — location scope on the Square service + staff caches (W3)
-- Run this in your Supabase SQL editor or via psql. Idempotent (safe to re-run).
--
-- SAFETY: additive. Three columns on square_services, two on square_staff, every
-- one defaulted to "present everywhere" so existing rows describe exactly the
-- behaviour they have today. Nothing reads these columns in W3 — the runtime
-- availability and booking paths still see a tenant-flat cache, unchanged.
--
-- ORDERING MATTERS MORE THAN USUAL HERE. db.replace_square_services() deletes the
-- tenant's rows and re-inserts them in one pass. If the W3 code ships before this
-- migration is applied, that insert fails on an unknown column *after* the delete
-- has already happened, leaving a Square tenant with an empty service menu until
-- the next successful sync. Apply this first, then deploy. (Blast radius today is
-- zero: no tenant has square_appointments_enabled.)
--
-- WHY THREE COLUMNS AND NOT TWO: Square expresses presence as
--   present_at_all_locations = true  -> everywhere EXCEPT absent_at_location_ids
--   present_at_all_locations = false -> only at present_at_location_ids
-- Dropping the exclusion list would silently offer a service at a location the
-- merchant deliberately removed it from, so the exclusions are stored too.

-- ---------------------------------------------------------------------------
-- 1) square_services — where a bookable variation may actually be booked.
--
--    These values are the EFFECTIVE presence of the variation: Square carries
--    presence on both the parent item and the variation, and a variation is only
--    bookable where both are present. services/location_scope resolves the two
--    into the single triple stored here, so consumers never have to re-derive it.
-- ---------------------------------------------------------------------------
alter table square_services
  add column if not exists present_at_all_locations boolean not null default true,
  add column if not exists location_ids             text[]  not null default '{}',
  add column if not exists absent_location_ids      text[]  not null default '{}';

-- ---------------------------------------------------------------------------
-- 2) square_staff — where a team member may be booked.
--
--    ALL_CURRENT_AND_FUTURE_LOCATIONS is stored as a flag, not as a materialised
--    list of today's location ids: the merchant's intent is "wherever we trade",
--    and freezing that into ids would silently exclude a location added later.
-- ---------------------------------------------------------------------------
alter table square_staff
  add column if not exists assigned_all_locations boolean not null default true,
  add column if not exists location_ids           text[]  not null default '{}';

-- ---------------------------------------------------------------------------
-- 3) Lookup support for W4, when availability starts filtering by location.
--    GIN on the array so "which services are bookable at L…" is an index scan.
-- ---------------------------------------------------------------------------
create index if not exists idx_square_services_location_ids
  on square_services using gin (location_ids);
create index if not exists idx_square_staff_location_ids
  on square_staff using gin (location_ids);

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting). Dropping these columns returns both
-- caches to tenant-flat; no existing behaviour depends on them in W3.
-- ===========================================================================
-- drop index if exists idx_square_services_location_ids;
-- drop index if exists idx_square_staff_location_ids;
-- alter table square_services
--   drop column if exists present_at_all_locations,
--   drop column if exists location_ids,
--   drop column if exists absent_location_ids;
-- alter table square_staff
--   drop column if exists assigned_all_locations,
--   drop column if exists location_ids;
