"""The durable binding between one signup attempt and one Stripe Customer
(migrations 034 + 035, W9I-H.0.2).

Every function here is a single fenced statement, and the fences ARE the state
machine. Nothing decides by reading a row and then writing it -- that pattern is
how two workers both conclude they are the creator.

    STATE 0  no row                              -> claim()
    STATE 1  claimed, provider_attempt_at NULL    -> mark_attempt() may win
    STATE 2  attempt set, customer NULL           -> UNKNOWN. No create, ever.
    STATE 3  customer set                         -> reuse. Always.

State 2 has no statement here that returns it to state 1, and that omission is
deliberate rather than incidental: an unknown provider outcome must never become
"safe to create again", however much time passes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.supabase import get_client

logger = logging.getLogger(__name__)

TABLE = "onboarding_payment_sessions"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get(onboarding_key: str) -> dict | None:
    rows = (get_client().table(TABLE).select("*")
            .eq("onboarding_key", onboarding_key).limit(1).execute().data) or []
    return rows[0] if rows else None


async def claim(*, onboarding_key: str, iso_country: str) -> bool:
    """Create the session row. True only for the caller that created it.

    The primary key elects one winner among concurrent callers; a loser gets
    False and reads the row instead. Nothing here touches the provider.
    """
    try:
        rows = (get_client().table(TABLE).insert({
            "onboarding_key": onboarding_key,
            "iso_country": iso_country,
        }).execute().data) or []
        return bool(rows)
    except Exception as e:
        # A duplicate key is the normal, expected loss. Anything else is not,
        # and is reported as a failure to claim rather than swallowed.
        from db.supabase import _is_unique_violation
        if _is_unique_violation(e):
            return False
        logger.error("payment session claim failed: %s", type(e).__name__)
        raise


async def mark_attempt(onboarding_key: str) -> bool:
    """Record that a provider create is ABOUT to be issued. One-way.

    THE IRREVERSIBLE BOUNDARY. Before this write, nothing has been asked of
    Stripe and a stale claim may be retaken. After it, Stripe may hold a Customer
    we have never seen, and no amount of elapsed time makes another create safe.

    True only for the caller that set it, so exactly one worker proceeds to the
    provider.
    """
    rows = (get_client().table(TABLE)
            .update({"provider_attempt_at": _now(), "updated_at": _now()})
            .eq("onboarding_key", onboarding_key)
            .is_("provider_attempt_at", "null")
            .execute().data) or []
    return bool(rows)


async def attach_customer(*, onboarding_key: str, customer_id: str) -> bool:
    """Bind the Customer the provider returned. Fenced twice over.

    `provider_attempt_at is not null` is in the WHERE clause as well as in
    migration 035's CHECK: the constraint makes the bad state unreachable, and
    the predicate makes the intent legible at the call site.
    """
    rows = (get_client().table(TABLE)
            .update({"stripe_customer_id": customer_id, "updated_at": _now()})
            .eq("onboarding_key", onboarding_key)
            .is_("stripe_customer_id", "null")
            .not_.is_("provider_attempt_at", "null")
            .execute().data) or []
    return bool(rows)


async def retake_unattempted(*, onboarding_key: str) -> bool:
    """Take over a claim that PROVABLY never reached the provider.

    The only route back toward a provider call, and it is gated on
    provider_attempt_at being NULL -- which is proof, not an inference from age.
    A worker that died before marking its attempt leaves a session that any later
    worker may continue; one that died after does not.

    Deliberately NOT time-based. There is no lease here, because elapsed time
    cannot distinguish the two cases and this column can.
    """
    rows = (get_client().table(TABLE)
            .update({"updated_at": _now()})
            .eq("onboarding_key", onboarding_key)
            .is_("provider_attempt_at", "null")
            .is_("stripe_customer_id", "null")
            .execute().data) or []
    return bool(rows)
