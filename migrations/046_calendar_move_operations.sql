-- 046 — durable record of moving a Google or Outlook appointment
--
-- Google and Outlook can move an event in place: one PATCH changes its start and
-- end, keeping the event, the appointment row and anything linked to that row —
-- deposits included. That single provider call still needs a durable record:
--   * the appointment is owned (migration 021) under this operation's id, and the
--     orphan sweep only releases a claim whose operation row does not exist;
--   * a timeout leaves the provider's answer unknown, and the next attempt must
--     settle it by reading the event, not by sending another move;
--   * the provider can be moved while our own row is not yet updated.
--
-- One live operation per appointment, enforced by the partial unique index.
-- Backend only. Apply BEFORE deploying the backend that uses it: until then
-- reschedule_appointment refuses Google and Outlook moves. New table only; no
-- existing data changes. Safe to run twice.

begin;
set local lock_timeout = '3s';

create table if not exists public.calendar_move_operations (
  id                uuid        primary key,
  tenant_id         uuid        not null references public.tenants(id) on delete cascade,
  appointment_id    uuid        not null references public.appointments(id) on delete cascade,
  vapi_call_id      text,
  provider          text        not null check (provider in ('google', 'microsoft')),
  provider_event_id text        not null,
  from_start_utc    timestamptz not null,
  to_start_utc      timestamptz not null,
  duration_minutes  integer     not null check (duration_minutes > 0),
  state             text        not null default 'in_progress'
                    check (state in ('in_progress', 'unknown', 'provider_moved', 'completed', 'failed')),
  claim_token       uuid        not null,
  claimed_at        timestamptz not null,
  detail            text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  check (from_start_utc <> to_start_utc)
);

create unique index if not exists calendar_move_operations_one_live
  on public.calendar_move_operations (appointment_id)
  where state in ('in_progress', 'unknown', 'provider_moved');

create index if not exists calendar_move_operations_unfinished
  on public.calendar_move_operations (updated_at)
  where state in ('in_progress', 'unknown', 'provider_moved');

alter table public.calendar_move_operations enable row level security;
revoke all on table public.calendar_move_operations from public, anon, authenticated;
grant select, insert, update, delete on table public.calendar_move_operations to service_role;

-- Finishing a move is ONE statement-level decision. A recovery worker that read
-- the provider and then paused must not write its old target into an appointment
-- that another worker has since completed, moved again or cancelled. So the
-- appointment write, the completion and the release happen together, and only
-- while this operation still owns the appointment: the operation row is locked
-- and must still be provider_moved under this claim token, and the mutation claim
-- (021) must still name this operation and token.
create or replace function public.calendar_move_finish(p_operation_id uuid, p_claim_token uuid)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
    op public.calendar_move_operations%rowtype;
    n integer;
begin
    select * into op from public.calendar_move_operations
     where id = p_operation_id for update;
    if not found then
        return 'missing';
    end if;
    if op.claim_token <> p_claim_token or op.state <> 'provider_moved' then
        return 'not_owner';
    end if;
    perform 1 from public.appointment_mutation_claims
     where appointment_id = op.appointment_id and claim_token = p_claim_token
       and operation_id = p_operation_id and operation_type = 'reschedule'
       for update;
    if not found then
        return 'not_owner';
    end if;
    update public.appointments set appointment_datetime = op.to_start_utc
     where id = op.appointment_id and status in ('confirmed', 'pending_payment');
    get diagnostics n = row_count;
    if n = 0 then
        return 'appointment_inactive';
    end if;
    update public.calendar_move_operations set state = 'completed', updated_at = now()
     where id = op.id;
    delete from public.appointment_mutation_claims
     where appointment_id = op.appointment_id and claim_token = p_claim_token;
    return 'completed';
end;
$$;

revoke execute on function public.calendar_move_finish(uuid, uuid) from public, anon, authenticated;
grant execute on function public.calendar_move_finish(uuid, uuid) to service_role;

do $$
begin
    if has_function_privilege('anon', 'public.calendar_move_finish(uuid, uuid)', 'EXECUTE')
       or has_function_privilege('authenticated', 'public.calendar_move_finish(uuid, uuid)', 'EXECUTE') then
        raise exception 'calendar_move_finish is executable by a browser role';
    end if;
    if has_table_privilege('anon', 'public.calendar_move_operations', 'SELECT')
       or has_table_privilege('authenticated', 'public.calendar_move_operations', 'SELECT') then
        raise exception 'calendar_move_operations is readable by a browser role';
    end if;
    if not (has_table_privilege('service_role', 'public.calendar_move_operations', 'INSERT')
            and has_table_privilege('service_role', 'public.calendar_move_operations', 'UPDATE')) then
        raise exception 'service_role cannot write calendar_move_operations';
    end if;
end $$;

notify pgrst, 'reload schema';
commit;
