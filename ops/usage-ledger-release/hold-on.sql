-- Usage ledger release: hold new end-of-call events.
--
-- New end-of-call events are stored with status 'held:usage-042', which no backend
-- version reads. Call intake keeps working, and nothing is lost. Refuses to start if
-- this hold already exists or any event has a status this release doesn't expect, so
-- hold-off.sql can only ever release events this hold created.

begin;
set local lock_timeout = '3s';

do $$
declare
    unexpected integer;
begin
    if exists (select 1 from pg_trigger where tgname = 'usage_release_hold') then
        raise exception 'The usage release hold is already on';
    end if;
    select count(*) into unexpected from public.webhook_events
     where status not in ('pending', 'done', 'failed');
    if unexpected > 0 then
        raise exception '% event(s) have an unexpected status; stop and review them', unexpected;
    end if;
end $$;

create function public.usage_release_hold_event()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    -- Only events arriving as pending: a status someone set on purpose is theirs.
    if new.event_type = 'end-of-call-report' and new.status = 'pending' then
        new.status := 'held:usage-042';
    end if;
    return new;
end;
$$;

revoke execute on function public.usage_release_hold_event() from public, anon, authenticated;

create trigger usage_release_hold
    before insert on public.webhook_events
    for each row execute function public.usage_release_hold_event();

commit;
