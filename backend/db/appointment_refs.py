"""
Data-access for call-scoped appointment references (migration 017).

Same shape as db/locations.py's slot-offer helpers, and for the same reason: the
model names a short opaque ref, and every identifier the destructive operation
uses is read back from here rather than from anything the model said.

The lookup is deliberately over the FULL identity — call, ref, tenant AND caller
phone. A ref that belongs to another caller does not fail a check; it simply is
not found, which is a harder thing to get wrong.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.supabase import get_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def insert_refs(rows: list[dict]) -> None:
    if rows:
        get_client().table("call_appointment_refs").insert(rows).execute()


async def count_refs(vapi_call_id: str) -> int:
    res = (get_client().table("call_appointment_refs")
           .select("appointment_ref", count="exact").eq("vapi_call_id", vapi_call_id).execute())
    return res.count or 0


async def get_ref(vapi_call_id: str, appointment_ref: str, tenant_id: str,
                  caller_phone: str) -> dict | None:
    """Every scope in the predicate. Wrong call, wrong tenant or wrong caller all
    come back as simply 'not yours'."""
    res = (get_client().table("call_appointment_refs").select("*")
           .eq("vapi_call_id", vapi_call_id).eq("appointment_ref", appointment_ref)
           .eq("tenant_id", tenant_id).eq("caller_phone", caller_phone)
           .limit(1).execute())
    return (res.data or [None])[0]


async def consume_ref(vapi_call_id: str, appointment_ref: str) -> bool:
    """Claim the ref for a destructive act. True only if WE claimed it.

    `consumed_at IS NULL` is in the predicate, so two concurrent tool calls
    holding the same ref cannot both proceed to the provider — the loser sees
    False and stops. This is the destructive boundary.
    """
    res = (get_client().table("call_appointment_refs")
           .update({"consumed_at": _now_iso()})
           .eq("vapi_call_id", vapi_call_id).eq("appointment_ref", appointment_ref)
           .is_("consumed_at", "null").execute())
    return len(res.data or []) == 1


async def release_ref(vapi_call_id: str, appointment_ref: str) -> None:
    """Hand the ref back after a provider failure so the caller can try again."""
    (get_client().table("call_appointment_refs").update({"consumed_at": None})
     .eq("vapi_call_id", vapi_call_id).eq("appointment_ref", appointment_ref).execute())


async def delete_refs(vapi_call_id: str) -> None:
    get_client().table("call_appointment_refs").delete().eq("vapi_call_id", vapi_call_id).execute()


async def purge_expired_refs(now_iso: str) -> int:
    res = (get_client().table("call_appointment_refs").delete()
           .lt("expires_at", now_iso).execute())
    return len(res.data or [])
