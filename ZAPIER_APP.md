# Open Lines — Zapier Platform App Reference

Everything needed to build/maintain the **Open Lines** app in the Zapier
Platform (Visual Builder). The backend (Phases 1–3) is live; this is the
copy‑paste reference for the Zapier side.

- **Base URL:** `https://backend-production-71174.up.railway.app`
- **Auth:** API Key in the `X-API-Key` header. Keys (`ol_live_…`) are generated
  in the Open Lines dashboard → **Integrations → Zapier & API Access**.
- **Outbound webhook signature:** every trigger POST includes
  `X-OpenLines-Signature: sha256=<hmac>` (HMAC of the body with
  `ZAPIER_SIGNING_SECRET`). Verification is optional.

---

## 1. Authentication (API Key)

**Auth field**
| Label | Key | Type | Required |
|---|---|---|---|
| API Key | `api_key` | Password | yes |

**Send the key as a header** (Request Template / each test request → Show
Options → HTTP Headers):

```
X-API-Key: {{bundle.authData.api_key}}
```

> Zapier also auto‑appends `?api_key=…` to the URL — harmless; the backend
> reads only the header.

**Test request (connection label):**
```
GET {{base}}/zapier/me
```
Returns `{ "tenant_id": "...", "business_name": "..." }`.
**Connection Label:** `{{bundle.inputData.business_name}}`

**Setup gotcha:** "Request Failed / send something in the authData property /
No logs" just means **no account is connected yet** — click *Connect to
Openlines.ai* on the Test Setup tab and paste a real `ol_live_…` key *before*
testing.

---

## 2. Triggers (REST Hook / Instant)

All 7 triggers use the **same wiring** — only the event name, sample, and
output fields differ.

**Subscribe** — `POST {{base}}/zapier/subscribe`
Request Body (JSON):
```json
{ "event": "<EVENT_KEY>" }
```
> `target_url` is optional — the backend falls back to Zapier's native
> `hookUrl`. **Do not put trailing spaces in the `event` key/value** (the
> backend strips them defensively, but keep it clean).

**Unsubscribe** — `DELETE {{base}}/zapier/subscribe/{{bundle.subscribeData.id}}`

**Perform List** — `GET {{base}}/zapier/triggers/<EVENT_KEY>/sample`
(returns an array of one sample record).

**Perform** — leave default:
```js
return [bundle.cleanedRequest];
```

Every webhook payload is **flat** (fields at top level) plus `_event` and
`_tenant_id`.

### Trigger catalog

| Key | Label | Noun | Event fires when |
|---|---|---|---|
| `call_completed` | Call Completed | Call | a call ends and is summarised |
| `new_lead` | New Lead | Lead | a new caller becomes a lead (first sighting) |
| `hot_lead` | Hot Lead | Lead | a call is analysed as urgency = hot |
| `appointment_booked` | Appointment Booked | Appointment | `book_appointment` succeeds |
| `appointment_cancelled` | Appointment Cancelled | Appointment | a caller cancels by phone |
| `deposit_paid` | Deposit Paid | Deposit | a Stripe/Square deposit succeeds |
| `deposit_refunded` | Deposit Refunded | Deposit | a deposit is refunded |

### Sample payloads (for "Define your Output")

`call_completed`
```json
{
  "call_id": "c_sample_123",
  "caller_name": "Jordan Lee",
  "caller_phone": "+14165550123",
  "duration_secs": 142,
  "urgency": "hot",
  "summary": "Caller wants a 3-bed condo viewing this weekend.",
  "suggested_next_step": "Book a Saturday viewing and confirm budget.",
  "transcript": "AI: Thanks for calling... You: Hi, I'm looking for...",
  "key_details": { "budget": "$650k", "timeline": "30 days" },
  "_event": "call_completed",
  "_tenant_id": "a85ba5cf-5c79-4044-8f39-06eaf9d158ff"
}
```

`new_lead`
```json
{ "lead_id": "l_sample_123", "name": "Jordan Lee", "phone": "+14165550123", "status": "new", "_event": "new_lead", "_tenant_id": "..." }
```

