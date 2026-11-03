-- 045 — one booking per slot per call, owned durably
--
-- A booking used to be guarded only by reading the caller's appointments first. Two
-- requests arriving together both read nothing and both booked; a lookup that failed
-- let the booking through; and a process that died after creating the calendar
-- event but before writing the appointment left nothing to stop the next attempt
-- creating another.
--
-- Each Google or Outlook booking made during a call now claims its slot here first:
--   * the primary key makes a slot in a call bookable once;
--   * the partial index lets a call have only one booking in progress at a time;
--   * attempt feeds the calendar event's deterministic id, so a retry or a recovery
--     after a crash finds the event it already made instead of making another.
--
-- Backend only. Apply this BEFORE deploying the backend that uses it: until then
-- the booking tool refuses Google and Outlook bookings rather than book unguarded.
-- New table only; no existing data changes. Safe to run twice.

begin;
set local lock_timeout = '3s';

create table if not exists public.call_booking_claims (
  tenant_id         uuid        not null,
  vapi_call_id      text        not null,
  slot_start        timestamptz not null,
  caller_phone      text        not null,
  attempt           integer     not null default 1 check (attempt >= 1),
  state             text        not null check (state in ('pending', 'booked', 'failed')),
  provider_event_id text,
  appointment_id    uuid,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  primary key (tenant_id, vapi_call_id, slot_start)
);

create unique index if not exists call_booking_claims_one_pending_per_call
  on public.call_booking_claims (tenant_id, vapi_call_id) where state = 'pending';

alter table public.call_booking_claims enable row level security;
revoke all on table public.call_booking_claims from public, anon, authenticated;
grant select, insert, update, delete on table public.call_booking_claims to service_role;

do $$
begin
    if has_table_privilege('anon', 'public.call_booking_claims', 'SELECT')
       or has_table_privilege('authenticated', 'public.call_booking_claims', 'SELECT') then
        raise exception 'call_booking_claims is readable by a browser role';
    end if;
    if not (has_table_privilege('service_role', 'public.call_booking_claims', 'INSERT')
            and has_table_privilege('service_role', 'public.call_booking_claims', 'UPDATE')) then
        raise exception 'service_role cannot write call_booking_claims';
    end if;
end $$;

notify pgrst, 'reload schema';
commit;
