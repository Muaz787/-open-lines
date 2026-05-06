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
# Tenants
# ---------------------------------------------------------------------------

async def get_tenant_by_id(tenant_id: str) -> dict:
    res = get_client().table("tenants").select("*").eq("id", tenant_id).single().execute()
    return res.data


async def get_tenant_by_phone(phone_number: str) -> dict:
    res = (
        get_client()
        .table("tenants")
        .select("*")
        .eq("twilio_phone_number", phone_number)
        .single()
        .execute()
    )
    return res.data


async def insert_tenant(data: dict) -> dict:
    res = get_client().table("tenants").insert(data).execute()
    return res.data[0]


async def update_tenant(tenant_id: str, data: dict) -> dict:
    res = (
        get_client()
        .table("tenants")
        .update(data)
        .eq("id", tenant_id)
        .execute()
    )
    return res.data[0]


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
    return res.data[0]


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
    return res.data[0]


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
    return res.data[0]


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
    return res.data[0]


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
