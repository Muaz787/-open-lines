"""
W7D — a Square booking webhook names ONE tenant location, or changes nothing.

WHAT THIS REPLACES
The shipped handler routed by merchant_id through a `.limit(1)` lookup and then
mutated whatever tenant came back, never reading booking.location_id at all. On a
merchant mapping to more than one tenant that is a coin toss with side effects.
It is safe in production today only by accident: the merchant happens to resolve
to a tenant whose appointments are switched off.

THE IDENTITY RULE
    signed event -> merchant candidate set + booking.location_id
                 -> W7A resolver -> EXACTLY ONE tenant/location
                 -> authoritative provider read
                 -> ownership-aware, version-guarded LOCAL reconciliation
Anything else changes nothing.

OBSERVATION, NEVER COMMAND
A webhook reports what Square has ALREADY done. It may bring local state into line
with proven provider truth; it may never call Square. There is no CreateBooking,
no CancelBooking, and no code path here that could acquire one -- asserted by test.

TWO THINGS THAT CANNOT HAPPEN HERE, BY CONSTRUCTION
1. Resurrection. The webhook never writes status='confirmed' onto an existing row.
   Only cancellation propagates. The historical bug -- read a confirmed row, have
   W6A2 cancel it underneath, then write the stale dict back -- is impossible when
   the only status this code can write is 'cancelled'.
2. A stale event winning. Every write goes through a conditional UPDATE whose
   predicate carries the version guard, so two workers cannot both pass a
   read-then-write window.

NOT IN SCOPE
catalog.version.updated still routes by merchant alone and still has the
ambiguity problem. That is deliberately untouched here: catalog events carry no
location, so they need a different answer and a separate workstream.
"""
from __future__ import annotations

import logging

import db.supabase as db
from db import mutation_claims as db_mc
from db import reschedule_ops as db_ops
from services import square_booking, square_webhook_resolution as resolver
from services import square_webhook_identity as identity
from services import square_webhook_observability as obs

logger = logging.getLogger(__name__)

BOOKING_EVENTS = ("booking.created", "booking.updated")

# Outcomes. The resolver's own refusals pass through unchanged so an operator
# reading the ledger sees one vocabulary.
RECONCILED_UPDATED = "reconciled_updated"
RECONCILED_CREATED = "reconciled_created"
NOOP_STALE = "noop_stale"                     # older or duplicate version
NOOP_NO_CHANGE = "noop_no_change"             # nothing to bring into line
DEFERRED_OWNED = "deferred_owned"             # another workflow owns the row
DEFERRED_RESCHEDULE = "deferred_reschedule"   # a live W6A2 operation targets this
LOCATION_CONFLICT = "location_conflict"       # event location != authoritative
IDENTITY_CONFLICT_OP = "identity_conflict_operation"  # operation tenant disagrees
PROVIDER_UNKNOWN = "provider_unknown"         # could not read provider truth
PROVIDER_ABSENT = "provider_absent"           # 404 for an event Square just sent
NOT_BOOKING_EVENT = "not_booking_event"
NO_CREDENTIAL = "no_credential"

# Only these justify asking Square to retry. Everything else is either done or
# permanently unresolvable, and a permanent refusal must NOT become an endless
# retry loop -- Square eventually disables a subscription that keeps failing, and
# that subscription also carries payments.
RETRYABLE = frozenset({PROVIDER_UNKNOWN})

# Square booking statuses that mean "this appointment is not happening".
# Matched by substring for the CANCELLED_BY_* family, exactly for the rest.
_TERMINAL_EXACT = frozenset({"DECLINED", "NO_SHOW"})


def is_terminal_status(status: str) -> bool:
    s = (status or "").upper()
    return "CANCELLED" in s or s in _TERMINAL_EXACT


class Outcome:
    __slots__ = ("result", "tenant_id", "tenant_location_id", "appointment_id",
                 "provider_version", "detail")

    def __init__(self, result, *, tenant_id="", tenant_location_id="",
                 appointment_id="", provider_version=None, detail=""):
        self.result = result
        self.tenant_id = tenant_id
        self.tenant_location_id = tenant_location_id
        self.appointment_id = appointment_id
        self.provider_version = provider_version
        self.detail = detail

    @property
    def should_retry(self) -> bool:
        return self.result in RETRYABLE

    def __repr__(self):
        return f"Outcome({self.result}, appt={self.appointment_id or '-'}, {self.detail!r})"


