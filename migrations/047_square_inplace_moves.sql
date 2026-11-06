-- 047 — Square moves in place, for appointments with a deposit (issue #179)
--
-- Square's UpdateBooking moves a booking and keeps its id: start_at changes,
-- version goes up, and the service, team member, duration, location and customer
-- stay as they were. Our appointment row stays too, so a deposit linked to it —
-- paid or still owed — stays linked. That is why deposit appointments move in
-- place instead of through the replacement engine (020/022), which books a new
-- row and would leave the payment on the cancelled one.
--
-- These moves use the same durable operation and atomic finish as Google and
-- Outlook (046): this widens the provider check and records the Square booking's
-- version, team member and service variation at the moment the move was frozen,
-- so a recovery can tell "moved by us" from "changed by someone else".
--
-- It also adds a 'payment_confirmation' claim type (021): a deposit confirmation
-- owns the appointment for the few seconds it reads the time and sends its
-- texts, so no move can change the time under it. Claims of this type expire
-- after a five-minute lease (backend).
--
-- And it adds inplace_test_runs, for the one production validation of this
-- feature (backend services/square_inplace_scope). An operator ARMS a run by
-- inserting the sha256 of a one-time code; nothing works without one. Using the
-- code sets vapi_call_id once, so it is single-use; the row then names the one
-- appointment the test may act on, and link_claimed_at lets only one request
-- create its one payment link. disabled_at stops the run at once, used or not.
--
-- Backend only. Apply BEFORE deploying the backend that uses it: until then a
-- Square deposit move can't be recorded, so it is refused and handed to the team,
-- and a deposit confirmation can't take ownership, so it leaves the time out.
-- Changes no existing rows. Safe to run twice.

begin;
set local lock_timeout = '3s';

alter table public.calendar_move_operations
  drop constraint if exists calendar_move_operations_provider_check;
alter table public.calendar_move_operations
  add constraint calendar_move_operations_provider_check
  check (provider in ('google', 'microsoft', 'square'));

alter table public.calendar_move_operations
  add column if not exists provider_version bigint,
  add column if not exists team_member_id text,
  add column if not exists service_variation_id text,
  add column if not exists slot_ref text;

alter table public.appointment_mutation_claims
  drop constraint if exists appointment_mutation_claims_type_chk;
alter table public.appointment_mutation_claims
  add constraint appointment_mutation_claims_type_chk
  check (operation_type in ('cancel', 'reschedule', 'cancel_reconcile', 'payment_confirmation'));

create table if not exists public.inplace_test_runs (
  code_sha256     text        primary key check (code_sha256 ~ '^[0-9a-f]{64}$'),
  tenant_id       uuid        not null references public.tenants(id) on delete cascade,
  vapi_call_id    text,
  armed_at        timestamptz not null default now(),
  used_at         timestamptz,
  appointment_id  uuid        references public.appointments(id) on delete set null,
  link_claimed_at timestamptz,
  payment_id      uuid,
  disabled_at     timestamptz,
  created_at      timestamptz not null default now()
);
create unique index if not exists inplace_test_runs_appointment_key
  on public.inplace_test_runs (appointment_id) where appointment_id is not null;
alter table public.inplace_test_runs enable row level security;
revoke all on public.inplace_test_runs from public, anon, authenticated, service_role;
grant select, insert, update on public.inplace_test_runs to service_role;

do $$
begin
    if has_table_privilege('anon', 'public.inplace_test_runs', 'SELECT')
       or has_table_privilege('authenticated', 'public.inplace_test_runs', 'SELECT') then
        raise exception 'inplace_test_runs is readable by a browser role';
    end if;
    if not exists (select 1 from pg_constraint
                    where conrelid = 'public.appointment_mutation_claims'::regclass
                      and conname = 'appointment_mutation_claims_type_chk'
                      and pg_get_constraintdef(oid) like '%payment_confirmation%'
                      and pg_get_constraintdef(oid) like '%cancel_reconcile%') then
        raise exception 'claim type check does not allow payment_confirmation';
    end if;
    if not exists (select 1 from pg_constraint
                    where conrelid = 'public.calendar_move_operations'::regclass
                      and conname = 'calendar_move_operations_provider_check'
                      and pg_get_constraintdef(oid) like '%square%') then
        raise exception 'provider check does not allow square';
    end if;
    if has_table_privilege('anon', 'public.calendar_move_operations', 'SELECT') then
        raise exception 'calendar_move_operations is readable by anon';
    end if;
end $$;

notify pgrst, 'reload schema';
commit;
