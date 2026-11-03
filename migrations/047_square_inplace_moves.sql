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
-- Backend only. Apply BEFORE deploying the backend that uses it: until then a
-- Square deposit move can't be recorded, so it is refused and handed to the team,
-- exactly as today. Changes no existing rows. Safe to run twice.

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

do $$
begin
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
