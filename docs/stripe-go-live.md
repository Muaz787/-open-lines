# Stripe — Test → Live Go-Live Checklist

Switching Stripe from test mode to **live** for both **subscriptions (billing)** and **deposit collection (Connect)**. They share **one** secret key. Work through top to bottom; tick each box. Square deposits are already live and are unaffected.

> Backend URL used below: `https://backend-production-71174.up.railway.app` (this is `APP_BACKEND_URL` — confirm it matches Railway).
> All backend env vars go in **Railway**; the one `NEXT_PUBLIC_*` var goes in **Vercel** and needs a redeploy.

---

## 1. Create Live Products, Prices & the usage meter
In the Stripe Dashboard, flip the top-right toggle to **Live mode**, then:

- [ ] Create 3 products with **monthly + annual** recurring prices (CAD):
  - Starter — **$99/mo**, **$990/yr**
  - Pro — **$199/mo**, **$1,990/yr**
  - Business — **$379/mo**, **$3,790/yr**
- [ ] Create a **Billing Meter** named/event `call_minutes`, and a **metered price** of **$0.69 / unit** linked to it (this is the overage price).
- [ ] Copy every resulting **live price ID** (`price_…`) for the env vars in step 2.

> Test-mode price IDs do NOT work in live — these must be brand-new live IDs.

## 2. Environment variables

**Railway (backend):**
- [ ] `STRIPE_SECRET_KEY` → `sk_live_…` *(drives BOTH subscriptions and Connect deposits)*
- [ ] `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_STARTER_ANNUAL`
- [ ] `STRIPE_PRICE_PRO`, `STRIPE_PRICE_PRO_ANNUAL`
- [ ] `STRIPE_PRICE_BUSINESS`, `STRIPE_PRICE_BUSINESS_ANNUAL`
- [ ] `STRIPE_CALL_MINUTES_PRICE_ID` → the live metered overage price
- [ ] `STRIPE_WEBHOOK_SECRET` → from the **billing** webhook (step 3)
- [ ] `STRIPE_PAYMENTS_WEBHOOK_SECRET` → from the **Connect/payments** webhook (step 3)

**Vercel (frontend):**
- [ ] `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` → `pk_live_…` (used by the card element in `PaymentForm.tsx`) → **redeploy Vercel** after setting (NEXT_PUBLIC vars are baked at build time)

## 3. Webhooks (create BOTH in Live mode)
Each live webhook has its **own** signing secret — copy it into the matching env var above.

**A. Billing webhook — "Your account" events**
- [ ] Endpoint: `https://backend-production-71174.up.railway.app/billing/webhook`
- [ ] Events (exactly what the code handles):
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
- [ ] Copy signing secret → `STRIPE_WEBHOOK_SECRET`

**B. Deposits webhook — "Connected accounts" events** (toggle "Listen to events on Connected accounts")
- [ ] Endpoint: `https://backend-production-71174.up.railway.app/payments/webhook`
- [ ] Events:
  - `checkout.session.completed`
  - `checkout.session.expired`
  - `charge.refunded`  ← required for deposit refunds to fire in live
- [ ] Copy signing secret → `STRIPE_PAYMENTS_WEBHOOK_SECRET`

## 4. Activate Connect & Tax in Live
- [ ] **Stripe Connect** platform profile complete in live: **Funds flow = "Sellers collect payments directly" (direct charges)** — this MUST match the code, which creates Checkout Sessions with `stripe_account=…` and no `application_fee` (`services/stripe_service.py`). Also confirm the negative-balance-liability + seller-compliance acknowledgements show **Completed**.
  - ⚠️ **Connect platform review gate:** a brand-new live Connect platform sits in **"Your application is in review"** for a period after setup. While in review you can only create **test** connected accounts — `POST /v1/accounts` returns 400 in live and the "Connect Stripe" button fails. This is a Stripe-side review, not a bug and not something env vars fix. Wait for Stripe to clear it (Connect → Overview stops showing "in review"), then retry. Contact Stripe support to expedite if needed.
- [ ] **Stripe Tax** enabled in live + your **GST/HST registration** (716179239RT0001) + **origin/head-office address** set in the live Tax settings.
  - ⚠️ **Required for subscriptions too:** the subscribe flow sends `automatic_tax={"enabled": True}` (`routers/billing.py`). If live Tax isn't configured, `Subscription.create` throws and the UI shows **"Failed to create subscription: …"**. Subscriptions worked in test only because test-mode Tax is auto-configured.
- [ ] Confirm the `payments` table has a `refunded_at` column (from the refund work) — if missing, run: `alter table payments add column if not exists refunded_at timestamptz;`

## 5. Smoke test in live (real card, small amounts)
- [ ] **Subscription:** run a real checkout for a plan → confirm the tenant flips to `active` + correct `subscription_plan` in the dashboard/DB. Then cancel → confirm it downgrades.
- [ ] **Deposit:** connect a Stripe account on a tenant → have the AI (or manually) send a deposit link → pay it → confirm the deposit shows `succeeded` + the caller gets the confirmation SMS.
- [ ] **Refund:** refund that test deposit in Stripe → confirm `charge.refunded` fires, the payment flips to `refunded`, and the appointment cancels.
- [ ] Check the two webhooks in the Stripe Dashboard show **200s** (no signature errors → secrets are correct).

## 6. Gotchas / rollback
- If webhooks return **400 "signature"**, the wrong secret is in the wrong env var (billing vs payments) — they are NOT interchangeable.
- If checkout says "no such price", a price ID is still a **test** ID or the wrong interval.
- Deposits use the **Connected accounts** webhook; subscriptions use the **Your account** webhook — keep them separate.
- To roll back, swap the env vars back to `sk_test_…` / test price IDs / test webhook secrets and redeploy. No code changes are involved — this is purely configuration.

---

**Owner:** _______   **Date completed:** _______
