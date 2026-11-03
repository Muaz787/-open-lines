-- 044 — each call keeps its own summary and rating
--
-- The summary, urgency, key details and next step from a call's analysis were only
-- written to the caller's lead, which every later call overwrites. The calls page
-- read them from the lead, so every call from a caller showed the newest call's
-- summary and rating, including five-second calls that had no analysis at all.
--
-- These columns hold the analysis of the call itself. They are written once, when
-- the call is processed. Older calls are left empty: the dashboard says no summary
-- was saved for them rather than borrowing the lead's. Leads keep their own copy.
--
-- Adds nullable columns only: no data changes. Safe to run twice. Apply this BEFORE
-- deploying the backend that reads them, or the calls list will fail to load.
-- Migration 043's grants cover new columns: anon and authenticated get none.

begin;
set local lock_timeout = '3s';

alter table public.calls
  add column if not exists summary text,
  add column if not exists urgency text,
  add column if not exists key_details jsonb,
  add column if not exists suggested_next_step text;

comment on column public.calls.summary is 'Summary of this call only, written once when it is processed.';
comment on column public.calls.urgency is 'hot, warm or cold for this call only; null when the call was not analysed.';

notify pgrst, 'reload schema';
commit;
