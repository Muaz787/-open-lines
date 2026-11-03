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
goodbye as (select coalesce(
    (select payload->'message'->'call'->'assistantOverrides'->>'endCallMessage' from ev),
    (select t->'messages'->0->>'content' from ev, jsonb_array_elements(ev.payload->'message'->'call'->'assistantOverrides'->'model'->'tools') t
      where t->>'type' = 'endCall')) as configured),
closing as (select * from bot where text ~* '(goodbye|bye for now|bye bye|take care|have a (great|good|nice) day|thanks for calling)' and n > (select min(n) from bot))
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
      select 1 from bot where n > coalesce((select min(n) from closing), 1e9))),
  -- The whole goodbye was spoken: the logged line (what the voice actually said)
  -- matches the configured endCallMessage word for word, and it finished before
  -- the call ended. A clipped goodbye is logged short, as on 3 Nov (46ac9156).
  'goodbye_complete', json_build_object(
      'ok', coalesce(regexp_replace(lower((select text from bot order by n desc limit 1)), '[^a-z ]', '', 'g')
          = regexp_replace(lower((select configured from goodbye)), '[^a-z ]', '', 'g'), false),
      'said', (select text from bot order by n desc limit 1),
      'configured', (select configured from goodbye)),
  'goodbye_inside_call', json_build_object('ok',
      (select (m.value->>'endTime')::numeric from ev, jsonb_array_elements(ev.payload->'message'->'artifact'->'messages') m
        where m.value->>'role' = 'bot' order by (m.value->>'time')::numeric desc limit 1)
      <= extract(epoch from (select (payload->'message'->>'endedAt')::timestamptz from ev)) * 1000)
) as r;
