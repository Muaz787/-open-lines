"""
Data access for per-call booking claims (migration 045).

Every change is a compare-and-swap on the row's state and updated_at, so a worker
that lost the slot to another, or woke up after a recovery took over, cannot
disturb the new owner's row.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.supabase import get_client, run_query

TABLE = "call_booking_claims"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_unique_violation(e: Exception) -> bool:
    s = str(e).lower()
    return "23505" in s or "duplicate" in s or "unique" in s


def _key(q, tenant_id: str, call_id: str, slot_start: str):
    return q.eq("tenant_id", tenant_id).eq("vapi_call_id", call_id).eq("slot_start", slot_start)


async def insert_pending(row: dict) -> bool:
    """False when the slot is taken, or the call already has a booking in progress."""
    try:
        await run_query(get_client().table(TABLE).insert(
            {**row, "state": "pending", "created_at": now_iso(), "updated_at": now_iso()}))
        return True
    except Exception as e:
        if is_unique_violation(e):
            return False
        raise


async def get(tenant_id: str, call_id: str, slot_start: str) -> dict | None:
    res = await run_query(_key(get_client().table(TABLE).select("*"),
                               tenant_id, call_id, slot_start).limit(1))
    return (res.data or [None])[0]


async def transition(claim: dict, patch: dict) -> dict | None:
    """Apply patch only if the row is still exactly as the caller last read it.

    Returns the updated row, or None when it had changed — someone else owns it.
    A unique violation (another booking went pending in this call first) is None too.
    """
    new = {**patch, "updated_at": now_iso()}
    try:
        res = await run_query(_key(get_client().table(TABLE).update(new),
                                   claim["tenant_id"], claim["vapi_call_id"], claim["slot_start"])
                              .eq("state", claim["state"]).eq("updated_at", claim["updated_at"]))
    except Exception as e:
        if is_unique_violation(e):
            return None
        raise
    return (res.data or [None])[0]
