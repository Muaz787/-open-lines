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

alter table public.tenants
  add column if not exists paid_transition_expires_at timestamptz,
  add column if not exists paid_transition_subscription_id text;
