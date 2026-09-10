"""
W5 — slot binding: what was offered is what gets booked.

Availability and booking used to be two independent derivations from the caller's
words. Booking re-matched the service, re-resolved the staff and re-read the
tenant's location pointer, so nothing tied the times a caller HEARD to the
appointment they GOT. For one location that was survivable; for three it means
hearing Dublin and being booked in Cork.

The cases that matter most are the refusals. A booking that fails loudly costs a
caller thirty seconds; one that succeeds against the wrong city costs them a trip.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools
from services import slot_offers

CORK_PID, DUBLIN_PID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K"
CORK_LOC, DUBLIN_LOC = "loc-cork", "loc-dublin"


def _loc(slug, name, lid, pid, active=True, bookable=True):
    return {"id": lid, "slug": slug, "name": name, "aliases": [], "active": active,
            "booking_enabled": bookable, "timezone": "Europe/Dublin", "is_default": False,
            "_binding": {"tenant_location_id": lid, "provider": "square",
                         "provider_location_id": pid, "provider_status": "ACTIVE",
                         "provider_timezone": "America/Toronto"}}


CORK = _loc("cork", "Cork", CORK_LOC, CORK_PID)
DUBLIN = _loc("dublin", "Dublin", DUBLIN_LOC, DUBLIN_PID)
ADOPTED = [CORK, DUBLIN]
TENANT = {"id": "t-dani", "business_name": "DANI", "square_appointments_enabled": True,
          "square_location_id": CORK_PID, "calendar_timezone": "Europe/Dublin",
          "square_access_token": "enc"}


def _future(minutes=10):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _offer(**over):
    return {"slot_ref": "slot_1", "vapi_call_id": "call-1", "tenant_id": "t-dani",
            "tenant_location_id": CORK_LOC, "provider_location_id": CORK_PID,
            "service_variation_id": "V-FIT", "service_variation_version": 1,
            "service_name": "Dress Fitting", "team_member_id": "TM-1",
            "start_at_utc": "2026-09-14T13:00:00Z", "duration_minutes": 60,
            "expires_at": _future(), "consumed_at": None, "booking_id": None, **over}


def _state(active=CORK_LOC, **over):
    return {"vapi_call_id": "call-1", "tenant_id": "t-dani", "active_location_id": active,
            "initial_location_id": active, "switch_count": 0,
            "location_source": "caller_selected", **over}


# ── resolve_for_booking: the refusals ────────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_offer_resolves():
    with patch("db.locations.get_slot_offer", new=AsyncMock(return_value=_offer())):
        status, offer = await slot_offers.resolve_for_booking(
            vapi_call_id="call-1", slot_ref="slot_1", tenant_id="t-dani",
            active_location_id=CORK_LOC)
    assert status == slot_offers.OK and offer["provider_location_id"] == CORK_PID


@pytest.mark.asyncio
async def test_E_unknown_slot_ref_is_refused():
    with patch("db.locations.get_slot_offer", new=AsyncMock(return_value=None)):
        status, _ = await slot_offers.resolve_for_booking(
            vapi_call_id="call-1", slot_ref="slot_99", tenant_id="t-dani",
            active_location_id=CORK_LOC)
    assert status == slot_offers.NOT_FOUND


@pytest.mark.asyncio
async def test_F_and_G_slot_from_another_call_or_tenant_is_refused():
    """Both are scoped away at the query: the lookup is keyed on call AND tenant,
    so a ref belonging to either is simply not found."""
    lookup = AsyncMock(return_value=None)
    with patch("db.locations.get_slot_offer", new=lookup):
        for call_id, tenant in (("call-OTHER", "t-dani"), ("call-1", "t-OTHER")):
            status, _ = await slot_offers.resolve_for_booking(
                vapi_call_id=call_id, slot_ref="slot_1", tenant_id=tenant,
                active_location_id=CORK_LOC)
            assert status == slot_offers.NOT_FOUND
    assert lookup.await_args_list[0].args[0] == "call-OTHER"
    assert lookup.await_args_list[1].args[2] == "t-OTHER"


@pytest.mark.asyncio
async def test_D_expired_slot_is_refused():
    expired = _offer(expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    with patch("db.locations.get_slot_offer", new=AsyncMock(return_value=expired)):
        status, _ = await slot_offers.resolve_for_booking(
            vapi_call_id="call-1", slot_ref="slot_1", tenant_id="t-dani",
            active_location_id=CORK_LOC)
    assert status == slot_offers.EXPIRED


@pytest.mark.asyncio
async def test_C_cork_slot_cannot_be_booked_while_dublin_is_active():
    """The heart of W5. Checked Cork, switched to Dublin, tried the Cork time."""
    with patch("db.locations.get_slot_offer", new=AsyncMock(return_value=_offer())):
        status, _ = await slot_offers.resolve_for_booking(
            vapi_call_id="call-1", slot_ref="slot_1", tenant_id="t-dani",
            active_location_id=DUBLIN_LOC)
    assert status == slot_offers.WRONG_LOCATION


@pytest.mark.asyncio
async def test_K_consumed_offer_returns_already_booked_not_a_second_booking():
    used = _offer(consumed_at="2026-09-10T18:00:00Z", booking_id="bk-1")
    with patch("db.locations.get_slot_offer", new=AsyncMock(return_value=used)):
        status, offer = await slot_offers.resolve_for_booking(
            vapi_call_id="call-1", slot_ref="slot_1", tenant_id="t-dani",
            active_location_id=CORK_LOC)
    assert status == slot_offers.ALREADY_BOOKED and offer["booking_id"] == "bk-1"


# ── offer minting ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refs_continue_across_a_location_switch():
    """Cork gets slot_1..2; Dublin must not reuse slot_1 — one ref, one meaning."""
    slots = [{"start_at_utc": "2026-09-14T13:00:00Z", "display": "2:00 PM"},
             {"start_at_utc": "2026-09-14T13:30:00Z", "display": "2:30 PM"}]
    with patch("db.locations.count_slot_offers", new=AsyncMock(return_value=2)), \
         patch("db.locations.insert_slot_offers", new=AsyncMock()) as ins:
        rows = await slot_offers.create_offers(
            vapi_call_id="call-1", tenant_id="t-dani", tenant_location_id=DUBLIN_LOC,
            provider_location_id=DUBLIN_PID, service_variation_id="V-CONS",
            service_name="Consultation", slots=slots)
    assert [r["slot_ref"] for r in rows] == ["slot_3", "slot_4"]
    assert all(r["tenant_location_id"] == DUBLIN_LOC for r in ins.await_args.args[0])


@pytest.mark.asyncio
async def test_offers_capture_the_identifiers_booking_will_replay():
    slots = [{"start_at_utc": "2026-09-14T13:00:00Z", "display": "2:00 PM",
              "team_member_id": "TM-9", "service_variation_version": 77,
              "duration_minutes": 45}]
    with patch("db.locations.count_slot_offers", new=AsyncMock(return_value=0)), \
         patch("db.locations.insert_slot_offers", new=AsyncMock()) as ins:
        await slot_offers.create_offers(
            vapi_call_id="call-1", tenant_id="t-dani", tenant_location_id=CORK_LOC,
            provider_location_id=CORK_PID, service_variation_id="V-FIT",
            service_name="Dress Fitting", slots=slots)
    row = ins.await_args.args[0][0]
    assert row["team_member_id"] == "TM-9"
    assert row["service_variation_version"] == 77
    assert row["duration_minutes"] == 45
    assert row["provider_location_id"] == CORK_PID


@pytest.mark.asyncio
async def test_persist_failure_yields_no_offers_rather_than_unbacked_refs():
    with patch("db.locations.count_slot_offers", new=AsyncMock(return_value=0)), \
         patch("db.locations.insert_slot_offers", new=AsyncMock(side_effect=RuntimeError("db"))):
        rows = await slot_offers.create_offers(
            vapi_call_id="call-1", tenant_id="t-dani", tenant_location_id=CORK_LOC,
            provider_location_id=CORK_PID, service_variation_id="V", service_name="X",
            slots=[{"start_at_utc": "2026-09-14T13:00:00Z", "display": "2:00 PM"}])
    assert rows == []


def test_spoken_list_pairs_times_with_refs():
    rows = [{"slot_ref": "slot_1", "display": "2:00 PM"},
            {"slot_ref": "slot_2", "display": "2:30 PM"}]
    assert slot_offers.spoken_offer_list(rows) == "2:00 PM [slot_1], 2:30 PM [slot_2]"


# ── the booking path end to end ──────────────────────────────────────────────

class _Book:
    def __init__(self, offer=None, state=None, adopted=ADOPTED, resolve=True, create=True):
        self.offer = offer if offer is not None else _offer()
        self.state = state or _state()
        self.adopted = adopted
        self.resolve_slot = AsyncMock(return_value=(
            {"team_member_id": "TM-1", "service_variation_version": 1,
             "duration_minutes": 60, "start_at": "2026-09-14T13:00:00Z"} if resolve else None))
        self.create = AsyncMock(return_value={"id": "bk-new", "status": "ACCEPTED"}) if create \
            else AsyncMock(side_effect=RuntimeError("square down"))
        self.consume = AsyncMock()
        self.insert = AsyncMock()

    def __enter__(self):
        self._p = [
            patch("db.locations.get_slot_offer", new=AsyncMock(return_value=self.offer)),
            patch("services.call_location.get_or_create", new=AsyncMock(return_value=self.state)),
            patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")),
            patch("services.square_booking.resolve_slot", new=self.resolve_slot),
            # W6B: the multi-location path resolves the customer through the
            # durable mapping now. Patching the old function left this step
            # unpatched and running against the stubbed Supabase MagicMock, which
            # returned a truthy id and made these tests pass for the wrong reason.
            patch("services.square_booking.resolve_customer",
                  new=AsyncMock(return_value=("ok", "cust-1"))),
            patch("services.square_booking.create_booking", new=self.create),
            # W6A2-prereq: the booking path now CLAIMS the slot before Square.
            patch("db.locations.claim_slot_offer", new=AsyncMock(return_value=True)),
            patch("db.locations.release_slot_offer", new=AsyncMock()),
            patch("db.locations.consume_slot_offer", new=self.consume),
            patch("db.supabase.insert_appointment", new=self.insert),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()

    async def run(self, slot_ref="slot_1"):
        return await tools._multi_location_book(
            "tc-1", "call-1", TENANT, "t-dani", {"slot_ref": slot_ref},
            caller_name="Aoife", caller_phone="+353871234567", adopted=self.adopted)

    def text(self, r):
        return r["results"][0]["result"]


@pytest.mark.asyncio
async def test_A_cork_slot_books_at_cork():
    with _Book() as b:
        res = await b.run()
    assert b.create.await_args.kwargs["location_id"] == CORK_PID
    assert b.create.await_args.kwargs["service_variation_id"] == "V-FIT"
    assert "confirmed" in b.text(res).lower()


@pytest.mark.asyncio
async def test_B_dublin_consultation_books_at_dublin():
    dub = _offer(tenant_location_id=DUBLIN_LOC, provider_location_id=DUBLIN_PID,
                 service_variation_id="V-CONS", service_name="Consultation")
    with _Book(offer=dub, state=_state(active=DUBLIN_LOC)) as b:
        await b.run()
    assert b.create.await_args.kwargs["location_id"] == DUBLIN_PID
    assert b.create.await_args.kwargs["service_variation_id"] == "V-CONS"


@pytest.mark.asyncio
async def test_booking_uses_only_stored_identifiers_never_model_input():
    """The model supplies a ref and nothing else. Square receives ids that came
    from the offer row, not from anything generated."""
    with _Book() as b:
        await b.run()
    kw = b.create.await_args.kwargs
    assert kw["location_id"] == b.offer["provider_location_id"]
    assert kw["service_variation_id"] == b.offer["service_variation_id"]


@pytest.mark.asyncio
async def test_C_wrong_location_slot_creates_nothing():
    with _Book(state=_state(active=DUBLIN_LOC)) as b:
        res = await b.run()
    b.create.assert_not_awaited()
    assert "Cork" in b.text(res) and "Dublin" in b.text(res)


@pytest.mark.asyncio
async def test_H_location_no_longer_bookable_creates_nothing():
    disabled = [_loc("cork", "Cork", CORK_LOC, CORK_PID, bookable=False), DUBLIN]
    with _Book(adopted=disabled) as b:
        res = await b.run()
    b.create.assert_not_awaited()
    assert "isn't taking bookings" in b.text(res)


@pytest.mark.asyncio
async def test_J_slot_gone_from_square_creates_nothing():
    with _Book(resolve=False) as b:
        res = await b.run()
    b.create.assert_not_awaited()
    assert "just been taken" in b.text(res)


@pytest.mark.asyncio
async def test_create_failure_does_not_consume_the_offer():
    """The caller must be able to try the same time again."""
    with _Book(create=False) as b:
        await b.run()
    b.consume.assert_not_awaited()


@pytest.mark.asyncio
async def test_offer_is_consumed_only_after_square_succeeds():
    with _Book() as b:
        await b.run()
    b.consume.assert_awaited_once()
    assert b.consume.await_args.args[2] == "bk-new"


@pytest.mark.asyncio
async def test_K_retry_returns_the_existing_booking_and_creates_no_second_one():
    used = _offer(consumed_at="2026-09-10T18:00:00Z", booking_id="bk-1")
    with _Book(offer=used) as b:
        res = await b.run()
    b.create.assert_not_awaited()
    assert "already booked" in b.text(res).lower()


@pytest.mark.asyncio
async def test_appointment_persists_both_location_identifiers():
    with _Book() as b:
        await b.run()
    row = b.insert.await_args.args[0]
    assert row["tenant_location_id"] == CORK_LOC
    assert row["provider_location_id"] == CORK_PID


@pytest.mark.asyncio
async def test_pending_is_not_reported_as_confirmed():
    with _Book() as b:
        b.create.return_value = {"id": "bk-p", "status": "PENDING"}
        res = await b.run()
    spoken = b.text(res).lower()
    assert "will confirm shortly" in spoken
    assert "do not say it is already confirmed" in spoken


@pytest.mark.asyncio
async def test_missing_slot_ref_creates_nothing():
    with _Book() as b:
        res = await b.run(slot_ref="")
    b.create.assert_not_awaited()
    assert "check availability first" in b.text(res).lower()


# ── reschedule safety (L, M, N) ──────────────────────────────────────────────

def test_L_a_new_booking_never_looks_for_an_appointment_to_cancel():
    """SUPERSEDED by the W6A2 prerequisite, and deliberately made STRICTER.

    W5 asserted that the reschedule lookup was GATED on an explicit flag rather
    than on phone equality. That flag — args.get("reschedule") — was never exposed
    by any tool schema, so the branch could not run, and dead destructive code is
    its own hazard: the next person to add the argument would have shipped
    implicit rescheduling without meaning to. The branch is now gone, so the
    assertion becomes that it cannot exist at all.
    """
    import ast
    import inspect
    code = _executable(tools._square_book_appointment)
    assert "get_active_appointment_by_phone" not in code
    assert "reschedule" not in code
    assert "cancel_booking" not in code


def test_M_a_legacy_square_booking_cancels_nothing_at_all():
    """W5 pinned the ORDER of create-then-cancel. There is no cancel here now, so
    the property to protect is its absence — ordering safety for a real reschedule
    moves to the explicit reschedule tool."""
    import ast
    import inspect
    code = _executable(tools._square_book_appointment)
    calls = [ast.unparse(n.func) for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call)]
    for destructive in ("square_booking.cancel_booking", "square_booking.cancel_booking_detailed",
                        "cal_svc.cancel_event", "ms_cal_svc.cancel_event"):
        assert destructive not in calls, f"legacy booking must not call {destructive}"


def test_legacy_square_booking_only_ever_inserts():
    """The other half: it must not UPDATE an existing appointment row either, which
    is how a booking silently overwrote one the caller still wanted."""
    import ast
    import inspect
    code = _executable(tools._square_book_appointment)
    calls = [ast.unparse(n.func) for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call)]
    assert "db.insert_appointment" in calls
    assert "db.update_appointment" not in calls


def _executable(fn):
    """Source with docstrings stripped — prose about what a function does NOT do
    must not satisfy or fail a guard about what it does."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(fn).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            if node.body and isinstance(node.body[0], ast.Expr) \
                    and isinstance(node.body[0].value, ast.Constant):
                node.body.pop(0)
    return ast.unparse(tree)


