"""
Data-access for the caller -> provider-customer mapping (migration 019).

Every mutating helper here is a compare-and-swap. That is not stylistic: this
table IS the concurrency boundary for Square customer creation, because
PostgreSQL advisory locks are unreachable through PostgREST. An unconditional
update method would let a caller finalize a claim it does not own, which is the
one thing the table exists to prevent — so there deliberately isn't one.

Each mutator returns True only when it affected exactly one row. A False means
somebody else won; the caller must re-read rather than assume.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from db.supabase import get_client

logger = logging.getLogger(__name__)

PROVIDER_SQUARE = "square"

# How long a claim may sit unfinished before another worker may take it over.
# Long enough to cover a slow Square round trip, short enough that a crashed
# worker does not strand a caller through a whole conversation.
CLAIM_STALE_SECONDS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def stale_cutoff_iso() -> str:
    return (_now() - timedelta(seconds=CLAIM_STALE_SECONDS)).isoformat()


def is_unique_violation(e: Exception) -> bool:
    """PostgREST surfaces the SQLSTATE inside the message. Same detection the
    webhook-event enqueue has used since it was written."""
    s = str(e).lower()
    return "23505" in s or "duplicate" in s or "unique" in s


async def get_mapping(tenant_id: str, provider: str, normalized_phone: str) -> dict | None:
    res = (get_client().table("provider_customers").select("*")
           .eq("tenant_id", tenant_id).eq("provider", provider)
           .eq("normalized_phone", normalized_phone).limit(1).execute())
    return (res.data or [None])[0]


async def get_by_id(row_id: str) -> dict | None:
    res = (get_client().table("provider_customers").select("*")
           .eq("id", row_id).limit(1).execute())
    return (res.data or [None])[0]


async def try_create_claim(
    tenant_id: str, provider: str, normalized_phone: str, claim_token: str,
) -> dict | None:
    """Insert the claim row. Returns it when we won the election, None on 23505.

    The unique index on (tenant_id, provider, normalized_phone) is what elects a
    single winner. Losing here is normal and not an error.
    """
    try:
        res = get_client().table("provider_customers").insert({
            "tenant_id": tenant_id,
            "provider": provider,
            "normalized_phone": normalized_phone,
            "claim_token": claim_token,
            "claimed_at": _now_iso(),
        }).execute()
        return (res.data or [None])[0]
    except Exception as e:
        if is_unique_violation(e):
            return None
        raise


async def acquire_unowned_claim_cas(row_id: str, claim_token: str) -> bool:
    """Take an UNRESOLVED, UNOWNED row (claim_token IS NULL).

    A null token means nobody is working on it — most often because an owner hit
    provider ambiguity and released it. Such a row is available immediately; there
    is no reason to make the next worker wait out a staleness timeout.
    """
    res = (get_client().table("provider_customers")
           .update({"claim_token": claim_token, "claimed_at": _now_iso(),
                    "updated_at": _now_iso()})
           .eq("id", row_id).is_("provider_customer_id", "null")
           .is_("claim_token", "null").execute())
    return len(res.data or []) == 1


async def takeover_stale_claim_cas(
    row_id: str, prev_claim_token: str, prev_claimed_at: str, claim_token: str,
) -> bool:
    """Take over an abandoned claim.

    Both the previous token AND the previous timestamp are in the predicate, so a
    takeover cannot succeed against a row that moved after we read it. Without the
    timestamp, two workers reading the same stale row could both match on token.
    """
    res = (get_client().table("provider_customers")
           .update({"claim_token": claim_token, "claimed_at": _now_iso(),
                    "updated_at": _now_iso()})
           .eq("id", row_id).is_("provider_customer_id", "null")
           .eq("claim_token", prev_claim_token).eq("claimed_at", prev_claimed_at)
           .lt("claimed_at", stale_cutoff_iso()).execute())
    return len(res.data or []) == 1


async def finalize_mapping_cas(
    row_id: str, claim_token: str, provider_customer_id: str,
    provider_merchant_id: str | None = None,
) -> bool:
    """Write the resolved provider customer id — owner only.

    `provider_customer_id IS NULL` is in the predicate as well as the token, so a
    worker that lost its claim to a takeover can never overwrite the new owner's
    result with its own.
    """
    patch = {"provider_customer_id": provider_customer_id, "claim_token": None,
             "updated_at": _now_iso()}
    if provider_merchant_id:
        patch["provider_merchant_id"] = provider_merchant_id
    res = (get_client().table("provider_customers").update(patch)
           .eq("id", row_id).eq("claim_token", claim_token)
           .is_("provider_customer_id", "null").execute())
    return len(res.data or []) == 1


async def release_claim_cas(row_id: str, claim_token: str) -> bool:
    """Give up ownership without resolving, leaving the row acquirable at once.

    Used when Square returns several customers for one phone: we refuse to guess,
    and parking the row behind a staleness timeout would punish the next worker
    for our caution.
    """
    res = (get_client().table("provider_customers")
           .update({"claim_token": None, "updated_at": _now_iso()})
           .eq("id", row_id).eq("claim_token", claim_token)
           .is_("provider_customer_id", "null").execute())
    return len(res.data or []) == 1


async def delete_mapping(row_id: str) -> None:
    """Test/fixture cleanup only. No production path deletes a mapping."""
    get_client().table("provider_customers").delete().eq("id", row_id).execute()
