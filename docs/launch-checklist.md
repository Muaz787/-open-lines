# Open Lines — Launch Checklist

Single view of everything left before public go-live. Grouped by area. Deep-dive
docs are linked where they exist. Update the status boxes as you go.

Legend: `[x]` done · `[ ]` open · `[~]` in progress / waiting on a third party.

---

## 1. Payments & billing
See `docs/stripe-go-live.md` for the full Stripe test→live steps.

- [x] **Stripe subscriptions live** — 4 products, monthly+annual prices, metered overage; live keys in Railway, `pk_live` in Vercel.
- [x] **Stripe Tax** live — GST/HST registration 716179239RT0001 + origin address; verified HST 13% computes on a live Pro invoice ($199 → $224.87).
- [x] **Square deposits** — already live.
- [x] **Stripe deposits (Connect) — platform APPROVED by Stripe (2026-07-04).** Live connected-account creation now works. Also fixed: the deposit onboarding self-heal now drops a stale test-mode connected account on a `PermissionError` (not just `InvalidRequestError`) so the live key recreates it cleanly. Remaining is just the live deposit smoke test below.
- [ ] **Confirm `payments.refunded_at` column** exists in Supabase (deposit refund flow). If missing: `alter table payments add column if not exists refunded_at timestamptz;`
- [ ] **End-to-end live smoke test** — one real subscription checkout → confirm tenant flips `incomplete → active`, billing webhook returns 200, invoice shows GST/HST. Then a live deposit + refund once Connect review clears.

## 2. Legal & compliance (PIPEDA)
See PIPEDA notes; drafts on branch `pipeda-legal-docs`.

- [x] **Call recording + AI disclosure** — "virtual receptionist, call may be recorded" in the greeting.
- [x] **Data retention/deletion** flows shipped.
- [ ] **Lawyer review** of Privacy Policy + Terms of Service, then merge `pipeda-legal-docs`.
- [ ] **Privacy Officer** named + **privacy@openlines.ai** and **support@openlines.ai** inboxes live and monitored.
- [ ] **Public privacy/terms pages** linked from footer + signup.

## 3. Email & deliverability
- [x] **Lifecycle/transactional email suite** — one branded `services/email.py` covering welcome, subscription-activation, deposit-received, cancellation, call-summary and trial reminders. Shared layout + plain-text part + reply-to `support@` + company mailing address in footer. Trial nudges carry a CASL unsubscribe link + `List-Unsubscribe` headers, backed by `/email/unsubscribe` and honored by the trial cron.
- [x] **Enable Stripe customer emails** — "Successful payments" + "Invoices" turned on in live mode. Covers invoice/receipt emails.
- [x] **Resend SMTP verified** for Supabase auth emails — SPF/DKIM on the sending domain confirmed.
- [ ] Do one live end-to-end pass of each lifecycle email (welcome on signup, activation on subscribe, deposit + cancellation on a booking) and confirm they land in the inbox (not spam) from the production domain, not sandbox.
- [x] **`EMAIL_UNSUBSCRIBE_SECRET` set** in prod to pin unsubscribe-token signing.

## 4. Infrastructure & ops
- [ ] **Railway daily cron** configured for: website re-crawl (stale KB refresh) + free-trial reminder emails. Confirm the schedule is actually running.
- [x] **Database migrations applied** in production Supabase — ran **`migrations/000_consolidated_schema.sql`** (core schema + migrations 001–007 + `payments` + Microsoft calendar cols + email lifecycle cols). This also covers the `oauth_states` migration in §5 and the two new email columns. Recommended: spot-check that `tenants.marketing_unsubscribed_at` / `subscription_activated_email_sent`, `oauth_states`, and `payments` all exist.
- [ ] **Env vars set in prod**: `VAPI_SERVER_SECRET`, `MISTRAL_API_KEY`, Stripe live keys, Square production keys, Resend key. Admin → System Health should be all-green.
- [ ] **Backups / monitoring** — confirm Supabase backups on; a basic uptime check on the Railway backend URL.

## 5. Security
See security hardening notes.

- [x] **`oauth_states` migration applied** (via `000_consolidated_schema.sql`). Still confirm **`VAPI_SERVER_SECRET`** is set in prod (tenant-auth / IDOR + OAuth state nonce hardening; also backs unsubscribe-token signing if `EMAIL_UNSUBSCRIBE_SECRET` were unset).
- [ ] Confirm tenant-scoped authz (`verify_tenant_owner`) covers all tenant-data endpoints.

## 6. Business & insurance
- [ ] **E&O / cyber insurance** in place before taking paying customers.
- [ ] **Incorporation / GST-HST account** active (registration 716179239RT0001 — done for tax).
- [ ] **Support process** — who answers support@, expected response time, escalation.

## 7. Marketing / site
- [x] Landing + sub-pages (How it works / Industries / Platform / Pricing) live with mobile nav.
- [x] Live demo phone number on the homepage (+1 438 839 3907).
- [ ] Final copy/pricing review; analytics events firing in production (check the funnel).
- [x] **`robots.txt` + `sitemap.xml`** — generated via `app/robots.ts` + `app/sitemap.ts`; public marketing pages indexable, app/account routes disallowed.
- [x] **Basic SEO metadata** — `metadataBase` + per-page `title`/`description`/canonical on all public pages; branded OG + Twitter card image generated at `app/opengraph-image.tsx`.

---

## Blocking vs. nice-to-have
**Hard blockers before charging real customers:** lawyer-reviewed legal docs + privacy inboxes (§2), Resend auth-email deliverability (§3), E&O/cyber insurance (§6), prod migrations + env (§4/§5).

**Not blocking general launch:** Stripe **deposits** are now unblocked — Connect review cleared 2026-07-04, so subscriptions, Square deposits **and** Stripe deposits all work. Just run the live deposit + refund smoke test (§1) to confirm end-to-end.

---

**Owner:** _______   **Target launch date:** _______
