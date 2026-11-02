-- Usage ledger rollback: read-only gate. Changes nothing.
--
-- Every value must be 0 before reverting. resend_exposure is what the old code would
-- send to Stripe on the tenant's next call: usage over the allowance that
-- overage_minutes_reported doesn't cover. pending = 0 alone isn't enough, because a
-- report Stripe accepted just before a crash, or a row in review, is still exposure.
with allowance(plan, minutes) as (values ('starter', 150), ('pro', 400), ('business', 900)),
exposure as (
    select t.id,
           greatest(0, coalesce(t.minutes_used_this_period, 0) - coalesce(a.minutes, 150))
             - coalesce(t.overage_minutes_reported, 0) as minutes
      from public.tenants t
      left join allowance a on a.plan = coalesce(t.subscription_plan, 'starter')
     where t.stripe_customer_id is not null
)
select json_build_object(
    'ledger_pending',          (select count(*) from public.usage_events where overage_state = 'pending'),
    'ledger_review',           (select count(*) from public.usage_events where overage_state = 'review'),
    'webhook_in_flight',       (select count(*) from public.webhook_events where status = 'pending' and event_type = 'end-of-call-report'),
    'resend_exposure_tenants', (select count(*) from exposure where minutes > 0),
    'resend_exposure_minutes', (select coalesce(sum(minutes), 0) from exposure where minutes > 0),
    'exposure',                (select coalesce(json_agg(json_build_object('tenant_id', id, 'minutes', minutes)), '[]') from exposure where minutes > 0)
) as gate;
