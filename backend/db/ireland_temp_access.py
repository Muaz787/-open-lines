"""The durable lifecycle of one Irish onboarding's free temporary test access
(migration 036, W9I-H.AUTO.1).

Every function is a single fenced statement, and the fences ARE the state
machine. Nothing reads a row and then writes it: that pattern is how two workers
both conclude they are the buyer.

    STATE 0  no row                            -> claim()
    STATE 1  claimed, provider_attempt_at NULL  -> mark_attempt() may win
    STATE 2  attempt recorded, no number        -> UNKNOWN. No purchase, ever.
    STATE 3  number recorded                    -> reuse. Always.

State 2 has no statement here that returns it to state 1. The omission is the
invariant: an unknown provider outcome must never become "safe to buy again",
however much time passes.

THE ALLOWANCE LIVES HERE, NOT ON THE PHONE ROW. It has to survive the number
being replaced, adopted, suspended, retired or re-acquired -- otherwise cycling
a number resets the free minutes, which is the abuse this exists to stop.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.supabase import get_client

logger = logging.getLogger(__name__)

TABLE = "ireland_temporary_access"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get(tenant_id: str) -> dict | None:
    rows = (get_client().table(TABLE).select("*")
            .eq("tenant_id", tenant_id).limit(1).execute().data) or []
    return rows[0] if rows else None


async def claim(tenant_id: str) -> bool:
    """Create the lifecycle row. True only for the caller that created it.

    A loser gets False and reads the row instead. Crucially this is NOT a reset:
    a row that already exists keeps its spent allowance and every clock.
    """
    try:
        rows = (get_client().table(TABLE)
                .insert({"tenant_id": tenant_id}).execute().data) or []
        return bool(rows)
    except Exception as e:
        from db.supabase import _is_unique_violation
        if _is_unique_violation(e):
            return False
        logger.error("temporary access claim failed: %s", type(e).__name__)
        raise


async def mark_attempt(tenant_id: str) -> bool:
    """Record that a number purchase is ABOUT to be issued. One-way.

    THE IRREVERSIBLE BOUNDARY. Before this write nothing has been asked of
    Twilio. After it, Twilio may hold a number we have never seen, and no
    elapsed time makes another purchase safe.
    """
    rows = (get_client().table(TABLE)
            .update({"provider_attempt_at": _now(), "updated_at": _now()})
            .eq("tenant_id", tenant_id)
            .is_("provider_attempt_at", "null")
            .execute().data) or []
    return bool(rows)


async def attach_number(*, tenant_id: str, e164: str, provider_sid: str) -> bool:
    """Bind the number the provider positively confirmed. Fenced twice over.

    `provider_attempt_at is not null` is in the WHERE clause as well as in
    036's CHECK: the constraint makes the bad state unreachable, the predicate
    makes the intent legible here.
    """
    rows = (get_client().table(TABLE)
            .update({"e164": e164, "provider_sid": provider_sid,
                     "updated_at": _now()})
            .eq("tenant_id", tenant_id)
            .is_("e164", "null")
            .not_.is_("provider_attempt_at", "null")
            .execute().data) or []
    return bool(rows)


async def retake_unattempted(tenant_id: str) -> bool:
    """Take over a claim that PROVABLY never reached the provider.

    The only route back toward a purchase, gated on provider_attempt_at being
    NULL -- proof, not an inference from age. Deliberately not time-based:
    elapsed time cannot tell the two cases apart and this column can.
    """
    rows = (get_client().table(TABLE)
            .update({"updated_at": _now()})
            .eq("tenant_id", tenant_id)
            .is_("provider_attempt_at", "null")
            .is_("e164", "null")
            .execute().data) or []
    return bool(rows)


# ── the clocks: each start recorded ONCE, never restamped ─────────────────

async def _start_clock(tenant_id: str, column: str) -> bool:
    """Stamp a clock only if it is not already running.

    The fence is the whole point: a reconciliation pass that runs hourly must
    not push a 14-day window 14 days further every hour.
    """
    rows = (get_client().table(TABLE)
            .update({column: _now(), "updated_at": _now()})
            .eq("tenant_id", tenant_id)
            .is_(column, "null")
            .execute().data) or []
    return bool(rows)


async def start_access(tenant_id: str) -> bool:
    """The 30-day pending-review clock. Starts when testing genuinely begins."""
    return await _start_clock(tenant_id, "access_started_at")


async def start_action_required(tenant_id: str) -> bool:
    return await _start_clock(tenant_id, "action_required_at")


async def start_rejected(tenant_id: str) -> bool:
    return await _start_clock(tenant_id, "rejected_at")


async def start_cutover(tenant_id: str) -> bool:
    """The 24-hour transition window, stamped when the permanent line goes live."""
    return await _start_clock(tenant_id, "cutover_at")


async def clear_action_required(tenant_id: str) -> bool:
    """The customer corrected the filing and the provider is reviewing again.

    Clears ONLY the correction window. access_started_at is deliberately left
    alone: the 30-day free lifetime does not restart, or a customer could earn a
    fresh month by cycling through corrections.
    """
    rows = (get_client().table(TABLE)
            .update({"action_required_at": None, "updated_at": _now()})
            .eq("tenant_id", tenant_id)
            .not_.is_("action_required_at", "null")
            .execute().data) or []
    return bool(rows)


# ── the allowance ─────────────────────────────────────────────────────────

async def consume_seconds(*, tenant_id: str, seconds: int) -> dict | None:
    """Add call time to the lifetime allowance. Concurrency-safe.

    Uses a database-side increment via RPC so two calls ending at once cannot
    both read the same starting value and write the same total. Falls back to a
    read-modify-write ONLY if the function is absent, and says so loudly --
    losing test minutes is far better than losing them silently.
    """
    client = get_client()
    try:
        res = client.rpc("ita_consume_seconds",
                         {"p_tenant": tenant_id, "p_seconds": int(seconds)}).execute()
        data = res.data
        if isinstance(data, list):
            return data[0] if data else None
        return data
    except Exception as e:
        logger.error("ITA allowance increment via RPC failed (%s) -- falling back "
                     "to read-modify-write, which can UNDERCOUNT under "
                     "concurrency", type(e).__name__)
        row = await get(tenant_id)
        if not row:
            return None
        total = int(row.get("seconds_used") or 0) + max(0, int(seconds))
        rows = (client.table(TABLE)
                .update({"seconds_used": total, "updated_at": _now()})
                .eq("tenant_id", tenant_id).execute().data) or []
        return rows[0] if rows else None


# ── suspension, which is NOT release ──────────────────────────────────────

async def suspend(*, tenant_id: str, reason: str) -> bool:
    """Stop inbound testing. Leaves the number in place.

    Separate from retirement on purpose: the regulatory lifecycle may still need
    the line to exist, and releasing it is its own fenced step with its own
    triggers. Fenced so the FIRST reason recorded is the one kept -- an
    allowance exhausted before a deadline expired should read as exhausted.
    """
    rows = (get_client().table(TABLE)
            .update({"suspended_at": _now(), "suspend_reason": reason,
                     "updated_at": _now()})
            .eq("tenant_id", tenant_id)
            .is_("suspended_at", "null")
            .execute().data) or []
    return bool(rows)


# ── retirement ────────────────────────────────────────────────────────────

async def claim_retirement(tenant_id: str) -> bool:
    """Elect ONE worker to release the number. True only for that worker."""
    rows = (get_client().table(TABLE)
            .update({"retirement_claimed_at": _now(), "updated_at": _now()})
            .eq("tenant_id", tenant_id)
            .is_("retirement_claimed_at", "null")
            .execute().data) or []
    return bool(rows)


async def mark_released(tenant_id: str) -> bool:
    rows = (get_client().table(TABLE)
            .update({"released_at": _now(), "updated_at": _now()})
            .eq("tenant_id", tenant_id)
            .is_("released_at", "null")
            .not_.is_("retirement_claimed_at", "null")
            .execute().data) or []
    return bool(rows)
