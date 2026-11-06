"""
Data access for the #179 production validation run (migration 047).

One row per one-time code, inserted by an operator to ARM it (only the code's
sha256). Using it sets vapi_call_id in a compare-and-swap, so it is single-use
across calls, retries and workers. The row then names the one
appointment the test may act on, and link_claimed_at lets exactly one request
create the one payment link. Every write is a compare-and-swap.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.supabase import get_client, run_query

TABLE = "inplace_test_runs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get(code_sha256: str) -> dict | None:
    res = await run_query(get_client().table(TABLE).select("*").eq("code_sha256", code_sha256).limit(1))
    return (res.data or [None])[0]


async def use_code(code_sha256: str, tenant_id: str, vapi_call_id: str) -> dict | None:
    """Use an ARMED code for this call. Returns the run, or None when no such code
    was armed for this tenant, it was used by a different call, or it is disabled.
    The same call asking again gets its own run back, so a retry behaves the same.
    Nothing is ever inserted here: a code works only if an operator armed it."""
    res = await run_query(get_client().table(TABLE).update({"vapi_call_id": vapi_call_id, "used_at": _now_iso()})
                          .eq("code_sha256", code_sha256).eq("tenant_id", tenant_id)
                          .is_("vapi_call_id", "null").is_("disabled_at", "null"))
    row = (res.data or [None])[0] or await get(code_sha256)
    if (not row or str(row.get("tenant_id")) != str(tenant_id)
            or str(row.get("vapi_call_id")) != str(vapi_call_id) or row.get("disabled_at")):
        return None
    return row


async def disable_unused(tenant_id: str) -> int:
    """Disable this tenant's armed codes that no call has used."""
    res = await run_query(get_client().table(TABLE).update({"disabled_at": _now_iso()})
                          .eq("tenant_id", tenant_id).is_("vapi_call_id", "null").is_("disabled_at", "null"))
    return len(res.data or [])


async def bind_appointment(code_sha256: str, appointment_id: str) -> bool:
    """Name the run's one appointment. Only if none is named yet."""
    res = await run_query(get_client().table(TABLE).update({"appointment_id": appointment_id})
                          .eq("code_sha256", code_sha256).is_("appointment_id", "null")
                          .is_("disabled_at", "null"))
    return len(res.data or []) == 1


async def claim_link(code_sha256: str, appointment_id: str) -> bool:
    """Exactly one request may create the payment link."""
    res = await run_query(get_client().table(TABLE).update({"link_claimed_at": _now_iso()})
                          .eq("code_sha256", code_sha256).eq("appointment_id", appointment_id)
                          .is_("link_claimed_at", "null").is_("disabled_at", "null"))
    return len(res.data or []) == 1


async def record_payment(code_sha256: str, payment_id: str) -> None:
    await run_query(get_client().table(TABLE).update({"payment_id": payment_id})
                    .eq("code_sha256", code_sha256).is_("payment_id", "null"))


async def for_appointment(appointment_id: str) -> dict | None:
    res = await run_query(get_client().table(TABLE).select("*")
                          .eq("appointment_id", appointment_id).limit(1))
    return (res.data or [None])[0]
