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
Note: the old `pipeda-legal-docs` branch is too stale to merge (would revert ~9.8k lines of newer main). Its improved privacy/terms text was cherry-picked onto current main instead.

- [x] **Call recording + AI disclosure** — "virtual receptionist, call may be recorded" in the greeting.
- [x] **Data retention/deletion** flows shipped (purge runs in the daily cron — see §4).
- [x] **PIPEDA-aligned privacy/terms live (2026-07-10)** — explicit PIPEDA + controller/processor roles, AI/recording consent notice, cross-border processing disclosure, retention specifics, breach-notification commitment, and OPC complaint right.
- [x] **Privacy page restructured (Chatbase-inspired, 2026-07-10)** — **role-based Privacy Officer** (no named individual; still PIPEDA-compliant — accountable person designated internally, only the contact is published), dedicated **`/subprocessors`** page (maintained provider/purpose/location table, linked from the policy + footer + sitemap), plus new **"no AI model training"**, **"Cookies & analytics"** (PostHog), and **"Children's data"** sections. Did NOT copy GDPR/SCC or SOC-2 claims.
- [x] **Privacy Officer + inboxes** — role-based Privacy Officer; contacts **privacy@openlines.ai** (privacy) and **support@openlines.ai** (general/terms). ⚠️ Keep both inboxes actively **monitored** — the policy directs access requests/complaints there.
- [x] **Public privacy/terms/sub-processors pages** linked from **footer + signup** (signup consent link added).
- [x] **Acceptable Use Policy + Data Processing Agreement pages (2026-07-13)** — new `/acceptable-use` (voice/AI-specific: impersonation & synthetic-voice, CASL/TCPA, disclosure) and `/dpa` (controller/processor terms for larger B2B customers). Adapted to our real posture, **not** the partner's generic drafts: Ontario law, `privacy@`/`support@`, PIPEDA-centered (GDPR/CCPA only "where applicable"), honest Canada-residency (primary DB `ca-central-1`, some US sub-processors), DPA liability defers to the Terms' cap, links to `/subprocessors` + `/privacy`, and **no reseller ("GoodSpeed") language** (no signed channel agreement). Incorporated into the Terms (§4 AUP, §5 DPA) so they're enforceable; added to footer + sitemap. Source docs came from a potential reseller partner; SLA / Cookie / Security-policy / their Terms+Privacy intentionally **not** adopted.
- [ ] **Lawyer review** of the Privacy Policy + Terms + **new AUP & DPA** — still drafts until reviewed. The partner-supplied SLA especially (99.9% uptime + service-credit schedule) was deliberately held back as a commitment we can't yet stand behind on the current infra.

## 3. Email & deliverability
- [x] **Lifecycle/transactional email suite** — one branded `services/email.py` covering welcome, subscription-activation, deposit-received, cancellation, call-summary and trial reminders. Shared layout + plain-text part + reply-to `support@` + company mailing address in footer. Trial nudges carry a CASL unsubscribe link + `List-Unsubscribe` headers, backed by `/email/unsubscribe` and honored by the trial cron.
- [x] **Enable Stripe customer emails** — "Successful payments" + "Invoices" turned on in live mode. Covers invoice/receipt emails.
- [x] **Resend SMTP verified** for Supabase auth emails — SPF/DKIM on the sending domain confirmed.
- [ ] Do one live end-to-end pass of each lifecycle email (welcome on signup, activation on subscribe, deposit + cancellation on a booking) and confirm they land in the inbox (not spam) from the production domain, not sandbox.
- [x] **`EMAIL_UNSUBSCRIBE_SECRET` set** in prod to pin unsubscribe-token signing.

## 4. Infrastructure & ops
- [x] **Railway daily cron** confirmed running (heartbeat: last ran ~20h ago, 2026-07-10). `scripts/recrawl_cron.py` runs in one pass: website re-crawl + free-trial reminders + **data-retention purge** + call-intent backfill, and writes `cron_last_run` to system_meta (Admin → System Health).
- [x] **Database migrations applied** in production Supabase — ran **`migrations/000_consolidated_schema.sql`** (core schema + migrations 001–007 + `payments` + Microsoft calendar cols + email lifecycle cols). This also covers the `oauth_states` migration in §5 and the two new email columns. Recommended: spot-check that `tenants.marketing_unsubscribed_at` / `subscription_activated_email_sent`, `oauth_states`, and `payments` all exist.
- [ ] **Env vars set in prod**: `VAPI_SERVER_SECRET`, `MISTRAL_API_KEY`, Stripe live keys, Square production keys, Resend key. Admin → System Health should be all-green.
- [ ] **Backups / monitoring** — confirm Supabase backups on; a basic uptime check on the Railway backend URL.

## 5. Security
See security hardening notes.

