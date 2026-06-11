# Open Lines — Analytics Events (PostHog)

Quick reference for every product event we track. Frontend events fire from
the browser (`frontend/src/lib/analytics.ts`); backend events fire
server-side (`backend/services/analytics.py`).

**Setup:** set `NEXT_PUBLIC_POSTHOG_KEY` (Vercel) and `POSTHOG_API_KEY`
(Railway). Both default to the US cloud host and no-op silently when unset.

## Marketing funnel (frontend, anonymous)

| Event | When it fires | Key properties | Why it matters |
|---|---|---|---|
| `$pageview` | every page load + SPA navigation (automatic) | url | traffic baseline |
| `landing_page_viewed` | landing page mounts | page_path, referrer, utm_* | top of funnel |
| `pricing_page_viewed` | pricing page mounts | page_path, referrer, utm_* | purchase intent |
| `demo_cta_clicked` | any "Book a Demo" button | location (nav/hero/bottom_cta) | demo pipeline |
| `get_started_clicked` | any onboarding CTA | location, plan (on pricing) | signup intent |
| `login_clicked` | "Sign in" in nav | location | returning users |

## Signup & onboarding (frontend)

| Event | When it fires | Key properties | Why it matters |
|---|---|---|---|
| `signup_started` / `onboarding_started` | onboarding page mounts | first-touch utm/referrer | funnel entry |
| `onboarding_step_completed` | each step finishes | step_number, step_name (basics / knowledge_contact), industry | drop-off per step |
| `business_profile_completed` | step 1 "Next" | industry | profile completion |
| `instructions_added` | submit, if instructions present | length only — never the text | feature adoption |
| `knowledge_base_uploaded` | docs uploaded during onboarding | file_count only — never names/contents | KB adoption |
| `onboarding_completed` | provisioning succeeds | tenant_id, first-touch utm | THE conversion event |
| `login_completed` | successful sign-in | — | retention |

Users are identified with their Supabase user id at signup/login
(`identify`), with safe props only: email, tenant_id, business_name,
industry. Logout calls `reset()` so devices aren't cross-contaminated.

## Backend conversion events (server-side, source of truth)

| Event | When it fires | Key properties | Why it matters |
|---|---|---|---|
| `tenant_created` | provisioning completes | tenant_id, business_name, industry, country | server-truth signup |
| `signup_completed` | auth user created + linked | same | account creation |
| `phone_number_provisioned` | Twilio number live | tenant_id | activation step |
| `calendar_connected` | Google OAuth callback succeeds | tenant_id | booking enabled (frontend only tracks `calendar_connect_started`) |
| `subscription_started` | Stripe checkout.session.completed | tenant_id, plan | revenue |
| `payment_failed` | subscription goes past_due | tenant_id, status | churn risk alert |
| `subscription_canceled` | subscription deleted | tenant_id | churn |

## Call & booking activity (backend)

| Event | When it fires | Key properties | Why it matters |
|---|---|---|---|
| `call_received` | inbound call hits the AI | tenant_id, caller_type (new/returning), has_calendar | core usage |
| `call_completed` | end-of-call report processed | tenant_id, call_id, duration_seconds | usage depth |
| `call_summary_generated` | GPT analysis finishes | tenant_id, call_id, urgency | AI quality signal |
| `owner_notification_sent` | WhatsApp or email summary sent | tenant_id, channel | notification delivery |
| `appointment_booking_started` | AI checks availability | tenant_id | booking intent |
| `calendar_event_created` | Google event created | tenant_id | booking pipeline |
| `appointment_booked` | appointment saved | tenant_id, service, duration_minutes, is_reschedule | THE activation event |
| `sms_confirmation_sent` | caller SMS confirmation sent | tenant_id | confirmation delivery |
| `appointment_cancelled` | AI cancels a booking | tenant_id | booking churn |
| `dashboard_viewed` (frontend) | dashboard loads | tenant_id | engagement / DAU |

**Tip:** there is no separate `first_test_call` event — use PostHog's
"first time performed" filter on `call_received` to build the
signup → first call activation funnel.

## Privacy rules (enforced in code, keep it that way)

- **Autocapture is OFF** — the dashboard renders caller phone numbers, lead
  names, and call transcripts; autocapture would send clicked-element text.
- **Session recording is OFF** for the same reason.
- Events never include: passwords, call transcripts or summaries, caller
  names or phone numbers, uploaded file names/contents, calendar event
  details, or knowledge-base text. Only ids, counts, durations, statuses,
  urgency levels, and plan names.
- Anonymous visitors don't get person profiles (`person_profiles:
  'identified_only'`) — profiles exist only after signup/login.
- Backend captures are fire-and-forget and no-op when `POSTHOG_API_KEY` is
  unset; analytics can never break a call, booking, or payment.
