"""Run the paid transition against Stripe TEST mode, with an in-memory tenant.

    python scripts/paid_transition_stripe_test.py

Reads a test key from ~/.openlines-stripe-test-key, outside the repo. It refuses any
other kind of key, and it stubs the database, so no real tenant, customer or payment
can be involved. Everything it creates in the test account is removed at the end.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

KEY_FILE = Path.home() / ".openlines-stripe-test-key"


def load_test_key(path: Path = KEY_FILE) -> str:
    key = path.read_text().strip() if path.exists() else ""
    if not key.startswith("sk_test_"):
        raise SystemExit(f"Refusing to run: {path} must hold a sk_test_ key.")
    return key


def main() -> int:
    key = load_test_key()
    # Set before billing is imported, which reads these once. The database address
    # goes nowhere, so a call that escaped the stub would fail rather than reach data.
    os.environ.update({"STRIPE_SECRET_KEY": key, "SUPABASE_URL": "http://127.0.0.1:9",
                       "SUPABASE_SERVICE_ROLE_KEY": "none", "STRIPE_OVERAGE_PRICE_ID": "",
                       "STRIPE_CALL_MINUTES_PRICE_ID": ""})
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    return asyncio.run(run())


async def run() -> int:
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, patch

    import stripe
    from fastapi import HTTPException

    from routers import billing

    assert stripe.api_key.startswith("sk_test_") and billing.STRIPE_SECRET_KEY.startswith("sk_test_")
    account = stripe.Account.retrieve()
    product = stripe.Product.create(name="Open Lines transition test")
    prices = {
        plan: stripe.Price.create(product=product.id, unit_amount=amount, currency="cad", recurring={"interval": "month"}).id
        for plan, amount in (("starter", 9900), ("business", 37900))
    }
    by_price = {v: k for k, v in prices.items()}
    window = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    address = {"line1": "1 Test St", "city": "Toronto", "state": "ON", "postal_code": "M5V 1A1", "country": "CA"}
    results: list[dict] = []
    customers: list[str] = []

    def tenant(tid, **extra):
        return {"id": tid, "email": "test@example.com", "business_name": "Test", "subscription_plan": "pro",
                "subscription_status": "active", "paid_transition_expires_at": window, **extra}

    def access(t):
        return tuple(t.get(f) for f in ("billing_exempt", "subscription_plan", "subscription_status", "stripe_subscription_id"))

    def subs_on(customer, status="all"):
        return stripe.Subscription.list(customer=customer, status=status, limit=20).data

    def paid_total(customer):
        return sum(i.amount_paid for i in stripe.Invoice.list(customer=customer, limit=20).data)

    async def pay(secret, payment_method):
        return stripe.PaymentIntent.confirm(secret.split("_secret")[0], payment_method=payment_method)

    async def scenario(name, comped, fn):
        tid = f"test-{name}"
        row = tenant(tid, billing_exempt=comped)
        before = access(row)

        async def update(_id, change):
            row.update(change)
            return row

        async def start(plan="business"):
            return await billing.start_paid_transition(
                {"tenant_id": tid, "plan": plan, "interval": "month", "address": address, "name": "Test"}, "Bearer t")

        async def confirm(sub_id):
            return await billing.confirm_payment({"tenant_id": tid, "subscription_id": sub_id}, "Bearer t")

        checks: dict = {}
        with patch.object(billing, "verify_tenant_owner", AsyncMock()), \
                patch.object(billing, "_resolve_price", lambda p, i: prices.get(p)), \
                patch.object(billing, "_plan_from_price", lambda p: by_price.get(p)), \
                patch.object(billing, "_sub_interval", lambda s: "month"), \
                patch.object(billing, "PRICE_IDS", {p: {} for p in prices}), \
                patch.object(billing.db, "get_tenant_by_id", AsyncMock(side_effect=lambda _i: dict(row))), \
                patch.object(billing.db, "update_tenant", AsyncMock(side_effect=update)):
            try:
                await fn(row, before, start, confirm, checks)
            except (AssertionError, HTTPException, stripe.StripeError) as e:
                checks["error"] = f"{type(e).__name__}: {e}"
        if row.get("stripe_customer_id"):
            customers.append(row["stripe_customer_id"])
        results.append({"scenario": name, "passed": "error" not in checks and all(v is True or not isinstance(v, bool) for v in checks.values()), **checks})

    async def happy(row, before, start, confirm, c):
        first = await start()
        c["access_unchanged_while_unpaid"] = access(row) == before
        await pay(first["client_secret"], "pm_card_visa")
        await confirm(first["subscription_id"])
        await confirm(first["subscription_id"])
        cust = row["stripe_customer_id"]
        c["moved_to_paid"] = access(row) == (False, "business", "active", first["subscription_id"])
        c["one_subscription"] = len(subs_on(cust)) == 1
        c["charged_once"] = len([i for i in stripe.Invoice.list(customer=cust).data if i.amount_paid]) == 1
        c["amount_paid_cents"] = paid_total(cust)

    async def double_click(row, before, start, confirm, c):
        a, b = await asyncio.gather(start(), start())
        again = await start()
        cust = row["stripe_customer_id"]
        c["one_subscription"] = len(subs_on(cust)) == 1
        c["same_payment"] = a["client_secret"] == b["client_secret"] == again["client_secret"]
        await pay(a["client_secret"], "pm_card_visa")
        await confirm(a["subscription_id"])
        c["charged_once"] = len([i for i in stripe.Invoice.list(customer=cust).data if i.amount_paid]) == 1

    async def declined(row, before, start, confirm, c):
        first = await start()
        try:
            await pay(first["client_secret"], "pm_card_chargeDeclined")
            c["card_declined"] = False
        except stripe.CardError:
            c["card_declined"] = True
        await confirm(first["subscription_id"])
        c["access_unchanged_after_decline"] = access(row) == before
        retry = await start()
        await pay(retry["client_secret"], "pm_card_visa")
        await confirm(retry["subscription_id"])
        cust = row["stripe_customer_id"]
        c["recovered"] = row["subscription_status"] == "active" and row.get("stripe_subscription_id") == retry["subscription_id"]
        c["one_subscription"] = len(subs_on(cust)) == 1
        c["charged_once"] = len([i for i in stripe.Invoice.list(customer=cust).data if i.amount_paid]) == 1

    async def canceled(row, before, start, confirm, c):
        first = await start()
        stripe.Subscription.cancel(first["subscription_id"])
        await confirm(first["subscription_id"])
        c["access_unchanged_after_cancel"] = access(row) == before
        retry = await start()
        c["new_attempt_works"] = retry["subscription_id"] != first["subscription_id"] and bool(retry.get("client_secret"))
        c["access_still_unchanged"] = access(row) == before

    async def switch_plans(row, before, start, confirm, c):
        await start("business")
        await start("starter")
        last = await start("business")
        cust = row["stripe_customer_id"]
        c["one_open_attempt"] = len(subs_on(cust, "incomplete")) == 1
        await pay(last["client_secret"], "pm_card_visa")
        await confirm(last["subscription_id"])
        c["moved_to_paid"] = row["subscription_plan"] == "business" and row["subscription_status"] == "active"
        c["charged_once"] = len([i for i in stripe.Invoice.list(customer=cust).data if i.amount_paid]) == 1

    try:
        await scenario("complimentary-success", True, happy)
        await scenario("manual-success", False, happy)
        await scenario("double-click", True, double_click)
        await scenario("declined-then-retry", False, declined)
        await scenario("canceled-then-retry", True, canceled)
        await scenario("plan-switching", False, switch_plans)
    finally:
        for customer in customers:
            for sub in subs_on(customer):
                if sub.status not in ("canceled", "incomplete_expired"):
                    stripe.Subscription.cancel(sub.id)
            stripe.Customer.delete(customer)
        stripe.Product.modify(product.id, active=False)

    print(json.dumps({"stripe_account": account.id, "livemode": False, "results": results}, indent=2))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
