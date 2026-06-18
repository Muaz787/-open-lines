import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _client = create_client(url, key)
    return _client


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def create_auth_user(email: str, password: str, tenant_id: str) -> str:
    res = get_client().auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"tenant_id": tenant_id},
    })
    return res.user.id


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------

async def get_tenant_by_id(tenant_id: str) -> dict:
    res = get_client().table("tenants").select("*").eq("id", tenant_id).single().execute()
    return res.data


async def get_tenant_by_phone(phone_number: str) -> dict | None:
    # Primary: match on twilio_phone_number (E.164, e.g. +16475581427)
    res = (
        get_client()
        .table("tenants")
        .select("*")
        .eq("twilio_phone_number", phone_number)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    # Fallback: Vapi end-of-call-report payloads sometimes provide the Vapi phone number
    # UUID instead of the Twilio number — match on vapi_phone_number_id.
    res = (
        get_client()
        .table("tenants")
        .select("*")
        .eq("vapi_phone_number_id", phone_number)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def insert_tenant(data: dict) -> dict:
    res = get_client().table("tenants").insert(data).execute()
    return res.data[0] if res.data else {}


async def update_tenant(tenant_id: str, data: dict) -> dict:
    res = (
        get_client()
        .table("tenants")
        .update(data)
        .eq("id", tenant_id)
        .execute()
    )
    return res.data[0] if res.data else {}


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

async def insert_lead(tenant_id: str, data: dict) -> dict:
    res = (
        get_client()
        .table("leads")
        .insert({"tenant_id": tenant_id, **data})
        .execute()
    )
    return res.data[0] if res.data else {}


async def get_leads(tenant_id: str, limit: int = 50) -> list:
    res = (
        get_client()
        .table("leads")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


async def get_lead_by_phone(tenant_id: str, phone: str) -> dict | None:
    res = (
        get_client()
        .table("leads")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def update_lead(tenant_id: str, lead_id: str, data: dict) -> dict:
    # Stamp last-activity time so the dashboard can show when a lead was last
    # touched (e.g. by a new call), not just when it was created.
    data = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    res = (
        get_client()
        .table("leads")
        .update(data)
        .eq("id", lead_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return res.data[0] if res.data else {}


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------

async def insert_call(tenant_id: str, lead_id: str, data: dict) -> dict:
    res = (
        get_client()
        .table("calls")
        .insert({"tenant_id": tenant_id, "lead_id": lead_id, **data})
        .execute()
    )
    return res.data[0] if res.data else {}


async def get_calls(tenant_id: str, limit: int = 50) -> list:
    res = (
        get_client()
        .table("calls")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

async def insert_appointment(data: dict) -> dict:
    res = get_client().table("appointments").insert(data).execute()
    return res.data[0] if res.data else {}


async def get_appointments(tenant_id: str, limit: int = 50) -> list:
    now_iso = datetime.now(timezone.utc).isoformat()
    res = (
        get_client()
        .table("appointments")
        .select("*")
        .eq("tenant_id", tenant_id)
        .gte("appointment_datetime", now_iso)
        .order("appointment_datetime", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data


async def get_tenants_with_calendar() -> list:
    res = (
        get_client()
        .table("tenants")
        .select("id, vapi_assistant_id, google_refresh_token, appointment_duration_minutes, calendar_timezone")
        .not_.is_("google_refresh_token", "null")
        .not_.is_("vapi_assistant_id", "null")
        .execute()
    )
    return res.data or []


async def get_active_appointment_by_phone(tenant_id: str, phone: str) -> dict | None:
    """Return the most recent confirmed appointment for this caller (up to 24h in the past
    and any future date) so same-day reschedules are caught even after the slot has passed."""
    from datetime import timedelta
    window_start = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    res = (
        get_client()
        .table("appointments")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("caller_phone", phone)
        .eq("status", "confirmed")
        .gte("appointment_datetime", window_start)
        .order("appointment_datetime", desc=False)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def get_tenant_by_stripe_customer(customer_id: str) -> dict | None:
    res = (
        get_client()
        .table("tenants")
        .select("*")
        .eq("stripe_customer_id", customer_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def get_upcoming_appointment_by_phone(tenant_id: str, phone: str) -> dict | None:
    now_iso = datetime.now(timezone.utc).isoformat()
    res = (
        get_client()
        .table("appointments")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("caller_phone", phone)
        .gte("appointment_datetime", now_iso)
        .order("appointment_datetime", desc=False)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def update_appointment(appointment_id: str, data: dict) -> dict:
    res = (
        get_client()
        .table("appointments")
        .update(data)
        .eq("id", appointment_id)
        .execute()
    )
    return res.data[0] if res.data else {}


async def get_appointment_by_id(appointment_id: str) -> dict | None:
    res = (
        get_client()
        .table("appointments")
        .select("*")
        .eq("id", appointment_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def get_appointment_by_call_id(call_id: str) -> dict | None:
    res = (
        get_client()
        .table("appointments")
        .select("*")
        .eq("vapi_call_id", call_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ---------------------------------------------------------------------------
# KB Entries
# ---------------------------------------------------------------------------

async def insert_kb_entry(tenant_id: str, type_: str, label: str, preview: str | None = None) -> dict:
    res = get_client().table("kb_entries").insert({
        "tenant_id": tenant_id,
        "type": type_,
        "label": label,
        **({"preview": preview} if preview else {}),
    }).execute()
    return res.data[0] if res.data else {}


async def get_kb_entries(tenant_id: str) -> list:
    res = (
        get_client()
        .table("kb_entries")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("added_at", desc=True)
        .execute()
    )
    return res.data or []


async def delete_kb_entry(tenant_id: str, entry_id: str) -> None:
    get_client().table("kb_entries").delete().eq("id", entry_id).eq("tenant_id", tenant_id).execute()


# ---------------------------------------------------------------------------
# Calls (with lead join)
# ---------------------------------------------------------------------------

async def get_calls_with_leads(tenant_id: str, days: int = 30, limit: int = 100) -> list:
    """Return calls with basic lead metadata joined. Excludes transcript for list performance."""
    query = (
        get_client()
        .table("calls")
        .select("id, vapi_call_id, duration_secs, created_at, lead_id, leads(name, phone, urgency, summary, metadata)")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if days > 0:
        from datetime import timedelta
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        query = query.gte("created_at", since)
    res = query.execute()
    return res.data or []


async def get_call_detail(tenant_id: str, call_id: str) -> dict | None:
    """Return a single call with full transcript and lead data."""
    res = (
        get_client()
        .table("calls")
        .select("*, leads(name, phone, urgency, summary, metadata)")
        .eq("tenant_id", tenant_id)
        .eq("id", call_id)
        .single()
        .execute()
    )
    return res.data


# ---------------------------------------------------------------------------
# Webhook event queue
# ---------------------------------------------------------------------------

async def enqueue_webhook_event(event_type: str, call_id: str | None, payload: dict) -> bool:
    """Insert a webhook event. Returns False if already enqueued (idempotent)."""
    try:
        get_client().table("webhook_events").insert({
            "event_type": event_type,
            "call_id": call_id,
            "payload": payload,
        }).execute()
        return True
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower() or "23505" in str(e):
            return False
        raise


async def claim_pending_webhook_events(limit: int = 10) -> list:
    """Return pending events that are ready to process (past their retry delay).

    Uses two separate queries instead of .or_() to avoid PostgREST's filter
    parser mishandling the '+' in UTC timezone offsets (e.g. +00:00), which
    caused .or_() to return zero rows and silently starve the processor.
    """
    # Use Z suffix (no '+' sign) so PostgREST's filter parser handles it cleanly
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    # Fresh events — never been retried (next_retry_at IS NULL)
    res1 = (
        get_client()
        .table("webhook_events")
        .select("*")
        .eq("status", "pending")
        .is_("next_retry_at", "null")
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )

    # Retry-eligible events — retry delay has elapsed.
    # No NOT NULL filter needed: SQL NULL semantics mean lte() already excludes NULL rows.
    res2 = (
        get_client()
        .table("webhook_events")
        .select("*")
        .eq("status", "pending")
        .lte("next_retry_at", now_iso)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )

    combined = (res1.data or []) + (res2.data or [])
    combined.sort(key=lambda e: e.get("created_at", ""))
    return combined[:limit]


async def mark_webhook_done(event_id: str) -> None:
    get_client().table("webhook_events").update({
        "status": "done",
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", event_id).execute()


async def mark_webhook_retry(event_id: str, attempts: int, error: str, retry_at: str) -> None:
    get_client().table("webhook_events").update({
        "attempts": attempts,
        "last_error": error[:500],
        "next_retry_at": retry_at,
    }).eq("id", event_id).execute()


async def mark_webhook_failed(event_id: str, attempts: int, error: str) -> None:
    get_client().table("webhook_events").update({
        "status": "failed",
        "attempts": attempts,
        "last_error": error[:500],
    }).eq("id", event_id).execute()


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

async def insert_payment(data: dict) -> dict:
    res = get_client().table("payments").insert(data).execute()
    return res.data[0] if res.data else {}


async def update_payment(payment_id: str, data: dict) -> dict:
    res = (
        get_client().table("payments").update(data).eq("id", payment_id).execute()
    )
    return res.data[0] if res.data else {}


async def get_payment_by_checkout_session(session_id: str) -> dict | None:
    res = (
        get_client().table("payments").select("*")
        .eq("checkout_session_id", session_id).limit(1).execute()
    )
    return res.data[0] if res.data else None


async def get_payment_by_payment_intent(payment_intent_id: str) -> dict | None:
    res = (
        get_client().table("payments").select("*")
        .eq("payment_intent_id", payment_intent_id).limit(1).execute()
    )
    return res.data[0] if res.data else None


async def get_payments_by_tenant(tenant_id: str, limit: int = 50) -> list:
    res = (
        get_client().table("payments").select("*")
        .eq("tenant_id", tenant_id).order("created_at", desc=True).limit(limit).execute()
    )
    return res.data or []


# ---------------------------------------------------------------------------
# Payment short links
# ---------------------------------------------------------------------------

async def create_payment_short_link(data: dict) -> dict:
    res = get_client().table("payment_short_links").insert(data).execute()
    return res.data[0] if res.data else {}


async def get_payment_short_link_by_code(short_code: str) -> dict | None:
    res = (
        get_client().table("payment_short_links")
        .select("*")
        .eq("short_code", short_code)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def increment_short_link_click(link_id: str) -> None:
    from datetime import datetime, timezone
    client = get_client()
    row = (
        client.table("payment_short_links")
        .select("click_count, clicked_at")
        .eq("id", link_id).limit(1).execute()
    )
    if not row.data:
        return
    current = row.data[0]
    update: dict = {"click_count": (current.get("click_count") or 0) + 1}
    if not current.get("clicked_at"):
        update["clicked_at"] = datetime.now(timezone.utc).isoformat()
    client.table("payment_short_links").update(update).eq("id", link_id).execute()


async def get_latest_appointment_by_phone(tenant_id: str, phone: str) -> dict | None:
    """Most recent appointment (any status) for this caller."""
    res = (
        get_client().table("appointments").select("*")
        .eq("tenant_id", tenant_id).eq("caller_phone", phone)
        .order("created_at", desc=True).limit(1).execute()
    )
    return res.data[0] if res.data else None


async def get_stripe_webhook_event(stripe_event_id: str) -> dict | None:
    res = (
        get_client().table("stripe_webhook_events").select("id, processed")
        .eq("stripe_event_id", stripe_event_id).limit(1).execute()
    )
    return res.data[0] if res.data else None


async def insert_stripe_webhook_event(
    stripe_event_id: str, event_type: str, tenant_id: str | None, payload: dict
) -> None:
    get_client().table("stripe_webhook_events").insert({
        "stripe_event_id": stripe_event_id,
        "event_type": event_type,
        "tenant_id": tenant_id,
        "payload": payload,
    }).execute()


async def mark_stripe_webhook_processed(stripe_event_id: str) -> None:
    get_client().table("stripe_webhook_events").update({"processed": True}).eq(
        "stripe_event_id", stripe_event_id
    ).execute()


# ---------------------------------------------------------------------------
# KB
# ---------------------------------------------------------------------------

async def upsert_kb_website_entry(tenant_id: str, label: str) -> dict:
    get_client().table("kb_entries").delete().eq("tenant_id", tenant_id).eq("type", "website").execute()
    res = get_client().table("kb_entries").insert({
        "tenant_id": tenant_id, "type": "website", "label": label,
    }).execute()
    return res.data[0] if res.data else {}
