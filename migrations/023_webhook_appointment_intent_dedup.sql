-- W6A2 — deduplicate outstanding appointment-cancellation intents.
--
-- A refund that cannot acquire global mutation ownership must not silently
-- discard its cancellation intent: the current owner may finish in
-- create_failed, which releases ownership while deliberately leaving the source
-- ACTIVE. The intent is therefore queued on webhook_events, which already
-- provides durability, retry with backoff, permanent-failure signalling, and a
-- consumer that runs continuously (5-20s poll) rather than daily.
--
-- THE PREDICATE, AUDITED RATHER THAN ASSUMED
-- webhook_events has exactly three status values in executable code:
--   'pending'  column default; set by enqueue_webhook_event, which never writes
--              status at all
--   'done'     mark_webhook_done      (terminal)
--   'failed'   mark_webhook_failed    (terminal, retries exhausted)
-- There is NO 'processing'/'claimed' state: claim_pending_webhook_events only
-- SELECTs status='pending', and mark_webhook_retry updates attempts,
-- last_error and next_retry_at WITHOUT touching status. So a row that is
-- in-flight, and a row waiting on a retry delay, are both still 'pending'.
--
-- 'pending' therefore covers every nonterminal state today. If a future change
-- introduces a claimed/processing status, THIS PREDICATE MUST BE WIDENED or
-- duplicate intents become possible.
--
-- Terminal rows are excluded on purpose: a genuinely later cancellation request
-- for the same appointment must be allowed, including after a permanently
-- failed one — that row is an operator signal, not a permanent veto.
--
-- event_type is pinned in the predicate so this does not impose JSON indexing
-- on every future non-call event type.

create unique index if not exists webhook_events_appointment_intent_idx
    on webhook_events ((payload ->> 'appointment_id'))
    where call_id is null
      and event_type = 'appointment.cancel_requested'
      and status = 'pending';
