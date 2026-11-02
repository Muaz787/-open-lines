-- 040 — moving a complimentary or manual account onto a paid plan
--
-- Two nullable columns. No data is rewritten, nothing is backfilled, and no
-- existing tenant's behaviour changes when this is applied.
--
-- paid_transition_expires_at: an admin allowed this account to buy a plan, until
-- this time. Null means it may not.
--
-- paid_transition_subscription_id: the subscription being paid for. It is kept apart
-- from stripe_subscription_id so that, until Stripe confirms payment, the webhooks
-- ignore it and the tenant's current access is untouched.

-- Metadata only: the table isn't rewritten. It still needs a brief exclusive lock, and
-- calls read this table, so give up quickly rather than queue behind a long
-- transaction and block every read behind it. If this times out, run it again.
--
-- Safe to run twice. To undo, after confirming no account is mid-transition:
--   select id from public.tenants where paid_transition_subscription_id is not null;
--   alter table public.tenants
--     drop column if exists paid_transition_expires_at,
--     drop column if exists paid_transition_subscription_id;

begin;
set local lock_timeout = '3s';

alter table public.tenants
  add column if not exists paid_transition_expires_at timestamptz,
  add column if not exists paid_transition_subscription_id text;

notify pgrst, 'reload schema';
commit;
