"""
W7B — see what Square actually delivers, and change nothing while looking.

Three questions have no answer today: what does Square send, how often does it
send the same thing twice, and where would W7A route it? Square events are
processed inline and never persisted, so there is no ledger, no delivery count
and no dead letter.

THE TEST THAT MATTERS MOST IS THE ONE THAT PROVES NOTHING CHANGED.
A duplicate delivery is counted and then dispatched exactly as before. It is
tempting to short-circuit it -- that is what the ledger makes possible -- but
"persist, dedupe and change nothing" is a contradiction, and the handler dedupe
would protect is the same one W7D replaces. So the duplicate still runs, and a
test pins that it does.

The second theme is that observability must never be able to break payments. A
ledger outage degrades to "we lost the evidence", never to a 500 that makes
Square retry a payment webhook for a day.
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from services import square_webhook_observability as obs
from services import square_webhook_resolution as r

MERCHANT = "ML66K1YVCD1P0"
CORK_PID, DUBLIN_PID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K"
DANI, SHAHID = "tenant-dani", "tenant-shahid"
EVENT_ID = "evt-0001"


# ── envelope builders ───────────────────────────────────────────────────────

def booking_envelope(*, event_id=EVENT_ID, etype="booking.created",
                     location_id=CORK_PID, version=3, status="ACCEPTED",
                     merchant=MERCHANT, booking_id="bk-1", omit_location=False):
    booking = {"id": booking_id, "status": status, "version": version,
               "start_at": "2026-11-08T13:00:00Z",
               "updated_at": "2026-09-11T12:00:00Z",
               "customer_id": "SQCUST-1",
               "appointment_segments": [{"team_member_id": "TM1",
                                         "service_variation_id": "VAR1",
                                         "service_variation_version": 1789040442821,
                                         "duration_minutes": 60}]}
    if not omit_location:
        booking["location_id"] = location_id
    return {"event_id": event_id, "type": etype, "merchant_id": merchant,
            "created_at": "2026-09-11T12:00:00Z",
            "data": {"type": "booking", "id": booking_id, "object": {"booking": booking}}}


def payment_envelope(event_id="evt-pay", order_id="ord-1"):
    return {"event_id": event_id, "type": "payment.updated", "merchant_id": MERCHANT,
            "data": {"type": "payment", "id": "pay-1", "object": {"payment": {
                "id": "pay-1", "order_id": order_id, "status": "COMPLETED",
                "location_id": CORK_PID, "updated_at": "2026-09-11T12:00:00Z"}}}}


def unknown_envelope(event_id="evt-unk", etype="team_member.updated"):
    return {"event_id": event_id, "type": etype, "merchant_id": MERCHANT,
            "data": {"type": "team_member", "id": "TM1",
                     "object": {"team_member": {"id": "TM1", "status": "ACTIVE"}}}}


# ── a faithful in-memory ledger (the real ON CONFLICT semantics) ────────────

class Ledger:
    """Mirrors migration 024's record_provider_webhook_event(): one row per
    (provider, event_id), atomic increment on repeat, first delivery's metadata
    left untouched."""

    def __init__(self):
        self.rows: dict[tuple, dict] = {}
        self.lock = asyncio.Lock()
        self.fail = False
        self._n = 0

    async def record_delivery(self, *, provider, provider_event_id, event_type,
                              raw_envelope=None, **meta):
        if self.fail:
            raise RuntimeError("ledger is down")
        async with self.lock:
            key = (provider, provider_event_id)
            if key in self.rows:
                row = self.rows[key]
                row["delivery_count"] += 1
                row["last_received_at"] = "later"
                return dict(row)
            self._n += 1
            row = {"id": f"row-{self._n}", "provider": provider,
                   "provider_event_id": provider_event_id, "event_type": event_type,
                   "delivery_count": 1, "raw_envelope": raw_envelope,
                   "resolution": None, "resolved_tenant_id": None,
                   "resolved_tenant_location_id": None, "legacy_result": None,
                   "last_error": None, **meta}
            self.rows[key] = row
            return dict(row)

    async def set_shadow_resolution(self, row_id, **kw):
        for row in self.rows.values():
            if row["id"] == row_id:
                row.update(kw)

    async def set_legacy_result(self, row_id, result, error=""):
        for row in self.rows.values():
            if row["id"] == row_id:
                row["legacy_result"] = result
                row["last_error"] = error or None

    def only(self):
        assert len(self.rows) == 1, f"expected one row, got {len(self.rows)}"
        return next(iter(self.rows.values()))


def tenant(tid, *, appts=True, merchant=MERCHANT):
    return {"id": tid, "square_appointments_enabled": appts,
            "square_merchant_id": merchant}


def bundle(*, bid="b1", tid=DANI, lid="loc-cork", pid=CORK_PID, status="ACTIVE",
           appts=True):
    return {"binding": {"id": bid, "tenant_id": tid, "tenant_location_id": lid,
                        "provider": "square", "provider_location_id": pid,
                        "provider_status": status},
            "location": {"id": lid, "tenant_id": tid, "active": True,
                         "booking_enabled": True},
            "tenant": tenant(tid, appts=appts)}


import contextlib


@contextlib.contextmanager
def env(ledger, *, merchants=None, bindings=None):
    with patch.multiple("db.provider_webhook_events",
                        record_delivery=AsyncMock(side_effect=ledger.record_delivery),
                        set_shadow_resolution=AsyncMock(side_effect=ledger.set_shadow_resolution),
                        set_legacy_result=AsyncMock(side_effect=ledger.set_legacy_result)), \
         patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=list(merchants if merchants is not None else [tenant(DANI)]))), \
         patch("db.square_routing.load_location_candidates",
               new=AsyncMock(return_value=list(bindings if bindings is not None else [bundle()]))):
        yield


# ═══════════════════════════════════════════════════════════════════════════
# §6 — extraction
# ═══════════════════════════════════════════════════════════════════════════

def test_booking_created_metadata_is_extracted():
    m = obs.extract(booking_envelope())
    assert m["provider_event_id"] == EVENT_ID
    assert m["event_type"] == "booking.created"
    assert m["merchant_id"] == MERCHANT
    assert m["object_type"] == "booking"
    assert m["object_id"] == "bk-1"
    assert m["provider_location_id"] == CORK_PID
    assert m["provider_version"] == 3
    assert m["provider_status"] == "ACCEPTED"
    assert m["provider_updated_at"] == "2026-09-11T12:00:00Z"


def test_booking_updated_is_extracted_the_same_way():
    m = obs.extract(booking_envelope(etype="booking.updated", version=9))
    assert m["event_type"] == "booking.updated"
    assert m["provider_version"] == 9


def test_a_booking_without_location_extracts_an_empty_location():
    m = obs.extract(booking_envelope(omit_location=True))
    assert m["provider_location_id"] == ""
    assert m["object_id"] == "bk-1"          # still observable


def test_payment_and_unknown_families_are_extracted_not_dropped():
    p = obs.extract(payment_envelope())
    assert (p["event_type"], p["object_id"], p["provider_location_id"]) == \
           ("payment.updated", "pay-1", CORK_PID)
    u = obs.extract(unknown_envelope())
    assert u["event_type"] == "team_member.updated"
    assert u["object_type"] == "team_member" and u["object_id"] == "TM1"


def test_extraction_is_total_and_never_raises():
    for junk in ({}, {"type": "x"}, {"data": None}, {"data": {"object": None}},
                 {"data": {"object": {"booking": "not-a-dict"}}},
                 {"data": {"object": {"booking": {"version": "nope"}}}}):
        m = obs.extract(junk)
        assert set(m) >= {"provider_event_id", "event_type", "provider_location_id"}
    assert obs.extract({"data": {"object": {"booking": {"version": "nope"}}}})[
        "provider_version"] is None


def test_extraction_carries_no_contact_details():
    blob = json.dumps(obs.extract(booking_envelope()))
    for leak in ("phone", "given_name", "family_name", "email", "customer_note"):
        assert leak not in blob.lower()


# ═══════════════════════════════════════════════════════════════════════════
# §7 — shadow resolution
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_merchant_mapped_and_binding_matching_resolves():
    led = Ledger()
    with env(led):
        await obs.observe(booking_envelope())
    row = led.only()
    assert row["resolution"] == r.RESOLVED
    assert row["resolved_tenant_id"] == DANI
    assert row["resolved_tenant_location_id"] == "loc-cork"


@pytest.mark.asyncio
async def test_empty_local_merchant_set_resolves_transitionally():
    led = Ledger()
    with env(led, merchants=[]):
        await obs.observe(booking_envelope())
    row = led.only()
    assert row["resolution"] == r.RESOLVED
    assert row["merchant_status"] == r.MERCHANT_UNMAPPED


@pytest.mark.asyncio
async def test_merchant_candidate_conflict_is_recorded_without_a_tenant():
    led = Ledger()
    with env(led, merchants=[tenant(SHAHID)]):
        await obs.observe(booking_envelope())
    row = led.only()
    assert row["resolution"] == r.IDENTITY_CONFLICT
    assert not row["resolved_tenant_id"]
    assert not row["resolved_tenant_location_id"]


@pytest.mark.asyncio
async def test_two_eligible_bindings_record_ambiguous_and_name_nobody():
    led = Ledger()
    with env(led, merchants=[tenant(DANI), tenant(SHAHID)],
             bindings=[bundle(), bundle(bid="b2", tid=SHAHID, lid="loc-sh")]):
        await obs.observe(booking_envelope())
    row = led.only()
    assert row["resolution"] == r.AMBIGUOUS_BINDING
    assert not row["resolved_tenant_id"]


@pytest.mark.asyncio
async def test_a_booking_without_location_shadows_unknown_location():
    led = Ledger()
    with env(led):
        await obs.observe(booking_envelope(omit_location=True))
    assert led.only()["resolution"] == r.UNKNOWN_LOCATION


@pytest.mark.asyncio
async def test_null_provider_status_is_excluded_and_shadows_inactive():
    led = Ledger()
    with env(led, bindings=[bundle(status=None)]):
        await obs.observe(booking_envelope())
    assert led.only()["resolution"] == r.INACTIVE_BINDING


@pytest.mark.asyncio
async def test_todays_production_topology_shadows_identity_conflict():
    """DANI Cork is the only eligible binding, but only Shahid records the
    merchant. This is the evidence W7B exists to collect — not a failure."""
    led = Ledger()
    with env(led, merchants=[tenant(SHAHID)],
             bindings=[bundle(bid="b-shahid", tid=SHAHID, lid="loc-shahid",
                              status=None, appts=False),
                       bundle(bid="b-dani", tid=DANI, lid="loc-cork")]):
        await obs.observe(booking_envelope())
    assert led.only()["resolution"] == r.IDENTITY_CONFLICT


@pytest.mark.asyncio
async def test_non_booking_events_are_recorded_but_not_shadow_resolved():
    led = Ledger()
    with env(led):
        await obs.observe(payment_envelope())
        await obs.observe(unknown_envelope())
    assert len(led.rows) == 2
    for row in led.rows.values():
        assert row["resolution"] is None


# ═══════════════════════════════════════════════════════════════════════════
# §5 + §11 — duplicates are COUNTED, never suppressed
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_duplicate_event_id_increments_rather_than_duplicating():
    led = Ledger()
    with env(led):
        for _ in range(4):
            await obs.observe(booking_envelope())
    assert len(led.rows) == 1
    assert led.only()["delivery_count"] == 4


@pytest.mark.asyncio
async def test_ten_concurrent_deliveries_make_one_row_with_count_ten():
    led = Ledger()
    with env(led):
        await asyncio.gather(*(obs.observe(booking_envelope()) for _ in range(10)))
    assert len(led.rows) == 1
    assert led.only()["delivery_count"] == 10


@pytest.mark.asyncio
async def test_a_repeat_delivery_keeps_the_first_deliverys_metadata():
    led = Ledger()
    with env(led):
        await obs.observe(booking_envelope(version=3))
        await obs.observe(booking_envelope(version=99))     # same event_id
    row = led.only()
    assert row["delivery_count"] == 2
    assert row["provider_version"] == 3, "a repeat must not rewrite the evidence"


def test_short_circuit_dedupe_is_deliberately_deferred():
    """Pinned so nobody 'finishes' dedupe here by accident: the handler it would
    protect is the same one W7D replaces."""
    import inspect
    src = inspect.getsource(obs)
    assert "NOT suppressed" in src
    assert "not deduplication" in src.lower()
    # observe() must never signal 'skip' to its caller
    assert "return None" in src            # only for 'nothing recorded'
    assert "skip" not in inspect.getsource(obs.observe).lower()


# ═══════════════════════════════════════════════════════════════════════════
# §4 + §10 — the endpoint: HTTP semantics and fail-open
# ═══════════════════════════════════════════════════════════════════════════

class _Req:
    def __init__(self, body: bytes):
        self._b = body
        self.headers = {"x-square-hmacsha256-signature": "sig"}
        self.client = type("c", (), {"host": "127.0.0.1"})()

    async def body(self):
        return self._b


@contextlib.contextmanager
def endpoint(ledger, *, good_sig=True, handler=None, merchants=None, bindings=None):
    from services import square_booking_reconcile as rec
    from services import square_service as sq_svc

    # W7D moved booking dispatch from square_booking.handle_booking_event to the
    # location-aware reconciler. These tests are about the LEDGER, not about which
    # handler runs, so they follow the dispatch target.
    h = handler or AsyncMock(return_value=rec.Outcome(rec.RECONCILED_CREATED))
    with patch.object(sq_svc, "SQUARE_WEBHOOK_SIGNATURE_KEY", "key"), \
         patch.object(sq_svc, "verify_webhook", return_value=good_sig), \
         patch("services.square_booking_reconcile.reconcile_booking_event", new=h), \
         patch("services.square_booking.handle_catalog_update", new=AsyncMock()), \
         env(ledger, merchants=merchants, bindings=bindings):
        yield h


async def call_endpoint(body):
    from fastapi import HTTPException

    from routers import payments
    try:
        return await payments.square_webhook(_Req(json.dumps(body).encode())), None
    except HTTPException as e:
        return None, e


@pytest.mark.asyncio
async def test_a_normal_booking_event_is_recorded_and_dispatched():
    led = Ledger()
    with endpoint(led) as handler:
        res, err = await call_endpoint(booking_envelope())
    assert err is None and res == {"status": "ok"}
    assert handler.await_count == 1
    assert led.only()["legacy_result"] == "reconciled_created"


@pytest.mark.asyncio
async def test_a_duplicate_delivery_still_invokes_the_legacy_handler():
    """The whole point of W7B: observe, do not suppress."""
    led = Ledger()
    with endpoint(led) as handler:
        for _ in range(3):
            res, err = await call_endpoint(booking_envelope())
            assert err is None and res == {"status": "ok"}
    assert handler.await_count == 3, "W7B must NOT deduplicate behaviour yet"
    assert led.only()["delivery_count"] == 3


@pytest.mark.asyncio
async def test_a_ledger_outage_does_not_break_the_webhook():
    led = Ledger()
    led.fail = True
    with endpoint(led) as handler:
        res, err = await call_endpoint(booking_envelope())
    assert err is None and res == {"status": "ok"}
    assert handler.await_count == 1, "legacy processing must survive a ledger outage"
    assert led.rows == {}


@pytest.mark.asyncio
async def test_a_shadow_resolution_failure_does_not_break_the_webhook():
    led = Ledger()
    with endpoint(led) as handler, \
         patch("db.square_routing.load_location_candidates",
               new=AsyncMock(side_effect=RuntimeError("db down"))):
        res, err = await call_endpoint(booking_envelope())
    assert err is None and res == {"status": "ok"}
    assert handler.await_count == 1


@pytest.mark.asyncio
async def test_a_legacy_handler_failure_still_returns_500_for_square_to_retry():
    led = Ledger()
    boom = AsyncMock(side_effect=RuntimeError("handler exploded"))
    with endpoint(led, handler=boom):
        res, err = await call_endpoint(booking_envelope())
    assert res is None and err is not None and err.status_code == 500
    assert led.only()["legacy_result"] == obs.LEGACY_ERROR
    assert "exploded" in (led.only()["last_error"] or "")


@pytest.mark.asyncio
async def test_an_invalid_signature_persists_nothing():
    led = Ledger()
    with endpoint(led, good_sig=False) as handler:
        res, err = await call_endpoint(booking_envelope())
    assert err is not None and err.status_code == 400
    assert handler.await_count == 0
    assert led.rows == {}, "nothing may be recorded before the signature is verified"


@pytest.mark.asyncio
async def test_invalid_json_preserves_the_existing_400():
    from fastapi import HTTPException

    from routers import payments
    led = Ledger()
    with endpoint(led):
        with pytest.raises(HTTPException) as e:
            await payments.square_webhook(_Req(b"{not json"))
    assert e.value.status_code == 400
    assert led.rows == {}


@pytest.mark.asyncio
async def test_an_unhandled_event_type_still_returns_200_and_is_recorded():
    led = Ledger()
    with endpoint(led) as handler:
        res, err = await call_endpoint(unknown_envelope())
    assert err is None and res == {"status": "ok"}
    assert handler.await_count == 0
    assert led.only()["legacy_result"] == obs.LEGACY_UNHANDLED


@pytest.mark.asyncio
async def test_an_event_without_an_event_id_is_skipped_not_fatal():
    led = Ledger()
    body = booking_envelope()
    body.pop("event_id")
    with endpoint(led) as handler:
        res, err = await call_endpoint(body)
    assert err is None and res == {"status": "ok"}
    assert handler.await_count == 1
    assert led.rows == {}


# ═══════════════════════════════════════════════════════════════════════════
# §3 — raw envelope capture is off by default and narrow
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_raw_capture_is_off_by_default():
    led = Ledger()
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("SQUARE_WEBHOOK_CAPTURE_RAW", None)
        with env(led):
            await obs.observe(booking_envelope())
    assert led.only()["raw_envelope"] is None


@pytest.mark.asyncio
async def test_raw_capture_when_enabled_covers_booking_events_only():
    led = Ledger()
    with patch.dict("os.environ", {"SQUARE_WEBHOOK_CAPTURE_RAW": "true"}):
        with env(led):
            await obs.observe(booking_envelope())
            await obs.observe(payment_envelope())
    rows = {r_["event_type"]: r_ for r_ in led.rows.values()}
    assert rows["booking.created"]["raw_envelope"] is not None
    assert rows["payment.updated"]["raw_envelope"] is None, \
        "payment envelopes are never captured raw"


@pytest.mark.parametrize("val,on", [("1", True), ("true", True), ("YES", True),
                                    ("on", True), ("0", False), ("", False),
                                    ("false", False)])
def test_raw_capture_flag_parsing(val, on):
    with patch.dict("os.environ", {"SQUARE_WEBHOOK_CAPTURE_RAW": val}):
        assert obs.capture_raw_enabled() is on


# ═══════════════════════════════════════════════════════════════════════════
# §12 — nothing sensitive lands in the ledger
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_ledger_row_holds_no_token_or_contact_details():
    led = Ledger()
    with env(led):
        await obs.observe(booking_envelope())
    blob = json.dumps(led.only(), default=str).lower()
    for leak in ("access_token", "square_access_token", "refresh_token",
                 "phone", "given_name", "family_name", "email"):
        assert leak not in blob


# ═══════════════════════════════════════════════════════════════════════════
# §16 — zero behaviour change
# ═══════════════════════════════════════════════════════════════════════════

def test_the_dispatch_table_is_intact_after_the_W7D_cutover():
    """W7D replaced the BOOKING arm only. Payments and catalog are untouched."""
    import inspect

    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    for case in ('"payment.updated" | "payment.created"',
                 '"booking.created" | "booking.updated"',
                 '"catalog.version.updated"'):
        assert case in src
    assert "_handle_square_payment_completed(event)" in src
    # W7E replaced the catalog arm's single-tenant .limit(1) lookup with
    # all-candidate routing. Payments are still untouched.
    assert "_w7e.route_catalog_event(event)" in src
    assert "square_booking.handle_catalog_update(event)" not in src
    # booking now routes through the location-aware reconciler. W7D.1 added the
    # resolve-once hand-off, so the call carries the shared Resolution.
    assert "square_booking_reconcile.reconcile_booking_event(" in src
    assert "resolution=_resolution" in src
    assert "square_booking.handle_booking_event(event)" not in src


def test_the_observation_does_not_choose_what_the_handler_mutates():
    """The LEDGER ROW never influences routing. Restated structurally for W7D.1.

    Until W7D.1 this was a string check -- "resolution" must not appear in the
    endpoint at all -- which worked only because the endpoint held no routing
    value of any kind. Resolve-once changes that: the endpoint now computes ONE
    in-memory Resolution and hands it to both consumers, so the literal appears
    and the old check would fail for a reason that has nothing to do with the
    invariant.

    The invariant itself is unchanged and is now asserted directly: whatever
    the endpoint routes on must NOT come from _observation. So every use of
    _observation is enumerated, and each one must be a bare argument handed to
    the telemetry recorder -- never subscripted, never attribute-accessed,
    never branched on, never assigned from.
    """
    import ast
    import inspect

    from routers import payments
    tree = ast.parse(inspect.getsource(payments.square_webhook).lstrip())
    code = ast.unparse(tree)

    # 1. the ledger row is never read, only passed on
    reads = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "_observation":
            reads.append(f"subscript {ast.unparse(node)}")
        if isinstance(node, ast.Attribute) and ast.unparse(node.value) == "_observation":
            reads.append(f"attribute {ast.unparse(node)}")
        if isinstance(node, (ast.If, ast.While)) and "_observation" in ast.unparse(node.test):
            reads.append(f"branch on {ast.unparse(node.test)}")
    assert not reads, f"the endpoint reads the ledger row: {reads}"

    # 2. every _observation use is an argument to record_legacy_result
    passed, other = 0, []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if any(isinstance(a, ast.Name) and a.id == "_observation" for a in node.args):
                if "record_legacy_result" in ast.unparse(node.func):
                    passed += 1
                else:
                    other.append(ast.unparse(node.func))
    assert passed >= 1, "the observation is never recorded against"
    assert not other, f"_observation handed to something other than telemetry: {other}"

    # 3. no ledger COLUMN is read anywhere in the endpoint
    for column in ("resolved_tenant", "resolution_detail", "shadow_resolution",
                   "merchant_status", "delivery_count"):
        assert column not in code, f"the endpoint reads the ledger column {column!r}"

    # 4. what the endpoint DOES route on comes from the resolver, not the ledger
    assert "_w7id.resolve_event(event)" in code
    assert "_resolution = await" in code
    # and there is no early return keyed on a duplicate
    assert "delivery_count" not in code


def test_booking_and_catalog_handlers_still_use_the_legacy_lookup():
    import inspect

    from services import square_booking
    for fn in (square_booking.handle_booking_event, square_booking.handle_catalog_update):
        src = inspect.getsource(fn)
        assert "get_tenant_by_square_merchant_id" in src
        assert "square_webhook_resolution" not in src
        assert "square_webhook_observability" not in src


def test_payment_routing_is_still_order_based():
    import inspect

    from routers import payments
    src = inspect.getsource(payments._handle_square_payment_completed)
    assert "get_payment_by_checkout_session(order_id)" in src
    assert "get_tenant_by_square_merchant_id" not in src
    refund = inspect.getsource(payments._handle_square_refund)
    assert "get_payment_by_checkout_session(order_id)" in refund


def test_w7b_adds_no_provider_call_and_no_token_selection():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(obs))
    code = ast.unparse(tree)
    for forbidden in ("get_access_token", "square_access_token", "httpx",
                      "connect.squareup.com", "create_booking", "cancel_booking"):
        assert forbidden not in code


def test_the_observability_module_never_raises_out_of_observe():
    """Every failure path inside observe() is caught; the endpoint relies on it."""
    import inspect
    src = inspect.getsource(obs.observe)
    assert src.count("try:") >= 3
    assert "except Exception" in src