async def _resolve_identity(meta: dict) -> tuple[resolver.Resolution, dict]:
    """W7A resolution, in-request. The ledger is never the routing authority.

    Since W7D.1 the computation lives in square_webhook_identity, shared with
    W7B telemetry so one delivery costs one pair of routing reads instead of
    two. What did NOT change is where authority comes from: the two DB reads
    and the pure resolver, in this request. Nothing is read back from
    provider_webhook_events, then or now.
    """
    return await identity.load_and_resolve(meta)


async def reconcile_booking_event(
        event: dict, *, resolution: resolver.Resolution | None = None) -> Outcome:
    """Route and reconcile one booking webhook. Makes NO provider mutation.

    `resolution` is the W7D.1 resolve-once hand-off. The caller may pass the
    Resolution already computed for this delivery, saving the two routing reads
    telemetry has just made with identical inputs.

    CORRECTNESS NEVER DEPENDS ON BEING GIVEN ONE. If the caller passes nothing
    -- because it is not the webhook endpoint, or because the shared
    computation failed open -- this resolves for itself and behaves exactly as
    it did before W7D.1. A telemetry path that is allowed to fail must never be
    able to change what a booking event may mutate, and the only way to
    guarantee that is for the fallback to be real.

    What is passed is an immutable in-memory Resolution computed from DB inputs
    in this request. It is NOT read back from the ledger, which stays evidence
    and never routing authority.
    """
    meta = obs.extract(event)
    if meta["event_type"] not in BOOKING_EVENTS:
        return Outcome(NOT_BOOKING_EVENT)

    # ── identity ────────────────────────────────────────────────────────────
    if resolution is not None:
        res = resolution
    else:
        res, _binding = await _resolve_identity(meta)
    if not res.may_mutate:
        # Every refusal is permanent for this event: the same payload resolved
        # again would refuse again. Recorded loudly, never retried.
        logger.warning("W7D: booking event %s not routed (%s) — no mutation. %s",
                       meta["provider_event_id"], res.outcome, res.detail)
        return Outcome(res.outcome, detail=res.detail)

    tenant_id, location_id = res.tenant_id, res.tenant_location_id
    booking_id = meta["object_id"]
    if not booking_id:
        # No provider identity, nothing to reconcile against. Belt-and-braces: an
        # empty id is also excluded from the appointments identity constraint, so
        # mirroring one would create a row nothing could ever match again.
        logger.warning("W7D: booking event %s carries no booking id — nothing to do",
                       meta["provider_event_id"])
        return Outcome(NOT_BOOKING_EVENT, tenant_id=tenant_id,
                       tenant_location_id=location_id, detail="no provider booking id")

    tenant = await db.get_tenant_by_id(tenant_id) or {}
    token = await square_booking.get_access_token(tenant)
    if not token:
        logger.error("W7D: tenant %s has no Square credential — cannot verify "
                     "booking %s", tenant_id, booking_id)
        return Outcome(NO_CREDENTIAL, tenant_id=tenant_id,
                       tenant_location_id=location_id)

    # ── authoritative provider read (READ ONLY) ─────────────────────────────
    fetch_status, booking = await square_booking.get_booking_detailed(token, booking_id)

    if fetch_status == square_booking.FETCH_UNKNOWN:
        # We could not establish provider truth. Reconciling from the event body
        # would mean acting on data we could not confirm, which is precisely what
        # this layer exists to avoid.
        logger.warning("W7D: could not read booking %s authoritatively — leaving "
                       "local state untouched", booking_id)
        return Outcome(PROVIDER_UNKNOWN, tenant_id=tenant_id,
                       tenant_location_id=location_id)

    existing = await db.get_appointment_by_provider_booking(booking_id)

    if fetch_status == square_booking.FETCH_NOT_FOUND:
        # A 404 is definitive in C1's taxonomy, and D2 acts on it — but D2 is
        # asking "did my cancellation land?", where absence answers the question.
        # Here it would mean DESTROYING a local appointment, and the two are not
        # the same risk.
        #
        # Measured evidence says a 404 is never how a booking ends: cancelling in
        # the D2/D3 live proofs left the booking fully retrievable by GET with
        # status CANCELLED_BY_SELLER. Square signals cancellation as a STATUS
        # CHANGE, not as deletion. So a 404 on a booking we hold a mirror for is
        # anomalous, not informative — and cancelling on it buys nothing, because
        # a genuine cancellation arrives as booking.updated with a terminal
        # status, which this path handles properly.
        #
        # Nothing is mutated either way. Loud, and safe.
        logger.error("W7D: ANOMALY — booking %s not found at the provider, but a %s "
                     "event was delivered for it%s. No local mutation.",
                     booking_id, meta["event_type"],
                     f" (local appointment {existing['id']})" if existing else
                     " and nothing is mirrored locally")
        return Outcome(PROVIDER_ABSENT, tenant_id=tenant_id,
                       tenant_location_id=location_id,
                       appointment_id=str(existing["id"]) if existing else "",
                       detail="provider reports the booking absent; refusing to "
                              "cancel a local row on an absence Square never uses "
                              "to signal cancellation")

    # ── the authoritative copy must agree about WHERE it happened ───────────
    auth_location = str(booking.get("location_id") or "")
    if auth_location and auth_location != meta["provider_location_id"]:
        logger.error("W7D: LOCATION CONFLICT — event for booking %s says %s but the "
                     "authoritative read says %s. Refusing to mutate; identity was "
                     "already resolved against the event's location.",
                     booking_id, meta["provider_location_id"], auth_location)
        return Outcome(LOCATION_CONFLICT, tenant_id=tenant_id,
                       tenant_location_id=location_id,
                       detail=f"event {meta['provider_location_id']} != authoritative {auth_location}")

    # Provider truth wins over the event body, including when the GET has moved
    # ahead of the event that woke us.
    auth_version = booking.get("version")
    if auth_version is None:
        auth_version = meta.get("provider_version")
    auth_updated = booking.get("updated_at") or meta.get("provider_updated_at")
    terminal = is_terminal_status(booking.get("status") or "")

    # ── ownership: a webhook never races the workflow that owns a row ───────
    if existing:
        claim = None
        try:
            claim = await db_mc.get_claim(str(existing["id"]))
        except Exception as e:
            logger.warning("W7D: could not read the mutation claim for %s: %s",
                           existing["id"], e)
        if claim:
            # The owner reads provider truth itself and reconciles under its own
            # rules -- C3's cancel reconciliation and D2's recovery both do. A
            # second writer here could only corrupt the assumptions it is working
            # from, most sharply W6A2's frozen source fingerprint.
            logger.info("W7D: appointment %s is owned by a %s — deferring "
                        "reconciliation of booking %s", existing["id"],
                        claim.get("operation_type"), booking_id)
            return Outcome(DEFERRED_OWNED, tenant_id=tenant_id,
                           tenant_location_id=location_id,
                           appointment_id=str(existing["id"]),
                           provider_version=auth_version,
                           detail=f"owned by {claim.get('operation_type')}")

        return await _update_existing(existing, booking, meta, tenant_id, location_id,
                                      auth_version, auth_updated, terminal)

    # ── no local row: is this booking a W6A2 replacement mid-flight? ────────
    # EXACT provider identity. D2 names the booking on its operation the moment
    # CreateBooking returns, before inserting the local row, so the gap between
    # those two writes has a definite answer. No inference from tenant, location,
    # start time, staff or service — Square gave us a unique id and guessing when
    # the provider has already told us is indefensible.
    owner_op = await _operation_owning(booking_id)
    if owner_op:
        if str(owner_op.get("target_provider_location_id") or "") != meta["provider_location_id"]:
            logger.error("W7D: CONSISTENCY INCIDENT — booking %s is named by operation %s "
                         "targeting %s, but this event routed to %s. Refusing to attach it.",
                         booking_id, owner_op.get("id"),
                         owner_op.get("target_provider_location_id"),
                         meta["provider_location_id"])
            return Outcome(LOCATION_CONFLICT, tenant_id=tenant_id,
                           tenant_location_id=location_id,
                           detail="operation target location disagrees with the event")
        if str(owner_op.get("tenant_id") or "") != tenant_id:
            logger.error("W7D: CONSISTENCY INCIDENT — booking %s belongs to operation %s "
                         "of tenant %s, but routed to tenant %s.",
                         booking_id, owner_op.get("id"), owner_op.get("tenant_id"), tenant_id)
            return Outcome(IDENTITY_CONFLICT_OP, tenant_id=tenant_id,
                           tenant_location_id=location_id,
                           detail="operation tenant disagrees with the routed tenant")
        logger.info("W7D: booking %s is the replacement of operation %s — deferring to "
                    "W6A2, which owns its local row", booking_id, owner_op.get("id"))
        return Outcome(DEFERRED_RESCHEDULE, tenant_id=tenant_id,
                       tenant_location_id=location_id, provider_version=auth_version,
                       detail=f"replacement of operation {owner_op.get('id')}")

    # TRANSITIONAL: an operation created before migration 026 may have made a
    # booking it cannot name. Deferring is recoverable; a duplicate appointment is
    # not. Production has zero reschedule operations, so this is a no-op today and
    # exists only for the deploy window.
    if await _has_unidentified_operation(tenant_id):
        logger.warning("W7D: tenant %s has an in_progress reschedule with no recorded "
                       "replacement booking id — deferring mirror creation for %s",
                       tenant_id, booking_id)
        return Outcome(DEFERRED_RESCHEDULE, tenant_id=tenant_id,
                       tenant_location_id=location_id, provider_version=auth_version,
                       detail="a pre-026 operation may own this booking")

    if terminal:
        # A booking that is already cancelled has nothing worth mirroring.
        return Outcome(NOOP_NO_CHANGE, tenant_id=tenant_id,
                       tenant_location_id=location_id, provider_version=auth_version,
                       detail=f"booking is {booking.get('status')}; no mirror created")

    return await _create_mirror(booking, meta, tenant_id, location_id,
                                auth_version, auth_updated)