# ── caller identity (O) and legacy (P, Q) ────────────────────────────────────

def test_O_trusted_caller_phone_still_beats_a_model_number():
    body = {"message": {"call": {"customer": {"number": "+353871234567"}}}}
    assert tools.trusted_caller_phone(body, {"caller_phone": "+00000000000"}) == "+353871234567"


def test_P_legacy_booking_path_never_sees_slot_binding():
    """Single-location tenants keep the path they have always had."""
    import inspect
    src = inspect.getsource(tools._square_book_appointment)
    for w5 in ("slot_offers", "slot_ref", "provider_location_id", "call_location"):
        assert w5 not in src, f"legacy booking path must stay slot-unaware: {w5}"


def test_Q_legacy_still_reads_the_tenant_pointer():
    """Guards the opposite mistake: W5 must not rip out single-location support."""
    import inspect
    assert "square_location_id" in inspect.getsource(tools._square_book_appointment)


def test_slot_offer_cleanup_is_wired_into_end_of_call_and_retention():
    import inspect
    from routers import webhooks
    from services import retention
    assert "slot_offers" in inspect.getsource(webhooks)
    assert "slot_offers" in inspect.getsource(retention.run_retention)


# ── service context across a location switch (W5 Decision 2) ─────────────────

@pytest.mark.asyncio
async def test_service_context_is_stored_when_explicitly_chosen():
    from services import call_location as cl
    with patch("db.locations.update_call_state", new=AsyncMock()) as upd:
        out = await cl.set_active_service(
            _state(), {"square_variation_id": "V-FIT", "name": "Dress Fitting — Regular"})
    assert out["active_service_variation_id"] == "V-FIT"
    assert upd.await_args.args[2]["active_service_name"] == "Dress Fitting — Regular"


def test_remembered_service_is_used_only_where_it_is_offered():
    """'What about Dublin?' must keep meaning dress fitting — but must return None
    when Dublin does not do it, so the caller is told rather than substituted."""
    from services import call_location as cl
    state = _state(active_service_variation_id="V-FIT", active_service_name="Dress Fitting")
    cork_services = [{"square_variation_id": "V-FIT", "name": "Dress Fitting"},
                     {"square_variation_id": "V-CONS", "name": "Consultation"}]
    dublin_services = [{"square_variation_id": "V-CONS", "name": "Consultation"}]

    assert cl.active_service_from(state, cork_services)["square_variation_id"] == "V-FIT"
    assert cl.active_service_from(state, dublin_services) is None
    assert cl.remembered_service_name(state) == "Dress Fitting"


def test_no_remembered_service_returns_none_rather_than_the_first_one():
    from services import call_location as cl
    assert cl.active_service_from(_state(), [{"square_variation_id": "V-CONS"}]) is None


def test_service_variation_ids_are_never_put_in_a_tool_schema():
    from services import vapi
    import json
    blob = json.dumps(vapi.build_calendar_tools("t1"))
    for leaked in ("variation", "square_variation_id", "provider_location_id"):
        assert leaked not in blob
