-- W7D review fix — exact provider identity for a W6A2 replacement, and one local
-- row per provider booking.
--
-- WHY A SEPARATE MIGRATION FROM 025
-- 025 is "which provider version does this appointment reflect". This is "which
-- provider booking IS this". Neither is applied yet, so they could have been
-- merged -- but they answer different questions and will be reviewed on different
-- grounds, and a reviewer reading 026 should not have to disentangle it from a
-- versioning change.
--
-- ── WHY replacement_provider_booking_id ────────────────────────────────────
-- D2 already produces an exact link between an operation and its replacement's
-- Square booking: appointments.google_event_id holds the booking id, and
-- operation.replacement_appointment_id points at that row. But both are written
-- AFTER CreateBooking returns:
--
--     create_booking() returns  ->  [ GAP ]  ->  insert replacement appointment
--
-- Inside that gap the booking exists at Square, a booking.created webhook can
-- arrive, and nothing local names it. W7D's first attempt closed that gap by
-- inferring identity from tenant + location + start_at, which is not identity at
-- all: two legitimate bookings can share all three and differ in staff, service,
-- resource or customer. Square hands us a unique booking id; guessing when the
-- provider has already told us is indefensible.
--
-- This column is written immediately after CreateBooking succeeds, before the
-- appointment insert, so the gap has an exact answer.
--
-- The partial unique index enforces the invariant that makes adoption safe: one
-- Square booking is the replacement of at most one operation. That holds because
-- every operation carries its own frozen idempotency key, so two operations
-- cannot converge on one booking -- and a replay of the SAME operation converges
-- on the same booking id, which the write path treats as success rather than
-- conflict.
--
-- ── WHY appointments (tenant_id, google_event_id) ──────────────────────────
-- The webhook mirror path is SELECT-then-INSERT. Two deliveries of one
-- booking.created, processed concurrently, both see no row and both insert. There
-- is no constraint stopping that today.
--
-- Scoped to (tenant_id, google_event_id) rather than the column alone: the race
-- is always within one tenant (routing has already resolved exactly one), and the
-- narrower key cannot be tripped by any future case where two tenants legitimately
-- reference the same provider object.
--
-- Verified against production before writing this: 26 appointments, all with a
-- google_event_id, zero duplicates on either key.

alter table appointment_reschedule_operations
    add column if not exists replacement_provider_booking_id text null;

-- One Square booking is the replacement of at most one operation.
create unique index if not exists appointment_reschedule_ops_replacement_booking_key
    on appointment_reschedule_operations (replacement_provider_booking_id)
    where replacement_provider_booking_id is not null;

-- Adoption looks an operation up by the booking id a webhook just delivered.
-- (The unique index above already serves equality lookups, so no second index.)

-- One local appointment per provider booking, per tenant. This is what makes the
-- webhook's SELECT-then-INSERT safe under concurrent delivery: the loser gets
-- 23505 and re-reads instead of creating a second row.
--
-- THE PREDICATE EXCLUDES THE EMPTY STRING, NOT JUST NULL.
-- routers/tools.py writes `event.get("id", "")` on the Google/Outlook booking
-- path, so a calendar response without an id yields '' rather than NULL. Under a
-- NULL-only predicate two such rows for one tenant would collide, and a calendar
-- hiccup would become a REFUSED BOOKING for a caller on the phone. An empty id is
-- not a provider identity, so it is excluded from the identity constraint
-- entirely -- which is also the honest reading: we cannot claim uniqueness over a
-- value that identifies nothing.
--
-- Verified against production before writing: 26 appointments, 0 NULL, 0 empty,
-- 0 duplicates on either key.
create unique index if not exists appointments_tenant_provider_booking_key
    on appointments (tenant_id, google_event_id)
    where google_event_id is not null and google_event_id <> '';

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting).
--
-- Additive and invisible to pre-W7D code. An application rollback does NOT
-- require dropping these, and dropping replacement_provider_booking_id would
-- discard the only exact record of which booking an in-flight operation created.
-- ===========================================================================
-- drop index if exists appointments_tenant_provider_booking_key;
-- drop index if exists appointment_reschedule_ops_replacement_booking_key;
-- alter table appointment_reschedule_operations
--     drop column if exists replacement_provider_booking_id;
