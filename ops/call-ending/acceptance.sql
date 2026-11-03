-- Read-only acceptance check for the call-ending change. Run against the first
-- natural call that ends after the release (set :since to the deploy time).
-- Passes only when every "ok" is true. Changes nothing.
with ev as (
  select * from public.webhook_events
   where event_type = 'end-of-call-report' and created_at > '2026-01-01T00:00:00Z'  -- replace with the deploy time
   order by created_at limit 1),
msgs as (
  select m.ordinality as n, m.value->>'role' as role, coalesce(m.value->>'message', '') as text
    from ev, jsonb_array_elements(ev.payload->'message'->'artifact'->'messages') with ordinality m(value, ordinality)),
bot as (select * from msgs where role in ('bot', 'assistant')),
closing as (select * from bot where text ~* '(goodbye for now|bye for now|bye bye|take care|have a (great|good|nice) day)')
select json_build_object(
  'call_id', (select call_id from ev),
  'ended_reason', json_build_object('ok', (select payload->'message'->>'endedReason' from ev) = 'assistant-ended-call',
                                    'value', (select payload->'message'->>'endedReason' from ev)),
  'endcall_offered', json_build_object('ok', (select bool_or(t->>'type' = 'endCall') from ev,
      jsonb_array_elements(coalesce(payload->'message'->'call'->'assistantOverrides'->'model'->'tools', '[]'::jsonb)) t)),
  'one_closing_message', json_build_object('ok', (select count(*) from closing) = 1,
                                           'count', (select count(*) from closing)),
  'closing_is_last', json_build_object('ok', (select max(n) from closing) = (select max(n) from bot)),
  'no_restarted_greeting', json_build_object('ok', not exists (
      select 1 from bot where n > (select min(n) from bot)
         and text ~* '(virtual receptionist|my name is|may i have your name|thank you for calling|thanks for calling .*how can i)')),
  'nothing_after_closing', json_build_object('ok', not exists (
      select 1 from bot where n > coalesce((select min(n) from closing), 1e9)))
) as r;
