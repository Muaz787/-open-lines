# WhatsApp Call-Summary Notifications — Setup (Production)

Owner-facing call-summary notifications over **production WhatsApp**, via a single
central OpenLines sender and an **approved Twilio Content Template**. No sandbox,
no freeform messages, no customer-facing WhatsApp (owner only).

> Scope: the business owner receives a call summary on WhatsApp when they enable
> the WhatsApp channel in Settings. The recipient is the tenant's
> `sms_alert_number` (falls back to `business_phone`). The same number is used for
> SMS.

---

## How it works (code)

- `services/telephony.py` → `send_whatsapp_template(to_number, variables)`: sends
  from the central account (`_master_client()`) using `content_sid` +
  `content_variables`. Returns `False` and logs if env isn't configured. **Never
  freeform.**
- `services/webhook_processor.py`: independent per-channel toggles
  (`email_enabled`, `sms_enabled`, `whatsapp_enabled`). WhatsApp branch fires only
  when `whatsapp_enabled` and a mobile number exists; non-fatal.
- `_whatsapp_summary_vars()` builds the ordered template variables (single-line,
  length-bounded).
- Settings UI: three independent toggles (Email / SMS / WhatsApp) + a shared
  mobile field.

---

## 1. Prerequisites (external, with lead time)

TrustHub Business Profile approval is necessary but **not sufficient**. Also do:

1. **WhatsApp Sender** in Twilio (Messaging → Senders → WhatsApp senders):
   register a WhatsApp Business Account (WABA), complete **Facebook Business
   Manager verification**, choose the sender phone number, and get the **display
   name** approved by Meta.
2. The sender number becomes `TWILIO_WHATSAPP_FROM`.

---

## 2. Content Template (Utility category)

Create in Twilio (Content Template Builder), category **Utility** (not Marketing),
and submit for WhatsApp approval. Body with six variables:

```
New call for {{1}}
Caller: {{2}}
Priority: {{3}}
Summary: {{4}}
Recommended next step: {{5}}
```

Five variables (WhatsApp rejects two variables on one line, so caller name +
number are combined into {{2}}). Mapping (set in `_whatsapp_summary_vars`):

| # | Value |
|---|-------|
| 1 | Business name |
| 2 | Caller name • number |
| 3 | Priority / urgency (Hot/Warm/Cold) |
| 4 | Call summary |
| 5 | Suggested next step |

After approval, copy the **Content SID** (`HX…`) → `TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID`.

---

## 3. Environment variables (backend / Railway)

| Var | Example | Notes |
|-----|---------|-------|
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+1XXXXXXXXXX` | The central WhatsApp sender. `whatsapp:` prefix added automatically if omitted. |
| `TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID` | `HXxxxxxxxx…` | Approved **call-summary** Content SID. |
| `TWILIO_WHATSAPP_DEPOSIT_TEMPLATE_SID` | `HXxxxxxxxx…` | Approved **deposit-received** Content SID. |
| `TWILIO_WHATSAPP_CANCEL_TEMPLATE_SID` | `HXxxxxxxxx…` | Approved **cancellation/refund** Content SID. |

Uses the existing master Twilio credentials (the same account used for
provisioning). **Each WhatsApp send is skipped if the sender or that specific
template SID is unset** (email/SMS unaffected). Do not commit these values.

### Deposit-received template (4 variables)
```
Deposit received for {{1}}
{{2}} paid {{3}}.
Appointment:
{{4}}
Status: Confirmed
```
| # | Value | Sample |
|---|-------|--------|
| 1 | Business name | Sam Real Estate |
| 2 | Caller name • number | John Doe • +1 416-555-0123 |
| 3 | Amount paid + currency | $50.00 CAD |
| 4 | Appointment (date · service) | Monday, Jun 12 · Apartment viewing |

### Cancellation / refund template (4 variables)
```
Appointment cancelled — {{1}}
{{2}}
Service: {{3}}
{{4}}
```
| # | Value | Sample |
|---|-------|--------|
| 1 | Business name | Sam Real Estate |
| 2 | Caller name • number | John Doe • +1 416-555-0123 |
| 3 | Service | Apartment viewing |
| 4 | Deposit outcome | Deposit of $50.00 CAD refunded. |

One cancellation template covers all cases — {{4}} is "Deposit of … refunded.",
"Deposit of … forfeited (cancelled inside the refund window).", or "No deposit
was on file." depending on the booking.

---

## 4. Database migration

```sql
alter table tenants add column if not exists email_enabled    boolean default true;
alter table tenants add column if not exists sms_enabled       boolean default false;
alter table tenants add column if not exists whatsapp_enabled  boolean default false;

-- Backfill from the old settings so existing tenants keep current behaviour.
update tenants set
  email_enabled = (coalesce(email_notifications, false) and coalesce(notification_channel, 'email') in ('email', 'both')),
  sms_enabled   = (coalesce(email_notifications, false) and coalesce(notification_channel, 'email') in ('sms', 'both'));
```

(The legacy `email_notifications` / `notification_channel` columns are left in
place, unused, for rollback safety.)

---

## 5. Opt-in & compliance

- Enabling the WhatsApp toggle in Settings is the owner's **opt-in**.
- The number must be a **WhatsApp-registered** mobile.
- Privacy policy lists **WhatsApp (Meta)** as a sub-processor (notifications carry
  caller PII to the owner).
- **Cost:** Meta bills per conversation; Utility templates are cheaper than
  Marketing — factor into margins.

---

## 6. Testing

1. Apply the migration; set both env vars to the approved sender + template.
2. On a test tenant, set `sms_alert_number` to a WhatsApp-registered mobile and
   enable the **WhatsApp** toggle.
3. Place a test call. Confirm the WhatsApp arrives and the Railway log shows
   `WhatsApp template sent to …` and analytics `owner_notification_sent`
   `channel=whatsapp`.
4. With env unset, confirm WhatsApp is **skipped** (logged) and email/SMS still work.

---

## 7. Rollback

- **Per tenant:** turn the WhatsApp toggle off in Settings (`whatsapp_enabled=false`).
- **Globally:** unset `TWILIO_WHATSAPP_FROM` / `TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID`
  → all WhatsApp sends skip immediately; email/SMS unaffected.
- No data migration to undo.
