"""THE ONE PLACE a provisioned number is recorded (W9I-B).

WHY THIS MODULE EXISTS
W9I-A found that signup wrote the number ONLY to the legacy
`tenants.twilio_phone_number` scalar. `tenant_phone_numbers` -- the canonical
model migration 027 built, that routing prefers, and that the whole two-number
Irish migration depends on -- was populated exclusively by the W9F backfill. So
every signup since W9D has quietly added a tenant the canonical model does not
know about. Production happens to be clean (11 tenants, 7 numbers, an exact 1:1
match) only because no signup has happened since that backfill ran.

Two writers with different semantics is how that drift happened, so there is now
one:

    register_permanent()   the number exists at the provider -> record it
    mark_active()          the number is configured and answers -> make it routable
    mark_released()        the provider confirmed it is gone -> close the row

mark_released() was added in W9I-B.1, because shipping the first two without it
left the model able to acquire numbers but never to let one go. release_tenant_number
cleared the legacy scalar and left the canonical row 'active', so a released
number stayed the tenant's live permanent for ever: unroutable in fact, still
counted by tpn_one_current_permanent, and therefore blocking the replacement the
customer was waiting for -- after the replacement had been bought and paid for.
Acquisition and release now go through the same module for the same reason they
have to: two writers with different semantics is how the drift happened.

BOTH THE CANONICAL ROW AND THE LEGACY SCALAR ARE WRITTEN HERE, TOGETHER. The
scalar is not deprecated yet -- `get_tenant_by_phone` still falls back to it and
several call sites still read it -- so leaving it unwritten would break routing,
and letting some other code write it independently would recreate exactly the
divergence this module exists to end.

STATUS LIFECYCLE, AND WHY IT IS TWO STEPS
A row is inserted `provisioning` and only becomes `active` once the voice path is
configured. `provisioning` is deliberately excluded from
phone_lifecycle.ROUTABLE_STATUSES, so between the two calls an inbound caller
cannot be routed to a number whose webhook is not wired -- they would reach
silence. The legacy scalar is mirrored at the SAME moment the row becomes
routable, for the same reason: the scalar is a routing source.

NOTHING HERE TOUCHES THE PROVIDER. It records what the provider already did.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db import phone_numbers as db_phones
from db import supabase as db
from services import phone_lifecycle as lifecycle

logger = logging.getLogger(__name__)

OK = "ok"
CONFLICT = "live_conflict"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def register_permanent(*, tenant_id: str, e164: str, provider_account_sid: str,
                             provider_sid: str, iso_country: str,
                             tenant_location_id: str | None = None,
                             regulatory_profile_id: str | None = None) -> dict:
    """Record a permanent number that now exists at the provider.

    Inserted as `provisioning`: it is ours, but it is not yet routable. Returns
    the existing row unchanged when this number is already recorded, so a retried
    provisioning attempt resumes instead of tripping the partial unique indexes.
    """
    existing = await db_phones.find_owned_by_e164(e164)
    if existing and str(existing.get("tenant_id")) == str(tenant_id):
        return {"status": OK, "row": existing, "created": False}
    if existing:
        # Another tenant holds this E.164. The index would refuse it anyway; say
        # so as a conflict rather than letting a 23505 escape.
        logger.error("Number already owned by a different tenant — refusing to "
                     "register it for tenant %s", tenant_id)
        return {"status": CONFLICT, "row": None, "created": False,
                "detail": "number_owned_by_another_tenant"}

    rows = await db_phones.list_for_tenant(tenant_id)
    candidate = {"purpose": lifecycle.PURPOSE_PERMANENT,
                 "status": lifecycle.STATUS_PROVISIONING}
    conflict = lifecycle.live_conflict(rows, candidate)
    if conflict:
        logger.error("Tenant %s already holds a live permanent number — refusing "
                     "a second (%s)", tenant_id, conflict)
        return {"status": CONFLICT, "row": None, "created": False,
                "detail": conflict}

    row = await db_phones.insert_number({
        "tenant_id": tenant_id, "tenant_location_id": tenant_location_id,
        "regulatory_profile_id": regulatory_profile_id,
        "e164": e164, "purpose": lifecycle.PURPOSE_PERMANENT,
        "status": lifecycle.STATUS_PROVISIONING,
        "provider": "twilio", "provider_account_sid": provider_account_sid,
        "provider_sid": provider_sid, "iso_country": iso_country})
    return {"status": OK, "row": row, "created": True}


async def mark_active(*, tenant_id: str, number_row_id: str, e164: str) -> dict:
    """The voice path is configured: make the number routable and mirror the scalar.

    The scalar is written HERE and nowhere else in the provisioning path, so the
    canonical row and the legacy pointer can never describe different numbers.
    """
    row = await db_phones.update_number(number_row_id,
                                       {"status": lifecycle.STATUS_ACTIVE})
    await db.update_tenant(tenant_id, {"twilio_phone_number": e164})
    return {"status": OK, "row": row}


STALE = "stale"


async def current_permanent_conflict(tenant_id: str) -> dict | None:
    """The live permanent row that would refuse a new one, or None.

    The cheap local preflight the reprovision path was missing. W9I-B routed
    reprovision through register_permanent() but left its guard reading the
    legacy scalar, so a tenant whose scalar was clear and whose canonical row was
    still live passed the guard, bought a real number, and was refused after the
    money was spent -- USD 1.15 per attempt, measured, non-refundable.

    This does NOT replace the post-purchase check. A preflight can only see the
    world as it was a moment ago; register_permanent's live_conflict and the
    tpn_one_current_permanent index are what hold under concurrency. The
    preflight exists to stop the PREDICTABLE spend, not the racing one.
    """
    return await db_phones.get_current_permanent(tenant_id)


async def mark_released(*, tenant_id: str, number_row_id: str, expected_e164: str,
                        expected_provider_sid: str,
                        expected_provider_account_sid: str,
                        last_error: str = "") -> dict:
    """THE ONE PLACE a number leaves our possession, in the application's books.

    Call this only with authoritative proof from the provider: a confirmed delete
    or an authoritative 404. "We asked and something went wrong" is not proof --
    a timeout, 401, 403, 429, 5xx or malformed body all mean the number may still
    be ours and still be billing, and a row marked released on that basis makes
    the number unfindable by every reconciliation path we have. Those cases must
    leave the row exactly as it is, so the next run can try again.

    Canonical first, scalar second, both fenced on the same E.164. The canonical
    table is the authority: if the CAS does not land, the scalar is left alone,
    because a cleared scalar next to a live canonical row is the divergence this
    module exists to prevent.

    Returns {"status": OK|STALE, "released": bool, "idempotent": bool,
             "scalar_cleared": bool, "row": dict|None, "detail": str}.
    """
    changed = await db_phones.release_number_cas(
        number_id=number_row_id, tenant_id=tenant_id, e164=expected_e164,
        provider_sid=expected_provider_sid,
        provider_account_sid=expected_provider_account_sid,
        last_error=last_error)

    idempotent = False
    if len(changed) == 1:
        row = changed[0]
    else:
        # Zero rows is ambiguous on its own -- already released, or moved under
        # us. Re-read and let the row say which.
        row = await db_phones.get_by_id(number_row_id)
        if row is None:
            logger.error("release: canonical row %s is gone for tenant %s",
                         number_row_id, tenant_id)
            return {"status": STALE, "released": False, "idempotent": False,
                    "scalar_cleared": False, "row": None, "detail": "row_missing"}
        identity_matches = (
            str(row.get("tenant_id") or "") == str(tenant_id)
            and str(row.get("e164") or "") == expected_e164
            and str(row.get("provider_sid") or "") == expected_provider_sid
            and str(row.get("provider_account_sid") or "") == expected_provider_account_sid)
        if identity_matches and lifecycle.is_released(row):
            idempotent = True          # a retry of a release that already landed
        else:
            # Either the identity moved (a replacement occupies this row id --
            # impossible today, but the fence is what makes it impossible) or the
            # status is one we must not release from. Fail closed either way.
            logger.error(
                "release: refusing to transition canonical row %s for tenant %s "
                "-- identity_matches=%s status=%s", number_row_id, tenant_id,
                identity_matches, row.get("status"))
            return {"status": STALE, "released": False, "idempotent": False,
                    "scalar_cleared": False, "row": row,
                    "detail": "identity_mismatch" if not identity_matches
                              else f"unreleasable_status:{row.get('status')}"}

    # The canonical row is released. Now, and only now, the legacy pointer -- and
    # only while it still names the number we just released.
    released_at = str(row.get("released_at") or "") or _now_iso()
    cleared = await db.clear_tenant_number_fenced(tenant_id, expected_e164, released_at)
    if not cleared:
        logger.info(
            "release: legacy scalar for tenant %s no longer named %s -- left "
            "untouched (already clear, or moved to a replacement)",
            tenant_id, expected_e164)

    return {"status": OK, "released": True, "idempotent": idempotent,
            "scalar_cleared": bool(cleared), "row": row, "detail": ""}


async def register_temporary(*, tenant_id: str, e164: str, provider_account_sid: str,
                             provider_sid: str, iso_country: str) -> dict:
    """Record a temporary test number that now exists at the provider (W9I-E).

    THE LEGACY SCALAR IS NOT WRITTEN, HERE OR IN mark_temporary_active.
    `tenants.twilio_phone_number` was built around one primary business number
    and every reader treats it as such: the reclaim sweep selects on it, the
    release path clears it, the retention purge gates on it, and the welcome
    email prints it as "your number". Putting a temporary number there would make
    all of those describe a number that is by design going away -- and the
    reclaim sweep in particular would start counting a free test line against a
    trial deadline.

    Routing does not need it. `get_tenant_by_phone` consults the canonical model
    FIRST and only falls back to the scalar, so an ACTIVE temporary row resolves
    on its own. W9I-B.1 proved that path; this relies on it rather than
    re-teaching the scalar a second meaning.
    """
    existing = await db_phones.find_owned_by_e164(e164)
    if existing and str(existing.get("tenant_id")) == str(tenant_id):
        return {"status": OK, "row": existing, "created": False}
    if existing:
        logger.error("Temporary number already owned by a different tenant — "
                     "refusing to register it for tenant %s", tenant_id)
        return {"status": CONFLICT, "row": None, "created": False,
                "detail": "number_owned_by_another_tenant"}

    rows = await db_phones.list_for_tenant(tenant_id)
    candidate = {"purpose": lifecycle.PURPOSE_TEMPORARY,
                 "status": lifecycle.STATUS_PROVISIONING, "e164": e164}
    conflict = lifecycle.live_conflict(rows, candidate)
    if conflict:
        logger.error("Tenant %s already holds a live temporary number — refusing "
                     "a second (%s)", tenant_id, conflict)
        return {"status": CONFLICT, "row": None, "created": False,
                "detail": conflict}

    row = await db_phones.insert_number({
        "tenant_id": tenant_id, "e164": e164,
        "purpose": lifecycle.PURPOSE_TEMPORARY,
        "status": lifecycle.STATUS_PROVISIONING,
        "provider": "twilio", "provider_account_sid": provider_account_sid,
        "provider_sid": provider_sid, "iso_country": iso_country})
    return {"status": OK, "row": row, "created": True}


async def mark_temporary_active(*, tenant_id: str, number_row_id: str,
                                vapi_phone_number_id: str = "") -> dict:
    """The temporary number's voice path is proved: make it routable.

    The counterpart to mark_active, and deliberately a SEPARATE function rather
    than a flag on it. mark_active mirrors the legacy scalar, which is exactly
    what must not happen here -- and a boolean argument controlling whether the
    scalar gets written is the kind of thing that gets passed wrongly once.

    The Vapi phone id is stored ON THE CANONICAL ROW, not on the tenant.
    `tenants.vapi_phone_number_id` holds the permanent number's record and is
    what the release path detaches; a temporary number's record belongs beside
    the temporary number, so the two can be retired independently in W9I-G.
    """
    patch = {"status": lifecycle.STATUS_ACTIVE}
    if vapi_phone_number_id:
        patch["vapi_phone_number_id"] = vapi_phone_number_id
    row = await db_phones.update_number(number_row_id, patch)
    return {"status": OK, "row": row}