- [x] **`oauth_states` migration applied** (via `000_consolidated_schema.sql`). **`VAPI_SERVER_SECRET`** confirmed set in prod.
- [x] **Confirmed tenant-scoped authz** (`verify_tenant_owner` binds the Supabase JWT's `tenant_id` to the path; router-level dependency on tenant-data routers) — no IDOR found in the security audit.
- [x] **Security audit + hardening (2026-07-06)** — set `APP_ENV=production` (stops the catch-all middleware leaking internal exception detail; `/health` now reports `production`); `verify_vapi_server_secret` now **fail-closed** (503 if unset) with `hmac.compare_digest`; admin key uses `compare_digest`; dropped `localhost` from the prod CORS allowlist. Verified good: encrypted-at-rest tokens, `_sanitize_tenant` denylist, signature-verified Stripe/Square webhooks (Square fail-closed), Firecrawl-only scraping (no SSRF into our network), prompt-injection defenses, leak-free Zapier endpoints.

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

## 8. Product / onboarding
- [x] **Gender-matched receptionist voice** — the agent name now drives the ElevenLabs voice: Alex/Sam → male ("Brian"), Emma/Sophia/Mia → female ("Sarah"). Custom names show a Female/Male voice picker in onboarding (defaults female). `tenant.voice_id`/`voice_gender` stored at provision; existing tenants get a gender-correct voice on their next assistant rebuild. Both voices confirmed present in the Vapi 11labs library.
- [x] **Male voice on real calls — root-caused & fixed (2026-07-09).** The male voiceId ("Brian") was always valid (Vapi "Talk" played male); the bug was the `assistant-request` webhook hard-coding the per-call voice to the default **female** and ignoring `tenant.voice_id`, so every *real* call came out female. Now the per-call override uses the tenant's voice — applies live on the next call for all tenants, no re-provision. Suggested: one real call to confirm male end-to-end.
- [x] **Prompt system v2 shipped (2026-07-05)** — explicit precedence (safety > owner operating rules > industry template > untrusted KB), structured owner layer (business subtype/tone/ordered priorities + editable business instructions in Settings), shared "don't guess — escalate" uncertainty rule, custom-tenant prompts now rebuild + refresh KB (no longer frozen), and Parliament removed from onboarding (backend template retained). Migration applied in prod. **Verified in prod:** Settings save → validate → rebuild → Vapi push, clean logs (checks #2/#3). **Pending spot-check:** #1 Settings card renders, #4 a custom-industry KB sync rebuild, #5 an existing parliament tenant rebuild.
- [x] **New industries shipped (2026-07-06)** — **Automotive** (one intent-branching template: sales / service & repair / body & collision), **Insurance** (compliance-first: intake + route only, no advice/quotes/binding, claims escalated), **Government & Public Office** (`public_office` — non-partisan elected-official's office covering federal MP / provincial MPP-MLA / municipal councillor / school board trustee; casework + service requests, jurisdiction routing), and **Courier & Delivery** (`courier` — order intake: pickup/drop-off, item, timing; positioned for businesses losing orders to phone outages). Each has a template + qualification fields; all industry whitelists mirrored; website classifier detects them (and no longer auto-detects `parliament`, which is kept as a legacy alias). No schema/migration; existing tenants unaffected.
- [x] **Caller-name capture + bulk reprompt (2026-07-06)** — shared receptionist layer now always asks for the caller's name early (confirm spelling for unfamiliar names, never guess; respects returning-caller recognition), and `clinic`/`parliament`/`public_office` templates gained an explicit name-capture Step 1 — reduces "unknown caller" leads. New admin `POST /admin/reprompt-all` (admin-key gated, non-fatal per tenant) rolls shared-layer prompt changes out to all existing tenants immediately. Ran it in prod: **4/4 tenants rebuilt, 0 failures.**
- [x] **Demo-bug fixes (2026-07-09)** — from a live demo: (1) **per-call voice** now uses `tenant.voice_id` in the assistant-request override (was defaulting female on every real call); (2) **no phantom bookings** — when no calendar is connected, a `NO_BOOKING_NOTE` stops the AI confirming appointments it has no tool to make (it captures the time + says the team will follow up), which also fixes the reschedule dead-end; (3) **post-onboarding calendar banner** on the dashboard when the line is live but no calendar (Google/Outlook/Square) is connected. All live in prod. **Follow-up:** if a call still drops mid-reschedule after this, pull the Vapi call log for Fix 4 (silence-timeout / tool robustness).
- [x] **Province-aware phone numbers (2026-07-11)** — new numbers now stay in the business's province: the search tries the preferred area code, then EVERY area code in that province (from the phone's area code, else the website-detected province, else Ontario), and only does a national search as a last resort. Fixes Ontario businesses getting Quebec (438) numbers. Website analyzer now emits a 2-letter province. Forward-looking; existing tenants keep their numbers.
- [x] **AI-drafted business description (2026-07-11)** — the "Describe your business" onboarding field now pre-fills with a natural first-person 1–2 sentence description generated during the website crawl (same GPT call, no extra cost); tenant can edit/replace/record over it, and manual input is preserved. Also sharpens the custom-industry prompt.

---

## Blocking vs. nice-to-have
**Hard blockers before charging real customers:** lawyer-reviewed legal docs + privacy inboxes (§2), Resend auth-email deliverability (§3), E&O/cyber insurance (§6), prod migrations + env (§4/§5).

**Not blocking general launch:** Stripe **deposits** are now unblocked — Connect review cleared 2026-07-04, so subscriptions, Square deposits **and** Stripe deposits all work. Just run the live deposit + refund smoke test (§1) to confirm end-to-end.

---

**Owner:** _______   **Target launch date:** _______
