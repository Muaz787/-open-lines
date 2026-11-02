-- Usage ledger release: release the hold.
--
-- Removes the trigger first, so new events are pending again, then returns only the
-- events this hold created, in their original order. Prints each released event id.
-- Run only once handover-status.sql shows the deployment you want is the only one left.

begin;
set local lock_timeout = '3s';

drop trigger if exists usage_release_hold on public.webhook_events;
drop function if exists public.usage_release_hold_event();

update public.webhook_events
   set status = 'pending'
 where status = 'held:usage-042'
returning id, call_id, created_at;

commit;
