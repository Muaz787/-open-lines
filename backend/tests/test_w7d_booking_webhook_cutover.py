"""
W7D — a Square booking webhook names one tenant location, or changes nothing.

WHAT THIS REPLACES
The shipped handler routed by merchant_id through `.limit(1)` and mutated
whatever tenant came back, never reading booking.location_id. It is safe in
production today only by accident: the merchant resolves to a tenant whose
appointments happen to be switched off.

THE TESTS THAT MATTER MOST
Two failure modes are structural here, and both are pinned by tests that assert
something did NOT happen:

  * Resurrection. The webhook never writes status='confirmed' onto an existing
    row. The historical bug — read a confirmed row, have W6A2 cancel it
    underneath, write the stale dict back — cannot occur when 'cancelled' is the
    only status this code can write to an existing row.

  * A stale event winning. Every write carries the version guard in the UPDATE's
    own predicate, so two workers cannot both pass a read-then-write window.

And the third, which is a whole-system property: a webhook is an OBSERVATION. It
may bring local state into line with proven provider truth; it may never call
Square. There is no CreateBooking or CancelBooking reachable from this path.
"""
import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from db import mutation_claims as db_mc, reschedule_ops as db_ops
from services import square_booking as sb
from services import square_booking_reconcile as rec
from services import square_webhook_resolution as wres

MERCHANT = "ML66K1YVCD1P0"
CORK_PID, DUB_PID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K"
DANI, SHAHID = "tenant-dani", "tenant-shahid"
CORK_LOC, DUB_LOC = "loc-cork", "loc-dublin"
BOOKING = "bk-real-1"