async def _operation_owning(booking_id: str) -> dict | None:
    """The W6A2 operation that created this exact booking, or None.

    Fails CLOSED on error by raising: a lookup failure must not be read as
    "no operation owns this", which would mirror a replacement and leave two local
    rows for one provider booking.
    """
    return await db_ops.get_operation_by_replacement_booking(booking_id)


async def _has_unidentified_operation(tenant_id: str) -> bool:
    try:
        return bool(await db_ops.list_unidentified_in_progress(tenant_id))
    except Exception as e:
        logger.warning("W7D: pre-026 operation check failed for %s: %s", tenant_id, e)
        return True          # fail closed


async def _apply_terminal(existing: dict, meta: dict, tenant_id: str, location_id: str,
                          *, version, updated_at, why: str) -> Outcome:
    """Propagate a cancellation, version-guarded. Never writes any other status."""
    if (existing.get("status") or "") == "cancelled":
        return Outcome(NOOP_NO_CHANGE, tenant_id=tenant_id,
                       tenant_location_id=location_id,
                       appointment_id=str(existing["id"]), provider_version=version,
                       detail="already cancelled locally")
    patch = {"status": "cancelled"}
    if updated_at:
        patch["provider_updated_at"] = str(updated_at)
    won = await db.reconcile_appointment_if_newer(str(existing["id"]), version, patch)
    if not won:
        return Outcome(NOOP_STALE, tenant_id=tenant_id, tenant_location_id=location_id,
                       appointment_id=str(existing["id"]), provider_version=version,
                       detail="a newer provider version is already recorded")
    logger.info("W7D: appointment %s cancelled from provider truth (%s)",
                existing["id"], why)
    return Outcome(RECONCILED_UPDATED, tenant_id=tenant_id,
                   tenant_location_id=location_id, appointment_id=str(existing["id"]),
                   provider_version=version, detail=why)


