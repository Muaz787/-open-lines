"""
Data-access helpers for AI Overflow Handling & AI Call Routing (migration 008).

Thin wrappers over the Supabase service-role client, matching the style in
db/supabase.py. Every write is tenant-scoped at the query level (defence in depth
on top of the owner-auth check in the API layer). These helpers do NOT enforce
entitlements or the dark-launch flag — callers (routers / tools) do that via
services/entitlements before invoking these.
"""
from __future__ import annotations

from db.supabase import get_client


# ---------------------------------------------------------------------------
# Per-tenant activation flag (dark-launch; master switch is ROUTING_ENABLED env)
# ---------------------------------------------------------------------------
async def set_routing_enabled(tenant_id: str, enabled: bool) -> dict:
    res = (get_client().table("tenants").update({"routing_enabled": bool(enabled)})
           .eq("id", tenant_id).execute())
    return (res.data or [{}])[0]


# ---------------------------------------------------------------------------
# call_handling_profiles
# ---------------------------------------------------------------------------
async def get_profile(tenant_id: str, phone_number: str | None = None) -> dict | None:
    q = get_client().table("call_handling_profiles").select("*").eq("tenant_id", tenant_id)
    if phone_number is not None:
        q = q.eq("phone_number", phone_number)
    res = q.limit(1).execute()
    return (res.data or [None])[0]


async def create_profile(tenant_id: str, data: dict) -> dict:
    res = get_client().table("call_handling_profiles").insert({**data, "tenant_id": tenant_id}).execute()
    return res.data[0]


async def update_profile(tenant_id: str, profile_id: str, data: dict) -> dict:
    res = (get_client().table("call_handling_profiles").update(data)
           .eq("tenant_id", tenant_id).eq("id", profile_id).execute())
    return (res.data or [{}])[0]


# ---------------------------------------------------------------------------
# routing_destinations (numbers stored encrypted — see services/routing_destinations)
# ---------------------------------------------------------------------------
async def list_destinations(tenant_id: str) -> list:
    res = (get_client().table("routing_destinations").select("*")
           .eq("tenant_id", tenant_id).order("created_at").execute())
    return res.data or []


async def get_destination(tenant_id: str, destination_id: str) -> dict | None:
    res = (get_client().table("routing_destinations").select("*")
           .eq("tenant_id", tenant_id).eq("id", destination_id).limit(1).execute())
    return (res.data or [None])[0]


async def create_destination(tenant_id: str, data: dict) -> dict:
    res = get_client().table("routing_destinations").insert({**data, "tenant_id": tenant_id}).execute()
    return res.data[0]


async def update_destination(tenant_id: str, destination_id: str, data: dict) -> dict:
    res = (get_client().table("routing_destinations").update(data)
           .eq("tenant_id", tenant_id).eq("id", destination_id).execute())
    return (res.data or [{}])[0]


async def find_destination_by_hash(tenant_id: str, e164_hash: str) -> dict | None:
    """Loop/dedup lookup by keyed hash (no decryption)."""
    if not e164_hash:
        return None
    res = (get_client().table("routing_destinations").select("*")
           .eq("tenant_id", tenant_id).eq("e164_hash", e164_hash).limit(1).execute())
    return (res.data or [None])[0]


# ---------------------------------------------------------------------------
# routing_rules
# ---------------------------------------------------------------------------
async def list_rules(tenant_id: str, profile_id: str) -> list:
    res = (get_client().table("routing_rules").select("*")
           .eq("tenant_id", tenant_id).eq("profile_id", profile_id)
           .order("priority").execute())
    return res.data or []


async def count_rules(tenant_id: str, profile_id: str) -> int:
    res = (get_client().table("routing_rules").select("id")
           .eq("tenant_id", tenant_id).eq("profile_id", profile_id).execute())
    return len(res.data or [])


async def create_rule(tenant_id: str, data: dict) -> dict:
    res = get_client().table("routing_rules").insert({**data, "tenant_id": tenant_id}).execute()
    return res.data[0]


async def update_rule(tenant_id: str, rule_id: str, data: dict) -> dict:
    res = (get_client().table("routing_rules").update(data)
           .eq("tenant_id", tenant_id).eq("id", rule_id).execute())
    return (res.data or [{}])[0]


async def delete_rule(tenant_id: str, rule_id: str) -> None:
    (get_client().table("routing_rules").delete()
     .eq("tenant_id", tenant_id).eq("id", rule_id).execute())


# ---------------------------------------------------------------------------
# transfer_attempts — idempotent on (vapi_call_id, attempt_index)
# ---------------------------------------------------------------------------
async def record_transfer_attempt(data: dict) -> dict:
    """Insert or update a transfer attempt. Idempotent: a duplicated / re-ordered
    provider event for the same (vapi_call_id, attempt_index) updates the existing
    row instead of creating a second one."""
    client = get_client()
    vci = data.get("vapi_call_id")
    idx = int(data.get("attempt_index", 0))
    if vci:
        existing = (client.table("transfer_attempts").select("id")
                    .eq("vapi_call_id", vci).eq("attempt_index", idx).limit(1).execute())
        if existing.data:
            upd = (client.table("transfer_attempts").update(data)
                   .eq("id", existing.data[0]["id"]).execute())
            return (upd.data or [{}])[0]
    ins = client.table("transfer_attempts").insert(data).execute()
    return ins.data[0]


async def list_transfer_attempts(tenant_id: str, call_id: str | None = None) -> list:
    q = (get_client().table("transfer_attempts").select("*")
         .eq("tenant_id", tenant_id))
    if call_id is not None:
        q = q.eq("call_id", call_id)
    res = q.order("created_at").execute()
    return res.data or []


# ---------------------------------------------------------------------------
# routing_decisions (immutable audit)
# ---------------------------------------------------------------------------
async def insert_routing_decision(data: dict) -> dict:
    res = get_client().table("routing_decisions").insert(data).execute()
    return res.data[0]


async def get_latest_transfer_decision(tenant_id: str, vapi_call_id: str) -> dict | None:
    """Most recent 'transfer' decision recorded for this call (by classify-and-route).
    The transfer webhook resolves the destination from this, so the AI never carries
    a number."""
    if not vapi_call_id:
        return None
    res = (get_client().table("routing_decisions").select("*")
           .eq("tenant_id", tenant_id).eq("vapi_call_id", vapi_call_id).eq("decision", "transfer")
           .order("created_at", desc=True).limit(1).execute())
    return (res.data or [None])[0]


async def get_transfer_attempt(vapi_call_id: str, attempt_index: int = 0) -> dict | None:
    if not vapi_call_id:
        return None
    res = (get_client().table("transfer_attempts").select("*")
           .eq("vapi_call_id", vapi_call_id).eq("attempt_index", attempt_index).limit(1).execute())
    return (res.data or [None])[0]


# ---------------------------------------------------------------------------
# callback_requests
# ---------------------------------------------------------------------------
async def create_callback(tenant_id: str, data: dict) -> dict:
    res = get_client().table("callback_requests").insert({**data, "tenant_id": tenant_id}).execute()
    return res.data[0]


async def list_callbacks(tenant_id: str, status: str = "open") -> list:
    q = get_client().table("callback_requests").select("*").eq("tenant_id", tenant_id)
    if status:
        q = q.eq("status", status)
    res = q.order("created_at", desc=True).execute()
    return res.data or []


async def update_callback(tenant_id: str, callback_id: str, data: dict) -> dict:
    res = (get_client().table("callback_requests").update(data)
           .eq("tenant_id", tenant_id).eq("id", callback_id).execute())
    return (res.data or [{}])[0]
