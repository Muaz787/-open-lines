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
    """Return pending events that are ready to process (past their retry delay)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    res = (
        get_client()
        .table("webhook_events")
        .select("*")
        .eq("status", "pending")
        .or_(f"next_retry_at.is.null,next_retry_at.lte.{now_iso}")
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data or []


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


async def upsert_kb_website_entry(tenant_id: str, label: str) -> dict:
    get_client().table("kb_entries").delete().eq("tenant_id", tenant_id).eq("type", "website").execute()
    res = get_client().table("kb_entries").insert({
        "tenant_id": tenant_id, "type": "website", "label": label,
    }).execute()
    return res.data[0] if res.data else {}
