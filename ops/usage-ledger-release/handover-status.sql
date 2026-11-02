-- Usage ledger release: read-only status. Changes nothing.
-- in_flight must be 0 before deploying. A row stays 'pending' until it's processed,
-- including events waiting for a retry, so 0 means no event is being worked on.
select json_build_object(
    'hold_on',    exists (select 1 from pg_trigger where tgname = 'usage_release_hold'),
    'held',       (select count(*) from public.webhook_events where status = 'held:usage-042'),
    'held_ids',   (select coalesce(json_agg(id order by created_at), '[]') from public.webhook_events where status = 'held:usage-042'),
    'in_flight',  (select count(*) from public.webhook_events where status = 'pending' and event_type = 'end-of-call-report'),
    'unexpected', (select count(*) from public.webhook_events where status not in ('pending', 'done', 'failed', 'held:usage-042'))
) as status;