async def _update_existing(existing: dict, booking: dict, meta: dict, tenant_id: str,
                           location_id: str, version, updated_at, terminal: bool) -> Outcome:
    """Bring an existing row into line. NARROW columns only.

    Deliberately never writes status='confirmed'. A webhook can tell us an
    appointment stopped happening; it is not a reason to declare one alive again,
    and refusing to write that status is what makes resurrection impossible
    rather than merely unlikely.
    """
    if terminal:
        return await _apply_terminal(existing, meta, tenant_id, location_id,
                                     version=version, updated_at=updated_at,
                                     why=f"provider status {booking.get('status')}")

    patch: dict = {}
    start_at = booking.get("start_at")
    if start_at and str(existing.get("appointment_datetime") or "") != str(start_at):
        patch["appointment_datetime"] = str(start_at)
    # Stamp location on a legacy row the first time authoritative truth touches it.
    if not existing.get("tenant_location_id"):
        patch["tenant_location_id"] = location_id
    if not existing.get("provider_location_id"):
        patch["provider_location_id"] = meta["provider_location_id"]
    if updated_at:
        patch["provider_updated_at"] = str(updated_at)

    if not patch:
        # Still record the version we verified, so a later stale event is a no-op.
        won = await db.reconcile_appointment_if_newer(str(existing["id"]), version, {})
        return Outcome(NOOP_NO_CHANGE if won else NOOP_STALE, tenant_id=tenant_id,
                       tenant_location_id=location_id,
                       appointment_id=str(existing["id"]), provider_version=version,
                       detail="local row already matches provider truth")

    won = await db.reconcile_appointment_if_newer(str(existing["id"]), version, patch)
    if not won:
        return Outcome(NOOP_STALE, tenant_id=tenant_id, tenant_location_id=location_id,
                       appointment_id=str(existing["id"]), provider_version=version,
                       detail="a newer provider version is already recorded")
    logger.info("W7D: appointment %s reconciled to provider version %s (%s)",
                existing["id"], version, ", ".join(sorted(patch)))
    return Outcome(RECONCILED_UPDATED, tenant_id=tenant_id,
                   tenant_location_id=location_id, appointment_id=str(existing["id"]),
                   provider_version=version, detail=", ".join(sorted(patch)))


