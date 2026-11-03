"""
Data access for Google/Outlook move operations (migration 046).

Transitions are compare-and-swap on state and claim_token: a worker that lost
ownership cannot advance an operation another worker now owns.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.supabase import get_client, run_query

TABLE = "calendar_move_operations"
LIVE = ("in_progress", "unknown", "provider_moved")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_unique_violation(e: Exception) -> bool:
    s = str(e).lower()
    return "23505" in s or "duplicate" in s or "unique" in s


async def insert(row: dict) -> dict | None:
    """None when the appointment already has a live operation."""
    try:
        res = await run_query(get_client().table(TABLE).insert(
            {**row, "created_at": _now_iso(), "updated_at": _now_iso()}))
    except Exception as e:
        if is_unique_violation(e):
            return None
        raise
    return (res.data or [None])[0]


async def get(operation_id: str) -> dict | None:
    res = await run_query(get_client().table(TABLE).select("*").eq("id", operation_id).limit(1))
    return (res.data or [None])[0]


async def live_for_appointment(appointment_id: str) -> dict | None:
    res = await run_query(get_client().table(TABLE).select("*")
                          .eq("appointment_id", appointment_id).in_("state", list(LIVE)).limit(1))
    return (res.data or [None])[0]


async def completed_for_appointment(appointment_id: str) -> list[dict]:
    """Every finished move of an appointment: when it started (created_at), when it
    finished (updated_at) and the time it moved from. Refund eligibility reads these."""
    res = await run_query(get_client().table(TABLE).select("*")
                          .eq("appointment_id", appointment_id).eq("state", "completed"))
    return res.data or []


async def transition(op: dict, from_states: tuple, patch: dict) -> dict | None:
    """Apply patch if the row is still owned by op's claim and in from_states."""
    res = await run_query(get_client().table(TABLE).update({**patch, "updated_at": _now_iso()})
                          .eq("id", op["id"]).eq("claim_token", op["claim_token"])
                          .in_("state", list(from_states)))
    return (res.data or [None])[0]


async def list_stale(before_iso: str, limit: int = 20) -> list[dict]:
    res = await run_query(get_client().table(TABLE).select("*").in_("state", list(LIVE))
                          .lt("updated_at", before_iso).limit(limit))
    return res.data or []


async def lease(op: dict) -> dict | None:
    """Take an operation for recovery: succeeds for exactly one worker, because it
    only matches the updated_at that worker read. Serializes recovery passes."""
    res = await run_query(get_client().table(TABLE).update({"updated_at": _now_iso()})
                          .eq("id", op["id"]).eq("updated_at", op["updated_at"])
                          .in_("state", list(LIVE)))
    return (res.data or [None])[0]


async def finish(operation_id: str, claim_token: str) -> str:
    """calendar_move_finish (migration 046): write the appointment, complete the
    operation and release its claim in one transaction, only while it still owns
    the appointment. Returns completed, not_owner, missing or appointment_inactive."""
    res = await run_query(get_client().rpc("calendar_move_finish", {
        "p_operation_id": operation_id, "p_claim_token": claim_token}))
    return str(res.data or "")
