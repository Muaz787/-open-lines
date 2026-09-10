"""
W6B — OpenLines owns the caller -> Square customer mapping.

THE PROBLEM
find_or_create_customer searched Square by phone and created when the search came
back empty. Square's customer SEARCH index is eventually consistent (GET by id is
not), so two resolutions seconds apart both miss and both create. A W5.2 probe
produced two customers for one caller doing exactly this.

WHY A LOCK ISN'T AVAILABLE
This repository reaches Postgres only through PostgREST, so there is no session in
which to hold an advisory lock. Uniqueness therefore IS the lock: one row per
(tenant, provider, phone), and whoever inserts it owns the right to talk to Square.

WHY A CLAIM TOKEN
An unfinished row says the mapping is incomplete. It does not say who is entitled
to complete it. The token makes ownership provable, so a worker that lost its
claim to a takeover cannot overwrite the new owner's result.

WHY THE ROW ID IS THE IDEMPOTENCY KEY
provider_customers.id exists before the Square call and is untouched by takeover,
retry or crash. claim_token changes hands, so it is exactly the wrong thing to
derive a provider identity from. Square honours the key (measured, not assumed:
two CreateCustomer calls with one key return one customer), which is what lets a
worker that crashed mid-create be recovered by replay rather than by waiting for
the search index to catch up.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid

from db import provider_customers as db_pc

logger = logging.getLogger(__name__)

# Outcome codes. Stable strings so the tool layer and the tests agree.
OK = "ok"
AMBIGUOUS = "ambiguous"          # several provider customers share this phone
UNAVAILABLE = "unavailable"      # someone else holds the claim and hasn't finished
FAILED = "failed"                # provider or database refused; nothing created

# How long a loser waits for the winner to finish. A caller is on the phone, so
# this is deliberately small: the wait is a courtesy, not the concurrency control.
LOSER_WAIT_ATTEMPTS = 4
LOSER_WAIT_SECONDS = 0.35

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def normalize_e164(phone: str | None) -> str:
    """Trusted E.164 only. Returns '' if we cannot be certain what number this is.

    Deliberately NOT telephony.normalize_phone(), which maps a 10-digit string to
    +1. That guess is silently wrong for +353 87 123 4567 written without its
    prefix, and this value is a durable identity key — a wrong country code here
    binds an Irish caller to a North American customer record forever.

    Formatting is stripped only when the caller already told us the country by
    including a '+'. Without one we refuse rather than infer.
    """
    if not phone:
        return ""
    s = str(phone).strip()
    if not s.startswith("+"):
        return ""
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    candidate = "+" + digits
    return candidate if _E164.match(candidate) else ""


async def resolve_customer_id(
    *, tenant_id: str, token: str, phone: str, given_name: str = "",
    provider: str = db_pc.PROVIDER_SQUARE, square=None,
) -> tuple[str, str | None]:
    """Return (status, provider_customer_id).

    `square` is the provider module, injected so tests can drive it without
    patching import machinery; it defaults to services.square_booking.
    """
    if square is None:
        from services import square_booking as square

    normalized = normalize_e164(phone)
    if not normalized:
        logger.warning("customer_identity: refusing a non-E.164 phone for tenant %s", tenant_id)
        return FAILED, None

    for _ in range(LOSER_WAIT_ATTEMPTS + 1):
        try:
            row = await db_pc.get_mapping(tenant_id, provider, normalized)
        except Exception as e:
            logger.error("customer_identity: mapping read failed for %s: %s", tenant_id, e)
            return FAILED, None

        # STATE 1 — resolved. The steady state, and the whole point: no provider
        # call of any kind, not even a search.
        if row and row.get("provider_customer_id"):
            return OK, row["provider_customer_id"]

        mine = str(uuid.uuid4())

        # STATE 2 — no row at all. The insert is the election.
        if not row:
            try:
                claimed = await db_pc.try_create_claim(tenant_id, provider, normalized, mine)
            except Exception as e:
                logger.error("customer_identity: claim insert failed for %s: %s", tenant_id, e)
                return FAILED, None
            if claimed:
                return await _reconcile(claimed, mine, token, normalized, given_name, square)
            continue                                    # lost the race — re-read

        # STATE 3 — unresolved and unowned. Available immediately.
        if not row.get("claim_token"):
            if await db_pc.acquire_unowned_claim_cas(row["id"], mine):
                fresh = await db_pc.get_by_id(row["id"]) or row
                return await _reconcile(fresh, mine, token, normalized, given_name, square)
            continue

        # STATE 5 — unresolved, owned, but abandoned.
        if str(row.get("claimed_at") or "") < db_pc.stale_cutoff_iso():
            if await db_pc.takeover_stale_claim_cas(
                    row["id"], row["claim_token"], row["claimed_at"], mine):
                logger.warning("customer_identity: took over a stale claim on %s", row["id"])
                fresh = await db_pc.get_by_id(row["id"]) or row
                return await _reconcile(fresh, mine, token, normalized, given_name, square)
            continue

        # STATE 4 — someone else is actively working. Never call Square here.
        await asyncio.sleep(LOSER_WAIT_SECONDS)

    logger.warning("customer_identity: claim still unresolved for tenant %s after waiting", tenant_id)
    return UNAVAILABLE, None


async def _reconcile(row, mine, token, normalized, given_name, square):
    """Owner-only. Search for an existing customer, else create exactly one.

    The search here is RECOVERY — it adopts customers that predate this table, and
    finds one an earlier crashed worker created. It is never the concurrency
    control; that was settled before we got here.
    """
    row_id = row["id"]

    try:
        matches = await square.search_customers_by_phone(token, normalized)
    except Exception as e:
        # Uncertainty about what exists must never become another customer.
        logger.error("customer_identity: provider search failed for %s: %s", row_id, e)
        await db_pc.release_claim_cas(row_id, mine)
        return FAILED, None

    if len(matches) > 1:
        # Refusing to guess. Picking the oldest would be deterministic without
        # being correct, and binding the wrong one is not something a later pass
        # can detect.
        logger.error(
            "customer_identity: AMBIGUOUS — %d Square customers share phone for tenant %s "
            "(mapping %s left unbound: %s)",
            len(matches), row.get("tenant_id"), row_id, [m.get("id") for m in matches])
        await db_pc.release_claim_cas(row_id, mine)
        return AMBIGUOUS, None

    if len(matches) == 1:
        customer_id = matches[0].get("id")
    else:
        try:
            customer_id = await square.create_customer(
                token, phone=normalized, given_name=given_name,
                idempotency_key=str(row_id))       # bare UUID, stable across takeover
        except Exception as e:
            # Ambiguous outcome: the request may have been committed. Keep the
            # claim and the key exactly as they are — a retry replays the same
            # logical request and Square converges on whatever it already made.
            logger.error("customer_identity: CreateCustomer unresolved for %s: %s", row_id, e)
            return FAILED, None

    if not customer_id:
        # Definitive provider rejection: nothing exists to be idempotent about.
        await db_pc.release_claim_cas(row_id, mine)
        return FAILED, None

    if await db_pc.finalize_mapping_cas(row_id, mine, customer_id):
        return OK, customer_id

    # Lost the claim mid-flight. Whatever is mapped now is authoritative; never
    # overwrite a conflicting id with ours.
    latest = await db_pc.get_by_id(row_id)
    if latest and latest.get("provider_customer_id"):
        logger.warning("customer_identity: finalize lost the race on %s; using %s",
                       row_id, latest["provider_customer_id"])
        return OK, latest["provider_customer_id"]
    return FAILED, None
