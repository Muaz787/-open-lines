-- Usage ledger rollback: pause overage reporting.
--
-- Moves every pending overage row to review. The retry loop ignores review rows, and
-- a report already under way can't mark one reported, so nothing is sent or settled
-- automatically after this. Prints each row it moved. Run with the hold on.

begin;
update public.usage_events
   set overage_state = 'review'
 where overage_state = 'pending'
returning tenant_id, call_id, overage_minutes, ended_at;
commit;
