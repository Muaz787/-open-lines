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
from db import square_routing
from services import square_booking, square_webhook_resolution as resolver
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
PROVIDER_UNKNOWN = "provider_unknown"         # could not read provider truth
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
    """W7A resolution, in-request. The ledger is never the routing authority."""
    merchant_candidates = await square_routing.list_tenants_by_square_merchant_id(
        meta.get("merchant_id") or "")
    location_bindings = await square_routing.load_location_candidates(
        meta.get("provider_location_id") or "")
    res = resolver.resolve_square_tenant_location(
        merchant_id=meta.get("merchant_id") or "",
        merchant_candidates=merchant_candidates,
        provider_location_id=meta.get("provider_location_id") or "",
        location_bindings=location_bindings)
    binding = next((c for c in location_bindings
                    if str((c.get("binding") or {}).get("id") or "") == res.binding_id), {})
    return res, binding


async def reconcile_booking_event(event: dict) -> Outcome:
    """Route and reconcile one booking webhook. Makes NO provider mutation."""
    meta = obs.extract(event)
    if meta["event_type"] not in BOOKING_EVENTS:
        return Outcome(NOT_BOOKING_EVENT)

    # ── identity ────────────────────────────────────────────────────────────
    res, _binding = await _resolve_identity(meta)
    if not res.may_mutate:
        # Every refusal is permanent for this event: the same payload resolved
        # again would refuse again. Recorded loudly, never retried.
        logger.warning("W7D: booking event %s not routed (%s) — no mutation. %s",
                       meta["provider_event_id"], res.outcome, res.detail)
        return Outcome(res.outcome, detail=res.detail)

    tenant_id, location_id = res.tenant_id, res.tenant_location_id
    booking_id = meta["object_id"]

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
        # Square says this booking does not exist. Same reading W6A1/D2 already
        # take for a 404: definitive absence, reconcile a local mirror to
        # cancelled. Nothing is created for a booking that is not there.
        if not existing:
            return Outcome(NOOP_NO_CHANGE, tenant_id=tenant_id,
                           tenant_location_id=location_id,
                           detail="provider reports the booking absent; nothing local")
        return await _apply_terminal(existing, meta, tenant_id, location_id,
                                     version=meta.get("provider_version"),
                                     updated_at=meta.get("provider_updated_at"),
                                     why="provider reports the booking absent")

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

    # ── no local row: is a live W6A2 operation about to create one? ─────────
    if await _reschedule_in_flight_for(tenant_id, meta["provider_location_id"],
                                       booking.get("start_at") or ""):
        # D2 has created this replacement at Square and has not yet persisted its
        # local row. Mirroring it here would produce a second appointment for one
        # provider booking -- the lineage index would not catch it, because a
        # mirror carries no rescheduled_from.
        logger.info("W7D: a live reschedule targets %s at %s — deferring mirror "
                    "creation for booking %s", meta["provider_location_id"],
                    booking.get("start_at"), booking_id)
        return Outcome(DEFERRED_RESCHEDULE, tenant_id=tenant_id,
                       tenant_location_id=location_id, provider_version=auth_version)

    if terminal:
        # A booking that is already cancelled has nothing worth mirroring.
        return Outcome(NOOP_NO_CHANGE, tenant_id=tenant_id,
                       tenant_location_id=location_id, provider_version=auth_version,
                       detail=f"booking is {booking.get('status')}; no mirror created")

    return await _create_mirror(booking, meta, tenant_id, location_id,
                                auth_version, auth_updated)


async def _reschedule_in_flight_for(tenant_id: str, provider_location_id: str,
                                    start_at: str) -> bool:
    """Is a live W6A2 operation about to create exactly this booking locally?"""
    if not (tenant_id and provider_location_id and start_at):
        return False
    try:
        return bool(await db_ops.list_live_operations_for_target(
            tenant_id, provider_location_id, start_at))
    except Exception as e:
        logger.warning("W7D: live-operation check failed for %s: %s", tenant_id, e)
        # Fail closed: if we cannot rule out an in-flight reschedule, do not
        # create a row that might duplicate its replacement.
        return True


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