def _executable_source(module) -> str:
    """Module source with every docstring removed.

    These assertions are about what the CODE can do. Prose describing what it must
    never do would otherwise trip them — which is exactly what happened the first
    time this file ran.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(module))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and \
               isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def envelope(*, etype="booking.created", location_id=CORK_PID, version=0,
             status="ACCEPTED", booking_id=BOOKING, merchant=MERCHANT,
             event_id="evt-1", omit_location=False):
    b = {"id": booking_id, "status": status, "version": version,
         "start_at": "2026-10-05T13:00:00Z", "updated_at": "2026-09-11T14:08:09Z",
         "customer_id": "SQCUST-1",
         "appointment_segments": [{"team_member_id": "TM1",
                                   "service_variation_id": "VAR1",
                                   "service_variation_version": 17890,
                                   "duration_minutes": 60}]}
    if not omit_location:
        b["location_id"] = location_id
    return {"event_id": event_id, "type": etype, "merchant_id": merchant,
            "data": {"type": "booking", "id": booking_id, "object": {"booking": b}}}


def tenant(tid, *, appts=True, merchant=MERCHANT):
    return {"id": tid, "business_name": tid, "square_appointments_enabled": appts,
            "square_merchant_id": merchant}


def bundle(*, bid="b1", tid=DANI, lid=CORK_LOC, pid=CORK_PID, status="ACTIVE",
           appts=True):
    return {"binding": {"id": bid, "tenant_id": tid, "tenant_location_id": lid,
                        "provider": "square", "provider_location_id": pid,
                        "provider_status": status},
            "location": {"id": lid, "tenant_id": tid, "active": True,
                         "booking_enabled": True},
            "tenant": tenant(tid, appts=appts)}


def appt(aid="a-1", *, tid=DANI, booking=BOOKING, status="confirmed",
         version=None, loc=CORK_LOC, pid=CORK_PID,
         when="2026-10-05T13:00:00+00:00"):
    return {"id": aid, "tenant_id": tid, "google_event_id": booking,
            "status": status, "provider_version": version,
            "appointment_datetime": when, "tenant_location_id": loc,
            "provider_location_id": pid, "caller_phone": "+353871234567",
            "service": "Consultation", "duration_minutes": 60}


class World:
    """Appointments with the REAL conditional-update semantics of migration 025."""

    def __init__(self, appointments=None, claims=None, operations=None):
        self.appts = {a["id"]: dict(a) for a in (appointments or [])}
        self.claims = dict(claims or {})
        # operations keyed by their EXACT replacement provider booking id
        self.operations = list(operations or [])
        self.inserts = []
        self.lock = asyncio.Lock()

    async def by_booking(self, booking_id):
        for a in self.appts.values():
            if a.get("google_event_id") == booking_id:
                return dict(a)
        return None

    async def reconcile_if_newer(self, aid, version, patch):
        """Mirrors `or=(provider_version.is.null, provider_version.lt.N)`."""
        async with self.lock:
            a = self.appts.get(aid)
            if not a or version is None:
                return False
            stored = a.get("provider_version")
            if not (stored is None or int(stored) < int(version)):
                return False
            a.update(patch)
            a["provider_version"] = int(version)
            return True

    async def insert(self, row):
        async with self.lock:
            new = {**row, "id": f"a-new-{len(self.appts)}"}
            self.appts[new["id"]] = new
            self.inserts.append(new)
            return dict(new)

    async def get_claim(self, aid):
        c = self.claims.get(aid)
        return dict(c) if c else None

    async def op_by_booking(self, booking_id):
        for o in self.operations:
            if o.get("replacement_provider_booking_id") == booking_id:
                return dict(o)
        return None

    async def unidentified_in_progress(self, tid):
        return [o for o in self.operations
                if o.get("tenant_id") == tid and o.get("state") == "in_progress"
                and not o.get("replacement_provider_booking_id")]


@contextlib.contextmanager
def env(w, *, merchants=None, bindings=None, fetch=sb.FETCH_FOUND, booking=None,
        token="tok"):
    """booking = the AUTHORITATIVE provider read (may differ from the event)."""
    auth = booking if booking is not None else {
        "id": BOOKING, "status": "ACCEPTED", "version": 0, "location_id": CORK_PID,
        "start_at": "2026-10-05T13:00:00Z", "updated_at": "2026-09-11T14:08:09Z",
        "appointment_segments": [{"team_member_id": "TM1",
                                  "service_variation_id": "VAR1",
                                  "duration_minutes": 60}]}
    create = AsyncMock(side_effect=AssertionError("a webhook must never create a booking"))
    cancel = AsyncMock(side_effect=AssertionError("a webhook must never cancel a booking"))
    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=list(merchants if merchants is not None else [tenant(DANI)]))), \
         patch("db.square_routing.load_location_candidates",
               new=AsyncMock(return_value=list(bindings if bindings is not None else [bundle()]))), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=tenant(DANI))), \
         patch("db.supabase.get_appointment_by_provider_booking",
               new=AsyncMock(side_effect=w.by_booking)), \
         patch("db.supabase.reconcile_appointment_if_newer",
               new=AsyncMock(side_effect=w.reconcile_if_newer)), \
         patch("db.supabase.insert_appointment", new=AsyncMock(side_effect=w.insert)), \
         patch("db.supabase.get_square_services", new=AsyncMock(return_value=[
             {"square_variation_id": "VAR1", "name": "Consultation"}])), \
         patch("db.supabase.get_square_staff", new=AsyncMock(return_value=[
             {"square_team_member_id": "TM1", "display_name": "Aoife"}])), \
         patch("db.mutation_claims.get_claim", new=AsyncMock(side_effect=w.get_claim)), \
         patch("db.reschedule_ops.get_operation_by_replacement_booking",
               new=AsyncMock(side_effect=w.op_by_booking)), \
         patch("db.reschedule_ops.list_unidentified_in_progress",
               new=AsyncMock(side_effect=w.unidentified_in_progress)), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value=token)), \
         patch("services.square_booking.get_booking_detailed",
               new=AsyncMock(return_value=(fetch, dict(auth) if auth else {}))), \
         patch("services.square_booking.create_booking", new=create), \
         patch("services.square_booking.cancel_booking_detailed", new=cancel):
        yield {"create": create, "cancel": cancel}


async def run(ev=None, **kw):
    return await rec.reconcile_booking_event(ev or envelope(**kw))


# ═══════════════════════════════════════════════════════════════════════════
# A/B — routing to the exact tenant and location
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_A_booking_created_routes_to_the_exact_tenant_and_location():
    w = World()
    with env(w):
        out = await run()
    assert out.result == rec.RECONCILED_CREATED
    assert out.tenant_id == DANI and out.tenant_location_id == CORK_LOC


@pytest.mark.asyncio
async def test_B_booking_updated_reconciles_an_existing_row():
    w = World([appt(version=0)])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 3, "location_id": CORK_PID,
            "start_at": "2026-10-05T16:00:00Z", "updated_at": "2026-09-11T15:00:00Z",
            "appointment_segments": [{}]}
    with env(w, booking=auth):
        out = await run(etype="booking.updated", version=3)
    assert out.result == rec.RECONCILED_UPDATED
    assert w.appts["a-1"]["appointment_datetime"] == "2026-10-05T16:00:00Z"
    assert w.appts["a-1"]["provider_version"] == 3


@pytest.mark.asyncio
async def test_routing_uses_location_not_merchant():
    """Two tenants share the merchant; the location decides."""
    w = World()
    with env(w, merchants=[tenant(DANI), tenant(SHAHID)],
             bindings=[bundle(tid=DANI, lid=CORK_LOC, pid=CORK_PID)]):
        out = await run()
    assert out.tenant_id == DANI


# ═══════════════════════════════════════════════════════════════════════════
# C–G — every refusal changes nothing
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("label,kw,expected", [
    ("C unknown location", dict(bindings=[]), wres.UNBOUND_LOCATION),
    ("D inactive binding", dict(bindings=[bundle(status="INACTIVE")]), wres.INACTIVE_BINDING),
    ("E provider_status NULL", dict(bindings=[bundle(status=None)]), wres.INACTIVE_BINDING),
    ("F ambiguous binding", dict(merchants=[tenant(DANI), tenant(SHAHID)],
                                 bindings=[bundle(), bundle(bid="b2", tid=SHAHID, lid="loc-sh")]),
     wres.AMBIGUOUS_BINDING),
    ("G identity conflict", dict(merchants=[tenant(SHAHID)]), wres.IDENTITY_CONFLICT),
])
async def test_CDEFG_refusals_mutate_nothing(label, kw, expected):
    w = World([appt(version=0)])
    before = json.dumps(w.appts, sort_keys=True)
    with env(w, **kw) as e:
        out = await run()
    assert out.result == expected, label
    assert json.dumps(w.appts, sort_keys=True) == before, f"{label} mutated local state"
    assert w.inserts == []
    assert e["create"].await_count == 0 and e["cancel"].await_count == 0
    assert not out.should_retry, "a permanent refusal must not ask Square to retry"


@pytest.mark.asyncio
async def test_C_missing_location_in_payload_is_unknown_location():
    w = World()
    with env(w):
        out = await run(omit_location=True)
    assert out.result == wres.UNKNOWN_LOCATION
    assert w.inserts == []


# ═══════════════════════════════════════════════════════════════════════════
# H/I/J/K — version semantics
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_H_a_stale_event_never_regresses_local_state():
    """v8 recorded, then v7 arrives."""
    w = World([appt(version=8, when="2026-10-05T18:00:00Z")])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 7, "location_id": CORK_PID,
            "start_at": "2026-10-05T13:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        out = await run(version=7)
    assert out.result == rec.NOOP_STALE
    assert w.appts["a-1"]["provider_version"] == 8
    assert w.appts["a-1"]["appointment_datetime"] == "2026-10-05T18:00:00Z"


@pytest.mark.asyncio
async def test_I_a_duplicate_version_is_an_idempotent_no_op():
    w = World([appt(version=5, when="2026-10-05T13:00:00Z")])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 5, "location_id": CORK_PID,
            "start_at": "2026-10-05T19:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        out = await run(version=5)
    assert out.result == rec.NOOP_STALE
    assert w.appts["a-1"]["appointment_datetime"] == "2026-10-05T13:00:00Z"


@pytest.mark.asyncio
async def test_J_a_newer_version_is_applied():
    w = World([appt(version=5)])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 6, "location_id": CORK_PID,
            "start_at": "2026-10-05T20:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        out = await run(version=6)
    assert out.result == rec.RECONCILED_UPDATED
    assert w.appts["a-1"]["provider_version"] == 6


@pytest.mark.asyncio
async def test_K_provider_truth_wins_when_the_get_is_newer_than_the_event():
    """Event says v7; the authoritative read says v9. v9 is persisted."""
    w = World([appt(version=5)])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 9, "location_id": CORK_PID,
            "start_at": "2026-10-05T21:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        out = await run(version=7)
    assert out.result == rec.RECONCILED_UPDATED
    assert w.appts["a-1"]["provider_version"] == 9, "the GET, not the event, is authority"
    assert out.provider_version == 9


@pytest.mark.asyncio
async def test_a_legacy_row_with_null_version_upgrades_itself():
    w = World([appt(version=None)])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 4, "location_id": CORK_PID,
            "start_at": "2026-10-05T13:30:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        out = await run(version=4)
    assert out.result == rec.RECONCILED_UPDATED
    assert w.appts["a-1"]["provider_version"] == 4


@pytest.mark.asyncio
async def test_concurrent_workers_cannot_both_apply_the_same_version():
    w = World([appt(version=1)])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 2, "location_id": CORK_PID,
            "start_at": "2026-10-05T22:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        outs = await asyncio.gather(*(run(version=2) for _ in range(8)))
    applied = [o for o in outs if o.result == rec.RECONCILED_UPDATED]
    assert len(applied) == 1, f"{len(applied)} workers applied the same version"
    assert w.appts["a-1"]["provider_version"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# L/M/N — provider read outcomes
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_L_provider_not_found_does_NOT_cancel_a_local_appointment():
    """Square signals cancellation as a STATUS CHANGE, never as deletion — proven
    in the D2/D3 live proofs, where a cancelled booking stayed fully retrievable
    as CANCELLED_BY_SELLER. So a 404 is anomalous, not informative, and
    destroying a real appointment on it would be guessing."""
    w = World([appt(version=0)])
    before = json.dumps(w.appts, sort_keys=True)
    with env(w, fetch=sb.FETCH_NOT_FOUND, booking={}):
        out = await run(version=1)
    assert out.result == rec.PROVIDER_ABSENT
    assert json.dumps(w.appts, sort_keys=True) == before
    assert w.appts["a-1"]["status"] == "confirmed"
    assert not out.should_retry


@pytest.mark.asyncio
async def test_L2_provider_not_found_creates_nothing():
    w = World()
    with env(w, fetch=sb.FETCH_NOT_FOUND, booking={}):
        out = await run()
    assert out.result == rec.PROVIDER_ABSENT
    assert w.inserts == []


@pytest.mark.asyncio
async def test_M_provider_unknown_changes_nothing_and_IS_retryable():
    w = World([appt(version=0)])
    before = json.dumps(w.appts, sort_keys=True)
    with env(w, fetch=sb.FETCH_UNKNOWN, booking={}):
        out = await run(version=9)
    assert out.result == rec.PROVIDER_UNKNOWN
    assert out.should_retry is True
    assert json.dumps(w.appts, sort_keys=True) == before


@pytest.mark.asyncio
async def test_N_event_location_disagreeing_with_the_get_fails_closed():
    w = World([appt(version=0)])
    before = json.dumps(w.appts, sort_keys=True)
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 1, "location_id": DUB_PID,
            "start_at": "2026-10-05T13:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth) as e:
        out = await run(location_id=CORK_PID, version=1)
    assert out.result == rec.LOCATION_CONFLICT
    assert json.dumps(w.appts, sort_keys=True) == before
    assert e["create"].await_count == 0 and e["cancel"].await_count == 0
    assert not out.should_retry


# ═══════════════════════════════════════════════════════════════════════════
# O/P/Q — the B3 fix: mirrors carry their location
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_O_an_external_booking_is_mirrored():
    w = World()
    with env(w):
        out = await run()
    assert out.result == rec.RECONCILED_CREATED
    assert len(w.inserts) == 1
    m = w.inserts[0]
    assert m["google_event_id"] == BOOKING
    assert m["source"] == "square"
    assert m["status"] == "confirmed"
    assert m["service"] == "Consultation" and m["staff_name"] == "Aoife"


@pytest.mark.asyncio
async def test_P_the_mirror_stamps_BOTH_location_columns():
    w = World()
    with env(w):
        await run()
    m = w.inserts[0]
    assert m["tenant_location_id"] == CORK_LOC
    assert m["provider_location_id"] == CORK_PID
    assert m["provider_version"] == 0
    assert m["provider_updated_at"]


@pytest.mark.asyncio
async def test_Q_the_mirror_is_W6A2_reschedulable():
    """B3 closed: D1 refuses a source whose tenant_location_id is NULL
    (LEGACY_LOCATION). A stamped mirror passes that gate."""
    from services import reschedule
    w = World()
    with env(w):
        await run()
    m = w.inserts[0]
    assert m.get("tenant_location_id") and m.get("provider_location_id"), \
        "without both columns W6A2 returns LEGACY_LOCATION"
    assert m.get("google_event_id"), "D1 requires a provider booking id"
    assert m["status"] in ("confirmed", "pending_payment"), \
        "D1 only accepts these source statuses"
    assert reschedule.LEGACY_LOCATION == "legacy_location"


@pytest.mark.asyncio
async def test_an_existing_legacy_row_gets_its_location_stamped():
    w = World([appt(version=None, loc=None, pid=None)])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 2, "location_id": CORK_PID,
            "start_at": "2026-10-05T13:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        out = await run(version=2)
    assert out.result == rec.RECONCILED_UPDATED
    assert w.appts["a-1"]["tenant_location_id"] == CORK_LOC
    assert w.appts["a-1"]["provider_location_id"] == CORK_PID


# ═══════════════════════════════════════════════════════════════════════════
# R/S — narrow updates, and no resurrection
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_R_an_update_touches_only_proven_columns():
    w = World([appt(version=0)])
    w.appts["a-1"]["caller_name"] = "Aoife"
    w.appts["a-1"]["party_size"] = 3
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 1, "location_id": CORK_PID,
            "start_at": "2026-10-05T17:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        await run(version=1)
    a = w.appts["a-1"]
    assert a["caller_name"] == "Aoife" and a["party_size"] == 3
    assert a["appointment_datetime"] == "2026-10-05T17:00:00Z"


def test_R2_no_full_row_stale_dict_write_remains_anywhere():
    """The pattern that could resurrect a cancelled appointment."""
    import inspect
    src = inspect.getsource(rec)
    assert "{**existing" not in src
    assert "**existing," not in src


@pytest.mark.asyncio
async def test_S_a_cancelled_appointment_is_NEVER_resurrected():
    """The historical worst case: a worker holds a 'confirmed' read, W6A2 cancels
    the row, and the webhook then writes back what it remembered."""
    w = World([appt(version=0, status="cancelled")])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 5, "location_id": CORK_PID,
            "start_at": "2026-10-05T13:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        await run(version=5)
    assert w.appts["a-1"]["status"] == "cancelled", "an ACTIVE provider booking must "\
        "never flip a locally cancelled row back to confirmed"


def test_S2_confirmed_is_never_written_to_an_existing_row():
    """Structural: 'confirmed' is reachable only from the mirror-creation path."""
    import ast
    tree = ast.parse(_executable_source(rec))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.AsyncFunctionDef) and fn.name in (
                "_update_existing", "_apply_terminal"):
            assert "confirmed" not in ast.unparse(fn), \
                f"{fn.name} must not be able to write 'confirmed'"
    creators = [f.name for f in ast.walk(tree)
                if isinstance(f, ast.AsyncFunctionDef) and "confirmed" in ast.unparse(f)]
    assert creators == ["_create_mirror"], creators


# ═══════════════════════════════════════════════════════════════════════════
# T/U/V — W6A2 ownership
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("op_type", [db_mc.OP_CANCEL, db_mc.OP_RESCHEDULE,
                                     db_mc.OP_CANCEL_RECONCILE])
async def test_TU_an_owned_appointment_is_deferred_not_raced(op_type):
    w = World([appt(version=0)],
              claims={"a-1": {"appointment_id": "a-1", "operation_type": op_type,
                              "claim_token": "t", "claimed_at": "x"}})
    before = json.dumps(w.appts, sort_keys=True)
    auth = {"id": BOOKING, "status": "CANCELLED_BY_SELLER", "version": 4,
            "location_id": CORK_PID, "start_at": "2026-10-05T13:00:00Z",
            "appointment_segments": [{}]}
    with env(w, booking=auth) as e:
        out = await run(version=4)
    assert out.result == rec.DEFERRED_OWNED
    assert json.dumps(w.appts, sort_keys=True) == before
    assert e["cancel"].await_count == 0
    assert not out.should_retry


@pytest.mark.asyncio
async def test_V_the_exact_replacement_booking_is_deferred_to_W6A2():
    """D2 names the booking on its operation the moment CreateBooking returns,
    before inserting the local row. That window now has an exact answer."""
    w = World(operations=[{"id": "op-1", "tenant_id": DANI, "state": "in_progress",
                           "replacement_provider_booking_id": BOOKING,
                           "target_provider_location_id": CORK_PID}])
    with env(w):
        out = await run()
    assert out.result == rec.DEFERRED_RESCHEDULE
    assert "op-1" in out.detail
    assert w.inserts == [], "no orphan duplicate for the W6A2 replacement"


@pytest.mark.asyncio
async def test_V_COLLISION_same_tenant_location_and_start_is_NOT_adopted():
    """THE regression this fix exists for.

    Operation A's replacement is BOOKING_A. An unrelated booking BOOKING_B shares
    tenant, location AND start time — differing only in staff/service/customer.
    The old tenant+location+start heuristic would have deferred BOOKING_B as if it
    were A's replacement. Exact provider identity must not.
    """
    w = World(operations=[{"id": "op-A", "tenant_id": DANI, "state": "in_progress",
                           "replacement_provider_booking_id": "BOOKING_A",
                           "target_provider_location_id": CORK_PID,
                           "target_start_at_utc": "2026-10-05T13:00:00Z"}])
    with env(w):
        out = await run(booking_id="BOOKING_B")          # same tenant/location/start
    assert out.result == rec.RECONCILED_CREATED, \
        "an unrelated booking must be mirrored, not swallowed as someone's replacement"
    assert len(w.inserts) == 1
    assert w.inserts[0]["google_event_id"] == "BOOKING_B"


@pytest.mark.asyncio
@pytest.mark.parametrize("differing", ["staff", "service"])
async def test_V_same_start_differing_staff_or_service_is_still_not_adopted(differing):
    w = World(operations=[{"id": "op-A", "tenant_id": DANI, "state": "in_progress",
                           "replacement_provider_booking_id": "BOOKING_A",
                           "target_provider_location_id": CORK_PID,
                           "target_start_at_utc": "2026-10-05T13:00:00Z",
                           "target_team_member_id": "TM1",
                           "target_service_variation_id": "VAR1"}])
    auth = {"id": "BOOKING_B", "status": "ACCEPTED", "version": 0,
            "location_id": CORK_PID, "start_at": "2026-10-05T13:00:00Z",
            "appointment_segments": [{"team_member_id": "TM9" if differing == "staff" else "TM1",
                                      "service_variation_id": "VAR9" if differing == "service" else "VAR1",
                                      "duration_minutes": 60}]}
    with env(w, booking=auth):
        out = await run(booking_id="BOOKING_B")
    assert out.result == rec.RECONCILED_CREATED
    assert w.inserts[0]["google_event_id"] == "BOOKING_B"


@pytest.mark.asyncio
async def test_V_matching_provider_id_but_mismatched_location_fails_closed():
    w = World(operations=[{"id": "op-1", "tenant_id": DANI, "state": "in_progress",
                           "replacement_provider_booking_id": BOOKING,
                           "target_provider_location_id": DUB_PID}])
    with env(w):
        out = await run(location_id=CORK_PID)
    assert out.result == rec.LOCATION_CONFLICT
    assert w.inserts == []


@pytest.mark.asyncio
async def test_V_matching_provider_id_but_another_tenants_operation_fails_closed():
    w = World(operations=[{"id": "op-1", "tenant_id": SHAHID, "state": "in_progress",
                           "replacement_provider_booking_id": BOOKING,
                           "target_provider_location_id": CORK_PID}])
    with env(w):
        out = await run()
    assert out.result == rec.IDENTITY_CONFLICT_OP
    assert w.inserts == []


@pytest.mark.asyncio
async def test_V_replaying_the_matching_provider_id_is_idempotent():
    w = World(operations=[{"id": "op-1", "tenant_id": DANI, "state": "in_progress",
                           "replacement_provider_booking_id": BOOKING,
                           "target_provider_location_id": CORK_PID}])
    with env(w):
        outs = [await run(), await run(), await run()]
    assert {o.result for o in outs} == {rec.DEFERRED_RESCHEDULE}
    assert w.inserts == []


@pytest.mark.asyncio
async def test_V2_once_the_replacement_row_exists_it_is_adopted_not_duplicated():
    w = World([appt("a-repl", version=None)])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 1, "location_id": CORK_PID,
            "start_at": "2026-10-05T13:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        out = await run(version=1)
    assert out.result in (rec.RECONCILED_UPDATED, rec.NOOP_NO_CHANGE)
    assert w.inserts == []
    assert out.appointment_id == "a-repl"


@pytest.mark.asyncio
async def test_V3_a_pre_026_in_progress_operation_defers_mirror_creation():
    """Transitional guard for the deploy window: an operation created before the
    replacement id existed may own a booking it cannot name."""
    w = World(operations=[{"id": "op-old", "tenant_id": DANI, "state": "in_progress",
                           "replacement_provider_booking_id": None}])
    with env(w):
        out = await run()
    assert out.result == rec.DEFERRED_RESCHEDULE
    assert w.inserts == []


@pytest.mark.asyncio
async def test_V4_the_pre_026_check_fails_closed_when_it_errors():
    w = World()
    with env(w), patch("db.reschedule_ops.list_unidentified_in_progress",
                       new=AsyncMock(side_effect=RuntimeError("db down"))):
        out = await run()
    assert out.result == rec.DEFERRED_RESCHEDULE
    assert w.inserts == []


def test_V5_no_tenant_location_start_heuristic_remains():
    """The removed inference must not creep back."""
    code = _executable_source(rec)
    assert "list_live_operations_for_target" not in code
    assert "target_start_at_utc" not in code
    assert "get_operation_by_replacement_booking" in code


# ═══════════════════════════════════════════════════════════════════════════
# W — cancellation mapping, and never a reverse provider mutation
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["CANCELLED_BY_SELLER", "CANCELLED_BY_CUSTOMER",
                                    "DECLINED", "NO_SHOW"])
async def test_W_terminal_provider_statuses_cancel_the_local_row(status):
    w = World([appt(version=0)])
    auth = {"id": BOOKING, "status": status, "version": 1, "location_id": CORK_PID,
            "start_at": "2026-10-05T13:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth) as e:
        out = await run(version=1)
    assert out.result == rec.RECONCILED_UPDATED
    assert w.appts["a-1"]["status"] == "cancelled"
    assert e["cancel"].await_count == 0, "observation must never call CancelBooking"


@pytest.mark.parametrize("status,terminal", [
    ("ACCEPTED", False), ("PENDING", False),
    ("CANCELLED_BY_SELLER", True), ("CANCELLED_BY_CUSTOMER", True),
    ("DECLINED", True), ("NO_SHOW", True), ("", False), (None, False)])
def test_W2_status_mapping_is_explicit(status, terminal):
    assert rec.is_terminal_status(status) is terminal


@pytest.mark.asyncio
async def test_W3_a_cancelled_booking_with_no_local_row_creates_nothing():
    w = World()
    auth = {"id": BOOKING, "status": "CANCELLED_BY_SELLER", "version": 1,
            "location_id": CORK_PID, "start_at": "2026-10-05T13:00:00Z",
            "appointment_segments": [{}]}
    with env(w, booking=auth):
        out = await run(version=1)
    assert out.result == rec.NOOP_NO_CHANGE
    assert w.inserts == []


def test_W4_no_provider_mutation_is_reachable_from_this_module():
    code = _executable_source(rec)
    for forbidden in ("create_booking", "cancel_booking", "CancelBooking",
                      "/v2/bookings", "httpx"):
        assert forbidden not in code, f"webhook path must not reference {forbidden}"


# ═══════════════════════════════════════════════════════════════════════════
# X/Y — event dedupe boundary
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_X_a_duplicate_provider_event_is_idempotent_by_version():
    """Behavioural dedupe is deliberately NOT implemented. Correctness comes from
    the version guard, so a duplicate delivery is harmless regardless."""
    w = World([appt(version=0)])
    auth = {"id": BOOKING, "status": "ACCEPTED", "version": 2, "location_id": CORK_PID,
            "start_at": "2026-10-05T13:00:00Z", "appointment_segments": [{}]}
    with env(w, booking=auth):
        first = await run(version=2)
        second = await run(version=2)
        third = await run(version=2)
    assert first.result == rec.RECONCILED_UPDATED
    assert second.result == third.result == rec.NOOP_STALE
    assert w.appts["a-1"]["provider_version"] == 2


def test_Y_reconciliation_does_not_read_the_ledger_for_routing():
    """W7C found ledger annotations can silently go missing. Routing must never
    depend on them — it resolves in-request."""
    code = _executable_source(rec)
    assert "provider_webhook_events" not in code
    assert "set_shadow_resolution" not in code
    assert "ledger" not in code
    # the resolver is called in-request; its result is never read back from storage
    assert "resolve_square_tenant_location" in code


# ═══════════════════════════════════════════════════════════════════════════
# Z — backwards compatibility
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_Z_single_location_square_tenant_routes_correctly():
    w = World()
    with env(w, merchants=[tenant(DANI)], bindings=[bundle(lid="loc-only")]):
        out = await run()
    assert out.result == rec.RECONCILED_CREATED
    assert out.tenant_location_id == "loc-only"


@pytest.mark.asyncio
async def test_Z2_multi_location_one_tenant_picks_the_right_location():
    w = World()
    with env(w, bindings=[bundle(bid="b-dub", lid=DUB_LOC, pid=DUB_PID)]):
        out = await run(location_id=DUB_PID)
    assert out.tenant_location_id == DUB_LOC


@pytest.mark.asyncio
async def test_Z3_two_tenants_distinct_locations_each_route_correctly():
    w = World()
    with env(w, merchants=[tenant(DANI), tenant(SHAHID)],
             bindings=[bundle(bid="b-sh", tid=SHAHID, lid="loc-sh", pid=DUB_PID)]):
        out = await run(location_id=DUB_PID)
    assert out.tenant_id == SHAHID


@pytest.mark.asyncio
async def test_Z4_no_credential_fails_closed():
    w = World()
    with env(w, token=None):
        out = await run()
    assert out.result == rec.NO_CREDENTIAL
    assert w.inserts == []


def test_Z5_catalog_and_payment_routing_are_untouched():
    import inspect

    from routers import payments
    from services import square_booking
    src = inspect.getsource(payments.square_webhook)
    assert 'case "catalog.version.updated"' in src
    assert "square_booking.handle_catalog_update(event)" in src
    assert '"payment.updated" | "payment.created"' in src
    assert "_handle_square_payment_completed(event)" in src
    # catalog still uses the legacy merchant lookup — documented remaining risk
    assert "get_tenant_by_square_merchant_id" in inspect.getsource(
        square_booking.handle_catalog_update)
    # payments still route by order id
    assert "get_payment_by_checkout_session(order_id)" in inspect.getsource(
        payments._handle_square_payment_completed)


def test_Z6_the_booking_case_now_uses_the_W7_resolver():
    import inspect

    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    assert "square_booking_reconcile.reconcile_booking_event(event)" in src
    assert "square_booking.handle_booking_event(event)" not in src


def test_Z7_a_deliberate_status_reaches_square_unchanged():
    """The 503 for a transient provider read must not be rewritten to a 500."""
    import inspect

    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    assert "except HTTPException:" in src
    assert src.index("except HTTPException:") < src.index("except Exception as e:")