`hot_lead`
```json
{ "lead_id": "l_sample_123", "name": "Jordan Lee", "phone": "+14165550123", "urgency": "hot", "summary": "Ready to buy within 30 days, pre-approved.", "key_details": { "budget": "$650k", "timeline": "30 days" }, "_event": "hot_lead", "_tenant_id": "..." }
```

`appointment_booked`
```json
{ "caller_name": "Jordan Lee", "caller_phone": "+14165550123", "service": "Property viewing", "datetime": "2026-07-02T14:00:00+00:00", "duration_minutes": 30, "status": "confirmed", "_event": "appointment_booked", "_tenant_id": "..." }
```

`appointment_cancelled`
```json
{ "caller_name": "Jordan Lee", "caller_phone": "+14165550123", "service": "Property viewing", "datetime": "2026-07-02T14:00:00+00:00", "refunded": true, "refund_amount": 20.0, "currency": "CAD", "_event": "appointment_cancelled", "_tenant_id": "..." }
```

`deposit_paid` / `deposit_refunded`
```json
{ "caller_name": "Jordan Lee", "caller_phone": "+14165550123", "service": "Property viewing", "amount": 20.0, "currency": "CAD", "provider": "square", "_event": "deposit_paid", "_tenant_id": "..." }
```

### Testing a trigger end-to-end
1. Build a Zap: trigger = the event, add any action (e.g. Email by Zapier).
2. **Publish / turn the Zap ON** — REST Hooks don't receive live events from
   the draft editor; turning it ON fires Subscribe and registers the listener.
3. Trigger the real event (make a call, take a deposit, etc.).
4. Check **Zap Runs** for the fired run.

---

## 3. Actions (Zapier → Open Lines)

All actions are `POST`, **JSON body**, `X-API-Key` header inherited from auth.

### Send SMS
`POST {{base}}/zapier/actions/send-sms`
```json
{ "to": "+14165559999", "message": "Hi from Open Lines" }
```
Sends from the tenant's business number. Returns `{ "status": "sent", "to": "..." }`.

### Add Knowledge
`POST {{base}}/zapier/actions/add-knowledge`
```json
{ "text": "Holiday hours: closed Dec 25-26." }
```
Appends to the AI knowledge base and re-prompts the assistant. Returns
`{ "status": "ok", "vectors_stored": N, "entry_id": "..." }`.

### Create / Update Lead
`POST {{base}}/zapier/actions/upsert-lead`
```json
{ "phone": "+14165559999", "name": "Jordan Lee", "status": "new", "note": "From website form" }
```
Upserts by phone. Returns `{ "status": "created|updated", "lead_id": "...", "lead": {...} }`.

---

## 4. Search

### Find Lead by Phone
`GET {{base}}/zapier/leads?phone=+14165559999`
Returns an array (`[lead]` or `[]`) — Zapier "find or create" shape.

---

## 5. Example Zaps (for the directory listing / marketing)

- **Hot Lead → CRM + alert:** Hot Lead → create deal in Salesforce/Pipedrive/
  GoHighLevel + Slack/SMS the owner.
- **Call Completed → Google Sheets / Airtable** call log.
- **Deposit Paid → QuickBooks/Xero** receipt + mark CRM deal won.
- **Appointment Cancelled → free the slot** in Acuity/Calendly + notify team.
- **Missed/after-hours call → task** in Asana/Trello/ClickUp.
- **Web form (Typeform) → Send SMS** from the business number (action).
- **Scheduled → Add Knowledge** (daily specials / hours) (action).

---

## 6. Backend reference (where this lives)

- Router: `backend/routers/zapier.py`
- Service / `emit()` / `SAMPLES` / key hashing: `backend/services/zapier.py`
- Tables: `tenant_api_keys`, `zapier_subscriptions` (`migrations/007_zapier_integration.sql`)
- Trigger emission points:
  - `call_completed` / `new_lead` / `hot_lead` → `services/webhook_processor.py::process_end_of_call`
  - `appointment_booked` / `appointment_cancelled` → `routers/tools.py`
  - `deposit_paid` (Stripe + Square) / `deposit_refunded` → `routers/payments.py`
- Optional env: `ZAPIER_SIGNING_SECRET` (enables the signature header).
