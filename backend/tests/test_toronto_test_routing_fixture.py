"""
Square booking-webhook routing for one Square location mapped by several tenants.

ISOLATED FIXTURE: no database, Square or production webhook. The rows are shaped
like production's mappings for merchant ML66K1YVCD1P0's location L0Q8GTAZCHD42 on
2026-11-06 (synthetic ids), and every event runs through the real resolver
(square_webhook_resolution) and the real reconciler (square_booking_reconcile).

  tenant        binding status   linked location          tenant Square bookings
  shahid        never confirmed  active, booking on       off
  open lines    ACTIVE           default, booking on      on
  dani test     ACTIVE (stale)   "Cork", booking on       on      <- the extra eligible one
  dani          ACTIVE           not adopted              on

The proposed fix turns booking off for DANI Test's "Cork" location. These tests
show that, before it, the location is refused as ambiguous; after it, events route
to Open Lines only; a genuinely ambiguous mapping is still refused; and nothing
else — other locations, other appointments — changes.
"""
from services import square_booking_reconcile as rec
from services import square_webhook_resolution as wres
from tests.test_w7d_booking_webhook_cutover import MERCHANT, World, env, envelope, tenant

PID, DUBLIN_PID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K"
OL, DT, DANI, SHAHID = "t-openlines", "t-dani-test", "t-dani", "t-shahid"
OL_LOC, CORK, DUBLIN, SHAHID_LOC = "loc-openlines", "loc-dt-cork", "loc-dt-dublin", "loc-shahid"
BK = "vlvspe2z8ct6zk"


def _bundle(bid, tid, lid, *, pid=PID, status="ACTIVE", appts=True, booking=True):
    return {"binding": {"id": bid, "tenant_id": tid, "tenant_location_id": lid, "provider": "square",
                        "provider_location_id": pid, "provider_status": status},
            "location": ({"id": lid, "tenant_id": tid, "active": True, "booking_enabled": booking}
                         if lid else None),
            "tenant": tenant(tid, appts=appts)}


def toronto(*, cork_booking=True):
    return [_bundle("b-shahid", SHAHID, SHAHID_LOC, status=None, appts=False),
            _bundle("b-ol", OL, OL_LOC),
            _bundle("b-dt-cork", DT, CORK, booking=cork_booking),
            _bundle("b-dani", DANI, None)]


MERCHANTS = [tenant(DANI), tenant(OL), tenant(SHAHID, appts=False), tenant(DT)]


def resolve(bindings, merchants=MERCHANTS, pid=PID):
    return wres.resolve_square_tenant_location(merchant_id=MERCHANT, merchant_candidates=merchants,
                                               provider_location_id=pid, location_bindings=bindings)


def ol_appt(aid="a-test", booking=BK, when="2026-11-11T14:30:00+00:00", version=1):
    return {"id": aid, "tenant_id": OL, "google_event_id": booking, "status": "confirmed",
            "provider_version": version, "appointment_datetime": when, "tenant_location_id": OL_LOC,
            "provider_location_id": PID, "caller_phone": "+16475550100", "service": "Dress Fitting",
            "duration_minutes": 60}


def square_booking(booking=BK, start="2026-11-11T14:30:00Z", version=1):
    return {"id": booking, "status": "ACCEPTED", "version": version, "location_id": PID,
            "start_at": start, "updated_at": "2026-11-06T05:05:44Z",
            "appointment_segments": [{"team_member_id": "TM1", "service_variation_id": "VAR1",
                                      "duration_minutes": 60}]}


# ═════════════════════════════ the resolver ═══════════════════════════════════

def test_today_the_location_is_refused_as_ambiguous():
    r = resolve(toronto())
    assert r.outcome == wres.AMBIGUOUS_BINDING and r.eligible_count == 2 and not r.may_mutate


def test_after_the_fix_it_resolves_to_open_lines_only():
    r = resolve(toronto(cork_booking=False))
    assert r.outcome == wres.RESOLVED and r.may_mutate
    assert (r.tenant_id, r.tenant_location_id, r.binding_id) == (OL, OL_LOC, "b-ol")


def test_a_genuinely_ambiguous_location_is_still_refused():
    """Two healthy tenants both adopt the location: still no guess."""
    both = toronto(cork_booking=False) + [_bundle("b-dani-adopted", DANI, "loc-dani")]
    assert resolve(both).outcome == wres.AMBIGUOUS_BINDING


