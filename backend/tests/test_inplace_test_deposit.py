"""
Issue #179 production validation — the one CAD $1 test deposit (MOCKED: no Square,
Twilio or database calls; tests/conftest.py fakes the inplace_test_runs table).

Workspace deposits stay off. A Square Appointments booking gets a deposit link
only for the configured caller (telephony metadata), on the configured workspace
and location, inside the validation window, reading out a code an operator has
ARMED — and only once. Everyone else books exactly as today.
"""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools
from services import customer_identity, square_inplace_scope as scope
from services import vapi as vapi_svc

TID, LOC = "b63c3f48-0000-0000-0000-000000000001", "L0Q8GTAZCHD42"
ME, DEMO = "+16475550100", "+14165550123"
CODE = "482917305146"                      # 12 digits, the minimum
HASH = hashlib.sha256(CODE.encode()).hexdigest()


def open_window(monkeypatch, *, tenant=TID, location=LOC, phone=ME, hours=6):
    monkeypatch.setenv("SQUARE_INPLACE_TEST_TENANT_ID", tenant)
    monkeypatch.setenv("SQUARE_INPLACE_TEST_LOCATION_ID", location)
    monkeypatch.setenv("SQUARE_INPLACE_TEST_CALLER_PHONE", phone)
    monkeypatch.setenv("SQUARE_INPLACE_TEST_EXPIRES_AT",
                       (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat())


class Shop:
    """The Open Lines workspace on Square, with workspace deposits OFF."""

    def __init__(self):
        self.tenant = {"id": TID, "business_name": "Open Lines", "square_appointments_enabled": True,
                       "square_location_id": LOC, "square_location_timezone": "America/Toronto",
                       "square_currency": "cad", "square_access_token": "enc", "square_deposits_enabled": False,
                       "stripe_deposits_enabled": False, "stripe_deposit_cents": 2500,
                       "twilio_subaccount_sid": "AC", "twilio_auth_token": "t",
                       "twilio_phone_number": "+14388393907"}
        self.bookings, self.appts, self.payments, self.links, self.texts = [], [], [], [], []

    async def create_booking(self, token, **k):
        await asyncio.sleep(0)
        self.bookings.append(k)
        return {"id": f"BK-{len(self.bookings)}", "status": "ACCEPTED"}

    async def insert_appointment(self, data):
        self.appts.append(data)
        return {"id": f"appt-{len(self.appts)}", **data}

    async def payment_link(self, **k):
        await asyncio.sleep(0)
        self.links.append(k)
        return f"LINK-{len(self.links)}", f"ORDER-{len(self.links)}", "https://square.link/u/x"

    async def insert_payment(self, row):
        self.payments.append(row)

    async def send_sms(self, **k):
        self.texts.append(k["body"])
        return True

    def env(self):
        ps = [
            patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")),
            patch("db.supabase.get_square_services", new=AsyncMock(return_value=[{
                "name": "Dress Fitting — Regular", "square_variation_id": "VAR", "duration_minutes": 60,
                "team_member_ids": ["TM"], "variation_version": 1}])),
            patch("db.supabase.get_square_staff", new=AsyncMock(return_value=[
                {"square_team_member_id": "TM", "display_name": "Muaz"}])),
            patch("services.square_booking.resolve_slot", new=AsyncMock(return_value={
                "team_member_id": "TM", "start_at": "2026-11-10T15:00:00Z", "duration_minutes": 60,
                "service_variation_version": 1})),
            patch("services.square_booking.resolve_customer",
                  new=AsyncMock(return_value=(customer_identity.OK, "C-1"))),
            patch("services.square_booking.create_booking", new=AsyncMock(side_effect=self.create_booking)),
            patch("db.supabase.insert_appointment", new=AsyncMock(side_effect=self.insert_appointment)),
            patch("db.supabase.get_appointment_by_id",
                  new=AsyncMock(side_effect=lambda aid: {"id": aid, "provider_location_id": None})),
            patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(return_value=None)),
            patch("db.supabase.insert_payment", new=AsyncMock(side_effect=self.insert_payment)),
            patch("db.supabase.update_tenant", new=AsyncMock()),
            patch("db.supabase.get_payment_short_link_by_code", new=AsyncMock(return_value=None)),
            patch("db.supabase.create_payment_short_link", new=AsyncMock(return_value={})),
            patch("routers.tools._resolve_square_deposit_location",
                  new=AsyncMock(return_value=(LOC, "configured"))),
            patch("services.square_service.create_payment_link", new=AsyncMock(side_effect=self.payment_link)),
            patch("services.security.decrypt", new=lambda v: "tok"),
            patch("services.telephony.send_sms", new=AsyncMock(side_effect=self.send_sms)),
            patch("services.analytics.capture"),
        ]
        shop = self

        class _Ctx:
            def __enter__(s):
                for p in ps:
                    p.start()
                return shop

            def __exit__(s, *a):
                for p in ps:
                    p.stop()
        return _Ctx()

    async def book(self, *, phone=ME, code=CODE, call="call-1"):
        args = {"service": "Dress Fitting"}
        if code is not None:
            args["test_code"] = code
        res = await tools._square_book_appointment(
            "tc", call, self.tenant, TID, args, caller_name="Muaz", caller_phone=phone,
            service="Dress Fitting", date_str="2026-11-10", time_str="10:00", party_size=1,
            metadata_phone=phone)
        return res["results"][0]["result"]