async def _create_mirror(booking: dict, meta: dict, tenant_id: str, location_id: str,
                         version, updated_at) -> Outcome:
    """Mirror an externally-created Square booking, stamped with its location.

    The location columns are the point. Without them every externally-booked
    appointment is legacy-shaped, and W6A2 refuses to reschedule it
    (LEGACY_LOCATION) -- so a caller who booked on Square's website could never
    move it by phone. That is the B3 defect, closed here.
    """
    seg = (booking.get("appointment_segments") or [{}])[0]

    name, phone = "", ""
    service_name, staff_name = "", ""
    try:
        services = {s["square_variation_id"]: s
                    for s in await db.get_square_services(tenant_id, bookable_only=False)}
        service_name = (services.get(seg.get("service_variation_id")) or {}).get("name") or ""
        staff = {s["square_team_member_id"]: s.get("display_name")
                 for s in await db.get_square_staff(tenant_id)}
        staff_name = staff.get(seg.get("team_member_id")) or ""
    except Exception as e:
        logger.warning("W7D: service/staff lookup failed for tenant %s: %s", tenant_id, e)

    row = {
        "tenant_id": tenant_id,
        "caller_name": name or None,
        "caller_phone": phone or None,
        "service": service_name or "Appointment",
        "appointment_datetime": booking.get("start_at"),
        "duration_minutes": seg.get("duration_minutes") or 60,
        "status": "confirmed",
        "google_event_id": meta["object_id"],
        "source": "square",
        # THE FIX: both location columns, so W6A2 can reschedule this later.
        "tenant_location_id": location_id,
        "provider_location_id": meta["provider_location_id"],
        "provider_version": int(version) if version is not None else None,
        "provider_updated_at": str(updated_at) if updated_at else None,
    }
    if staff_name:
        row["staff_name"] = staff_name

    try:
        created = await db.insert_appointment(row)
    except Exception as e:
        logger.error("W7D: could not mirror booking %s for tenant %s: %s",
                     meta["object_id"], tenant_id, e)
        raise

    logger.info("W7D: mirrored external booking %s for tenant %s at location %s",
                meta["object_id"], tenant_id, location_id)
    return Outcome(RECONCILED_CREATED, tenant_id=tenant_id,
                   tenant_location_id=location_id,
                   appointment_id=str((created or {}).get("id") or ""),
                   provider_version=version)