def test_open_lines_must_still_claim_the_merchant():
    """The fix does not weaken the merchant cross-check."""
    others = [m for m in MERCHANTS if m["id"] != OL]
    assert resolve(toronto(cork_booking=False), merchants=others).outcome == wres.IDENTITY_CONFLICT


def test_the_fix_does_not_touch_other_locations():
    """Each location is judged only by its own mappings. Dublin (inactive in Square)
    still resolves to DANI Test's stale mapping, with or without the Cork change;
    that is a separate, known leftover, not something this fix alters."""
    dublin = [_bundle("b-dt-dublin", DT, DUBLIN, pid=DUBLIN_PID),
              _bundle("b-ol-dublin", OL, None, pid=DUBLIN_PID, status="INACTIVE"),
              _bundle("b-dani-dublin", DANI, None, pid=DUBLIN_PID, status="INACTIVE")]
    assert all(b["binding"]["provider_location_id"] != PID for b in dublin)
    r = resolve(dublin, pid=DUBLIN_PID)
    assert (r.outcome, r.tenant_id) == (wres.RESOLVED, DT)


# ═══════════════════ end to end through the reconciler ════════════════════════

async def test_today_a_booking_update_changes_nothing_and_is_not_retried():
    w = World([ol_appt(when="2026-11-09T14:00:00+00:00", version=0)])
    with env(w, merchants=MERCHANTS, bindings=toronto(), booking=square_booking()):
        out = await rec.reconcile_booking_event(envelope(etype="booking.updated", location_id=PID,
                                                         booking_id=BK, version=1))
    assert out.result == wres.AMBIGUOUS_BINDING and not out.should_retry
    assert w.appts["a-test"]["appointment_datetime"] == "2026-11-09T14:00:00+00:00", "nothing written"


async def test_after_the_fix_a_square_side_change_reaches_the_open_lines_row_only():
    w = World([ol_appt(version=1), ol_appt("a-other", booking="bk-other", when="2026-11-02T15:00:00+00:00")])
    other_before = dict(w.appts["a-other"])
    moved = square_booking(start="2026-11-12T15:00:00Z", version=2)
    with env(w, merchants=MERCHANTS, bindings=toronto(cork_booking=False), booking=moved) as calls:
        out = await rec.reconcile_booking_event(envelope(etype="booking.updated", location_id=PID,
                                                         booking_id=BK, version=2))
    assert out.result == rec.RECONCILED_UPDATED and out.tenant_id == OL
    assert w.appts["a-test"]["appointment_datetime"] == "2026-11-12T15:00:00Z"
    assert w.appts["a-test"]["provider_version"] == 2
    assert w.appts["a-other"] == other_before, "no other appointment is touched"
    assert not calls["create"].called and not calls["cancel"].called, "Square is only read"


async def test_after_the_fix_a_replayed_or_stale_event_is_a_no_op():
    w = World([ol_appt(version=1)])
    with env(w, merchants=MERCHANTS, bindings=toronto(cork_booking=False), booking=square_booking()):
        out = await rec.reconcile_booking_event(envelope(etype="booking.updated", location_id=PID,
                                                         booking_id=BK, version=1))
    assert out.result in (rec.NOOP_NO_CHANGE, rec.NOOP_STALE)
    assert w.appts["a-test"]["appointment_datetime"] == "2026-11-11T14:30:00+00:00"


async def test_after_the_fix_a_booking_made_in_square_is_mirrored_under_open_lines():
    """The one behaviour that starts once events route: a booking created
    directly in Square at Toronto Test gets an Open Lines appointment row."""
    w = World([])
    with env(w, merchants=MERCHANTS, bindings=toronto(cork_booking=False),
             booking=square_booking(booking="bk-new", start="2026-11-20T15:00:00Z", version=0)):
        out = await rec.reconcile_booking_event(envelope(etype="booking.created", location_id=PID,
                                                         booking_id="bk-new", version=0))
    assert out.result == rec.RECONCILED_CREATED and len(w.inserts) == 1
    assert w.inserts[0]["tenant_id"] == OL and w.inserts[0]["tenant_location_id"] == OL_LOC