def deposit_texts(shop):
    return [t for t in shop.texts if "deposit" in t]


# ════════════════════════ the one test deposit ════════════════════════════════

async def test_the_test_caller_with_the_code_gets_one_cad_1_link(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    with Shop().env() as shop:
        said = await shop.book()
    assert len(shop.links) == 1 and shop.links[0]["amount_cents"] == 100
    assert shop.links[0]["currency"] == "cad" and shop.links[0]["location_id"] == LOC
    assert len(shop.payments) == 1 and shop.payments[0]["amount_cents"] == 100
    assert shop.payments[0]["appointment_id"] == "appt-1" and shop.payments[0]["provider"] == "square"
    assert len(deposit_texts(shop)) == 1 and shop.texts[0].startswith("Hi Muaz! Your Dress Fitting")
    assert "CAD $1 test deposit link has been texted" in said
    run = inplace_runs_store.rows[HASH]
    assert run["appointment_id"] == "appt-1" and run["payment_id"] == shop.payments[0]["id"]


def test_the_amount_is_fixed_at_one_dollar():
    assert scope.TEST_DEPOSIT_CENTS == 100 and scope.TEST_DEPOSIT_CURRENCY == "cad"


# ════════════════════ everyone else books exactly as today ════════════════════

async def _ordinary(shop, **k):
    said = await shop.book(**k)
    assert shop.links == [] and shop.payments == [] and deposit_texts(shop) == []
    assert said.startswith("Done!") and "test deposit" not in said
    assert len(shop.bookings) == 1 and len(shop.appts) == 1
    return said


@pytest.mark.parametrize("case", [
    "ordinary demo caller", "demo caller who says the code", "test caller without a code",
    "test caller with a wrong code", "window expired", "window over 24h", "validation off",
    "another workspace configured", "another location configured", "workspace not in CAD",
])
async def test_everyone_else_books_as_today(case, monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    kwargs = {}
    shop = Shop()
    if case == "ordinary demo caller":
        kwargs = {"phone": DEMO, "code": None}
    elif case == "demo caller who says the code":
        kwargs = {"phone": DEMO}
    elif case == "test caller without a code":
        kwargs = {"code": None}
    elif case == "test caller with a wrong code":
        kwargs = {"code": "111111"}
    elif case == "window expired":
        open_window(monkeypatch, hours=-1)
    elif case == "window over 24h":
        open_window(monkeypatch, hours=30)
    elif case == "validation off":
        monkeypatch.delenv("SQUARE_INPLACE_TEST_CALLER_PHONE")
    elif case == "another workspace configured":
        open_window(monkeypatch, tenant="t-other")
    elif case == "another location configured":
        open_window(monkeypatch, location="L-ELSEWHERE")
    else:
        shop.tenant["square_currency"] = "usd"
    with shop.env():
        await _ordinary(shop, **kwargs)
    assert inplace_runs_store.rows[HASH]["vapi_call_id"] is None, "the code is not used up"


async def test_the_booking_and_its_text_are_identical_with_and_without_the_test(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    with Shop().env() as plain:
        a = await plain.book(phone=DEMO, code=None)
    with Shop().env() as test:
        b = await test.book()
    assert plain.bookings == test.bookings, "Square receives the same booking"
    assert test.appts == [x | {"caller_phone": ME} for x in plain.appts], "same appointment row"
    assert test.texts[0] == plain.texts[0], "same confirmation text"
    assert b.startswith(a), "the assistant hears the same, plus one sentence"


# ═══════════════════ single use, one link, retries and races ══════════════════

async def test_a_second_call_cannot_reuse_the_code(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    with Shop().env() as shop:
        await shop.book(call="call-1")
        said = await shop.book(call="call-2")
    assert len(shop.links) == 1 and len(shop.payments) == 1
    assert "test deposit" not in said, "the second call books as an ordinary caller"


async def test_a_retry_in_the_same_call_sends_no_second_link(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    with Shop().env() as shop:
        await shop.book()
        # The same call booking again (were the same-call guard ever bypassed):
        # its run is bound to the first appointment, so no link for the second.
        said = await shop.book()
    assert len(shop.links) == 1 and len(shop.payments) == 1 and len(deposit_texts(shop)) == 1
    assert "test deposit" not in said


async def test_concurrent_bookings_create_one_link(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    with Shop().env() as shop:
        results = await asyncio.gather(*(shop.book() for _ in range(5)))
    assert len(shop.links) == 1 and len(shop.payments) == 1 and len(deposit_texts(shop)) == 1
    assert sum("CAD $1 test deposit link has been texted" in r for r in results) == 1


async def test_concurrent_calls_with_the_same_code_create_one_link(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    with Shop().env() as shop:
        await asyncio.gather(*(shop.book(call=f"call-{i}") for i in range(5)))
    assert len(shop.links) == 1 and len(shop.payments) == 1


async def test_a_claimed_link_is_never_created_twice(monkeypatch, inplace_runs_store):
    """Same call, same appointment, link already claimed (e.g. a crash after the
    claim): nothing new is created, and the assistant is told not to send another."""
    open_window(monkeypatch)
    inplace_runs_store.rows[HASH] = {"code_sha256": HASH, "tenant_id": TID, "vapi_call_id": "call-1",
                                     "appointment_id": "appt-1", "link_claimed_at": "then",
                                     "payment_id": None, "disabled_at": None}
    with Shop().env() as shop:
        said = await shop.book()
    assert shop.links == [] and shop.payments == []
    assert "already sent; do not send another" in said


async def test_a_disabled_run_sends_nothing(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    inplace_runs_store.rows[HASH].update(vapi_call_id="call-1", disabled_at="now")
    with Shop().env() as shop:
        await _ordinary(shop)


async def test_bookkeeping_failure_sends_nothing(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    with Shop().env() as shop, \
            patch("db.inplace_test_runs.use_code", new=AsyncMock(side_effect=RuntimeError("db down"))):
        await _ordinary(shop)


async def test_the_test_deposit_never_reads_workspace_deposit_settings(monkeypatch):
    """Workspace deposits stay off: request_deposit for anyone still says so."""
    open_window(monkeypatch)
    with Shop().env() as shop:
        dep = await tools._create_and_send_deposit(shop.tenant, caller_phone=ME, caller_name="x",
                                                   service="s", appointment_id="appt-9")
    assert dep["error"] == "no_provider" and shop.links == []


# ══════════════════ armed, stopped, burned: fail closed ════════════════════════

async def test_with_nothing_armed_the_code_does_nothing(monkeypatch, inplace_runs_store):
    """Five settings configured, nobody armed a run: an ordinary booking."""
    open_window(monkeypatch)
    with Shop().env() as shop:
        await _ordinary(shop)
    assert inplace_runs_store.rows == {}, "nothing is ever inserted by a call"


async def test_stopping_before_first_use_blocks_first_use(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    inplace_runs_store.disable_all()                      # the stop command
    with Shop().env() as shop:
        await _ordinary(shop)
    assert inplace_runs_store.rows[HASH]["vapi_call_id"] is None, "never used"


async def test_stopping_mid_booking_blocks_the_payment_link(monkeypatch, inplace_runs_store):
    """Stop lands after the code was used and the appointment bound, before the
    link is claimed: no link, and nothing the move or lock may act on."""
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    real_bind = inplace_runs_store.bind_appointment

    async def bind_then_stop(h, appt):
        ok = await real_bind(h, appt)
        inplace_runs_store.disable_all()
        return ok
    with Shop().env() as shop, patch("db.inplace_test_runs.bind_appointment", new=bind_then_stop):
        said = await shop.book()
    assert shop.links == [] and shop.payments == [] and deposit_texts(shop) == []
    assert "test deposit" not in said
    assert not await scope.allowed(TID, "appt-1"), "the move and lock are off for it too"


async def test_stopping_after_the_link_stops_the_move_and_lock(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    with Shop().env() as shop:
        await shop.book()
    assert await scope.allowed(TID, "appt-1")
    inplace_runs_store.disable_all()
    assert not await scope.allowed(TID, "appt-1")


async def test_a_code_shorter_than_12_digits_is_refused(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    short = "482917"
    inplace_runs_store.arm(hashlib.sha256(short.encode()).hexdigest(), TID)
    with Shop().env() as shop:
        await _ordinary(shop, code=short)


async def test_a_code_armed_for_another_workspace_is_refused(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, "t-other")
    with Shop().env() as shop:
        await _ordinary(shop)


async def test_a_test_call_that_ends_unused_burns_the_code(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    assert await scope.burn_unused_codes(TID, DEMO, "call-x") == 0, "other callers burn nothing"
    assert await scope.burn_unused_codes(TID, ME, "call-x") == 1
    with Shop().env() as shop:
        await _ordinary(shop)


async def test_a_used_code_is_not_burned_by_a_later_call(monkeypatch, inplace_runs_store):
    open_window(monkeypatch)
    inplace_runs_store.arm(HASH, TID)
    with Shop().env() as shop:
        await shop.book()
    assert await scope.burn_unused_codes(TID, ME, "call-later") == 0
    assert await scope.allowed(TID, "appt-1"), "the booked test appointment stays in scope"


def test_every_end_of_call_report_runs_the_burn_check():
    import inspect
    from services import webhook_processor
    src = inspect.getsource(webhook_processor.process_end_of_call)
    assert "square_inplace_scope.burn_unused_codes(tenant_id, caller_number, call_id)" in src


def test_test_calls_are_not_recorded_and_others_are_unchanged():
    import inspect
    from routers import webhooks
    src = inspect.getsource(webhooks)
    i = src.index('overrides["artifactPlan"] = {"recordingEnabled": False}')
    assert "if test_call:" in src[i - 120:i]
    assert src.count("artifactPlan") == 1, "no other call's recording settings are touched"


# ═══════════════════════ the call: only the test caller ═══════════════════════

def test_only_the_test_caller_is_offered_a_code(monkeypatch):
    open_window(monkeypatch)
    assert scope.caller_in_test(TID, ME)
    assert scope.caller_in_test(TID, "+1 (647) 555-0100"), "formatting doesn't matter"
    assert not scope.caller_in_test(TID, DEMO)
    assert not scope.caller_in_test(TID, "6475550100"), "no country code: not trusted"
    assert not scope.caller_in_test("t-other", ME)
    open_window(monkeypatch, hours=-1)
    assert not scope.caller_in_test(TID, ME)


def test_the_code_field_is_added_to_book_appointment_only():
    tools_in = [{"type": "function", "function": {"name": "book_appointment",
                                                  "parameters": {"properties": {"date": {}}}}},
                {"type": "function", "function": {"name": "check_availability", "parameters": {}}}]
    out = vapi_svc.with_test_code(tools_in)
    assert "test_code" in out[0]["function"]["parameters"]["properties"]
    assert "test_code" not in tools_in[0]["function"]["parameters"]["properties"], "original untouched"
    assert out[1] == tools_in[1]


def test_the_webhook_offers_the_code_only_through_the_scope_check():
    import inspect
    from routers import webhooks
    src = inspect.getsource(webhooks)
    i = src.index("with_test_code(tools)")
    assert "test_call = square_inplace_scope.caller_in_test(tenant_id, caller_phone)" in src[i - 300:i]
