"""
Square Appointments bookings take the business's deposit, the assistant knows how
long things last, and an unpaid mandatory deposit releases the hold.

Live test on 16 Nov 2026 (demo line, Square Appointments, deposits ON via Square,
$1 mandatory): two bookings were confirmed with no deposit; the assistant could
not say whether a 9:00 appointment ran to 9:30 or 10:00; it said "Tuesday,
November 23" for a Monday; and it booked Square's sample "Consultation (example
service)" for a caller who never named a service.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools, webhooks
from services import appointment_refs, deposit_expiry, square_service as sq, vapi
from tests.test_inplace_test_deposit import LOC, ME, TID, Shop


def deposits_on(shop, **extra):
    shop.tenant.update({"square_deposits_enabled": True, "stripe_deposit_cents": 100, **extra})
    return shop


async def book(shop, service="Dress Fitting"):
    res = await tools._square_book_appointment(
        "tc", "call-1", shop.tenant, TID, {"service": service}, caller_name="Ricks",
        caller_phone=ME, service=service, date_str="2026-11-20", time_str="09:00",
        party_size=1, metadata_phone=ME)
    return res["results"][0]["result"]


# ═══════════════════════════ the deposit rule ════════════════════════════════

@pytest.mark.parametrize("tenant,party,want", [
    ({}, 1, (False, False)),
    ({"square_access_token": "x", "square_deposits_enabled": True}, 1, (True, True)),
    ({"square_access_token": "x", "square_deposits_enabled": True,
      "stripe_deposit_mandatory": False}, 1, (True, False)),
    ({"square_access_token": "x", "square_deposits_enabled": True,
      "deposit_applies": "group", "deposit_group_min_size": 4}, 3, (False, False)),
    ({"square_access_token": "x", "square_deposits_enabled": True,
      "deposit_applies": "group", "deposit_group_min_size": 4}, 4, (True, True)),
    ({"stripe_account_id": "acct", "stripe_deposits_enabled": True}, 1, (True, True)),
])
def test_one_deposit_rule_for_every_booking_path(tenant, party, want):
    assert tools._deposit_terms(tenant, party) == want


# ═══════════════════ single-location Square booking ══════════════════════════

async def test_a_mandatory_deposit_holds_the_booking_and_sends_the_link():
    with deposits_on(Shop()).env() as shop, \
            patch("db.supabase.update_appointment", new=AsyncMock()) as upd:
        said = await book(shop)
    assert shop.appts[0]["status"] == "pending_payment", "held until paid"
    assert len(shop.links) == 1 and shop.links[0]["amount_cents"] == 100
    assert shop.payments[0]["appointment_id"] == "appt-1" and shop.payments[0]["provider"] == "square"
    assert not any("confirmed for" in t for t in shop.texts), "no 'confirmed' text before payment"
    assert any("square.link" in t or "pay" in t.lower() for t in shop.texts), "the link was texted"
    assert said.startswith("BOOKING_CONFIRMED") and "deposit link has ALREADY been texted" in said
    assert "hold is released" in said
    assert "60 minutes long, 9:00 AM to 10:00 AM" in said
    upd.assert_not_awaited()


async def test_an_optional_deposit_confirms_and_still_sends_the_link():
    with deposits_on(Shop(), stripe_deposit_mandatory=False).env() as shop:
        said = await book(shop)
    assert shop.appts[0]["status"] == "confirmed"
    assert any("confirmed for" in t for t in shop.texts) and len(shop.links) == 1
    assert "hold is released" not in said


async def test_no_link_reached_the_caller_so_nothing_is_held():
    """Irish lines can't text, for example. A hold with no way to pay would be
    released later for something the caller couldn't do."""
    with deposits_on(Shop()).env() as shop, \
            patch("routers.tools._create_and_send_deposit", new=AsyncMock(return_value={
                "sms_sent": False, "already_paid": False, "amount_display": "1",
                "currency_voice": "dollars", "expiry_hours": 2, "error": "sms_failed"})), \
            patch("db.supabase.update_appointment", new=AsyncMock()) as upd:
        said = await book(shop)
    upd.assert_awaited_once_with("appt-1", {"status": "confirmed"})
    assert "team will follow" in said and "hold is released" not in said


async def test_without_deposits_it_books_exactly_as_before_plus_its_length():
    with Shop().env() as shop:
        said = await book(shop)
    assert shop.appts[0]["status"] == "confirmed" and shop.links == []
    assert said.startswith("Done! Your Dress Fitting at Open Lines is confirmed for")
    assert said.endswith("say this if the caller asks how long it is.")


async def test_a_booking_the_shop_must_accept_takes_no_deposit_yet():
    with deposits_on(Shop()).env() as shop, \
            patch("services.square_booking.create_booking",
                  new=AsyncMock(return_value={"id": "BK-1", "status": "PENDING"})):
        said = await book(shop)
    assert shop.links == [] and shop.appts[0]["status"] == "confirmed"
    assert "requested for" in said


# ═════════════════════ which service, how long, which day ════════════════════

TWO = [{"name": "Consultation (example service) — Regular", "square_variation_id": "V1",
        "duration_minutes": 60, "team_member_ids": ["TM"]},
       {"name": "Dress Fitting — Regular", "square_variation_id": "V2",
        "duration_minutes": 45, "team_member_ids": ["TM"]}]


def test_an_unnamed_service_is_asked_for_when_there_is_a_choice():
    ask = tools._which_service_prompt("", TWO)
    assert "Consultation (example service)" in ask and "Dress Fitting" in ask
    assert "Do NOT pick one" in ask
    assert tools._which_service_prompt("dress fitting", TWO) == ""
    assert tools._which_service_prompt("", TWO[:1]) == ""


async def test_booking_never_picks_a_service_for_the_caller():
    with Shop().env() as shop, \
            patch("db.supabase.get_square_services", new=AsyncMock(return_value=TWO)):
        said = await book(shop, service="")
    assert shop.bookings == [] and "Ask the caller which one" in said


async def test_availability_names_the_weekday_and_the_length():
    tenant = {"id": TID, "square_location_id": LOC, "calendar_timezone": "America/Toronto"}
    with patch("db.supabase.get_square_services", new=AsyncMock(return_value=TWO)), \
            patch("db.supabase.get_square_staff", new=AsyncMock(return_value=[])), \
            patch("services.square_booking.available_slot_strings",
                  new=AsyncMock(return_value=["9:00 AM", "9:30 AM"])):
        unnamed = await tools._square_availability_response("tc", tenant, TID, {}, "2026-11-23", "")
        res = await tools._square_availability_response(
            "tc", tenant, TID, {"service": "dress fitting"}, "2026-11-23", "")
    assert "Ask the caller which one" in unnamed["results"][0]["result"]
    said = res["results"][0]["result"]
    assert "Monday, November 23" in said
    assert "Each Dress Fitting is 45 minutes long" in said


def test_a_listed_appointment_says_how_long_it_is():
    row = {"service": "Consultation", "start_at_utc": "2026-11-20T14:00:00+00:00"}
    said = appointment_refs.describe(row, "", "America/Toronto", minutes=60)
    assert said == "a Consultation on Friday, November 20 at 9:00 AM (60 minutes, until 10:00 AM)"
    assert appointment_refs.describe(row, "", "America/Toronto") == \
        "a Consultation on Friday, November 20 at 9:00 AM"


async def test_the_service_menu_carries_each_length():
    from services import square_booking
    with patch("db.supabase.get_square_services", new=AsyncMock(return_value=TWO)), \
            patch("services.call_location.is_multi_location", new=AsyncMock(return_value=(False, []))):
        block = await square_booking.service_menu_block({"id": TID, "square_appointments_enabled": True})
    assert "Consultation (example service) (60 min), Dress Fitting (45 min)" in block
    assert "ask them. Never pick one for them." in block


# ══════════════════ the per-call setup knows about deposits ══════════════════

BASE = {"id": TID, "business_name": "Open Lines", "vapi_assistant_id": "asst-1",
        "last_system_prompt": "You are the receptionist.", "calendar_timezone": "America/Toronto",
        "square_appointments_enabled": True, "square_location_id": LOC,
        "square_access_token": "enc", "stripe_deposit_cents": 100}


async def _per_call(tenant):
    msg = {"type": "assistant-request", "phoneNumber": {"number": "+14388393907"},
           "call": {"id": "c1", "customer": {"number": ME}}}
    with patch("db.supabase.get_tenant_by_phone", new=AsyncMock(return_value=tenant)), \
            patch("routers.webhooks._calls_allowed", new=AsyncMock(return_value=True)), \
            patch("db.supabase.get_lead_by_phone", new=AsyncMock(return_value=None)), \
            patch("routers.webhooks.supports_safe_reschedule", new=AsyncMock(return_value=False)), \
            patch("services.call_location.location_prompt_block_for", new=AsyncMock(return_value="")), \
            patch("services.square_booking.service_menu_block", new=AsyncMock(return_value="")), \
            patch("services.analytics.capture"):
        out = await webhooks._handle_assistant_request(msg)
    model = out["assistantOverrides"]["model"] if "assistantOverrides" in out else out["assistant"]["model"]
    return model["messages"][0]["content"], [t.get("function", {}).get("name") or t.get("type")
                                             for t in model["tools"]]


async def test_with_deposits_on_every_call_gets_the_note_and_the_tool():
    prompt, tools_ = await _per_call({**BASE, "square_deposits_enabled": True})
    assert "DEPOSIT COLLECTION" in prompt and "request_deposit" in tools_


async def test_with_deposits_off_neither_is_added():
    prompt, tools_ = await _per_call({**BASE, "square_deposits_enabled": False})
    assert "DEPOSIT COLLECTION" not in prompt and "request_deposit" not in tools_


def test_the_deposit_note_defers_to_the_booking_result():
    assert "Do NOT call request_deposit after a booking" in vapi._DEPOSIT_NOTE
    assert "Call request_deposit immediately" not in vapi._DEPOSIT_NOTE


# ═════════════════════ releasing an unpaid hold (option b) ═══════════════════

NOW = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)


class Hold:
    def __init__(self, *, provider="square", status="pending", appt_status="pending_payment",
                 tenant_extra=None):
        self.tenant = {"id": TID, "business_name": "Open Lines", "square_appointments_enabled": True,
                       "square_access_token": "enc", "calendar_timezone": "America/Toronto",
                       "twilio_subaccount_sid": "AC", "twilio_auth_token": "t",
                       "twilio_phone_number": "+14388393907", **(tenant_extra or {})}
        self.appt = {"id": "a-1", "tenant_id": TID, "status": appt_status, "caller_phone": ME,
                     "caller_name": "Ricks", "service": "Consultation — Regular",
                     "appointment_datetime": "2026-11-20T14:00:00+00:00", "google_event_id": "BK-1"}
        self.payment = {"id": "p-1", "tenant_id": TID, "appointment_id": "a-1", "provider": provider,
                        "status": status, "checkout_session_id": "ORDER-1",
                        "payment_intent_id": "LINK-1", "expires_at": (NOW - timedelta(hours=1)).isoformat()}
        self.orders = ["unpaid", "unpaid"]
        self.link = sq.LINK_DELETED
        self.cancel = "ok"
        self.busy = False
        self.paid_row = None
        self.calls = []
        self.texts = []

    async def order_state(self, token, order_id):
        self.calls.append("order")
        return self.orders.pop(0) if self.orders else "unknown"

    async def delete_link(self, token, link_id):
        self.calls.append("delete")
        return self.link

    async def cancel_at_provider(self, tenant, appt, tid):
        self.calls.append("cancel")
        return self.cancel

    async def acquire(self, aid, tid):
        from services import mutation_ownership as m
        if self.busy:
            return m.BUSY, None
        return m.ACQUIRED, m.Claim(aid, "tok", "now", "cancel")

    async def update_appt(self, aid, data):
        self.calls.append(("appt", data["status"]))
        self.appt.update(data)

    async def update_pay(self, pid, data):
        self.calls.append(("payment", data["status"]))

    async def sms(self, **k):
        self.texts.append(k["body"])
        return True

    owner = None

    async def run(self):
        self.owner = AsyncMock()
        ps = [patch("services.deposit_expiry._now", lambda: NOW),
              patch("db.supabase.list_lapsed_deposits", new=AsyncMock(return_value=[self.payment])),
              patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=self.tenant)),
              patch("db.supabase.get_appointment_by_id", new=AsyncMock(side_effect=lambda a: dict(self.appt))),
              patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(side_effect=lambda a: self.paid_row)),
              patch("db.supabase.update_appointment", new=AsyncMock(side_effect=self.update_appt)),
              patch("db.supabase.update_payment", new=AsyncMock(side_effect=self.update_pay)),
              patch("services.square_service.order_payment_state", new=AsyncMock(side_effect=self.order_state)),
              patch("services.square_service.delete_payment_link", new=AsyncMock(side_effect=self.delete_link)),
              patch("services.appointment_cancellation.cancel_at_provider",
                    new=AsyncMock(side_effect=self.cancel_at_provider)),
              patch("services.mutation_ownership.acquire_for_cancel", new=AsyncMock(side_effect=self.acquire)),
              patch("services.mutation_ownership.release", new=AsyncMock()),
              patch("services.mutation_ownership.to_reconcile", new=AsyncMock()),
              patch("services.security.decrypt", new=lambda v: "tok"),
              patch("services.telephony.send_sms", new=AsyncMock(side_effect=self.sms)),
              patch("services.owner_notify.send_owner_sms_whatsapp", new=self.owner)]
        for p in ps:
            p.start()
        try:
            return await deposit_expiry.run_once()
        finally:
            for p in ps:
                p.stop()


async def test_an_unpaid_hold_is_released_after_the_link_is_closed():
    h = Hold()
    out = await h.run()
    assert out == {"released": 1, "skipped": 0}
    assert h.calls == ["order", "delete", "order", ("payment", "expired"), "cancel", ("appt", "cancelled")]
    assert h.texts and "didn't receive the deposit" in h.texts[0] and "Friday, November 20 at 9:00 AM" in h.texts[0]



async def test_the_owner_alert_also_goes_out_on_whatsapp(monkeypatch):
    from services import telephony
    monkeypatch.setattr(telephony, "TWILIO_WHATSAPP_CANCEL_TEMPLATE_SID", "HXcancel")
    h = Hold()
    await h.run()
    h.owner.assert_awaited_once()
    kw = h.owner.await_args.kwargs
    assert kw["event"] == "deposit_hold_released"
    assert "Unpaid hold released" in kw["sms_body"]
    assert kw["wa_template_sid"] == "HXcancel"
    v = kw["wa_vars"]
    assert set(v) == {"1", "2", "3", "4"} and all(x and "\n" not in x for x in v.values())
    assert v["1"] == "Open Lines" and v["2"].startswith("Ricks • ")
    assert v["3"] == "Consultation on Friday, November 20 at 9:00 AM"
    assert "wasn't paid in time" in v["4"] and len(v["4"]) <= 120


async def test_an_uncertain_hold_alerts_nobody():
    h = Hold()
    h.orders = ["paid"]
    await h.run()
    h.owner.assert_not_awaited()

@pytest.mark.parametrize("setup,why", [
    (lambda h: setattr(h, "orders", ["paid"]), "already paid at Square"),
    (lambda h: setattr(h, "orders", ["unknown"]), "order unreadable"),
    (lambda h: setattr(h, "link", sq.LINK_FAILED), "link could not be closed"),
    (lambda h: setattr(h, "orders", ["unpaid", "paid"]), "paid as the link closed"),
    (lambda h: setattr(h, "busy", True), "being changed elsewhere"),
    (lambda h: setattr(h, "paid_row", {"id": "p-1", "status": "succeeded"}), "webhook already recorded it"),
])
async def test_anything_uncertain_keeps_the_booking(setup, why):
    h = Hold()
    setup(h)
    out = await h.run()
    assert out == {"released": 0, "skipped": 1}, why
    assert "cancel" not in h.calls and ("appt", "cancelled") not in h.calls and h.texts == []


@pytest.mark.parametrize("hold", [
    lambda: Hold(appt_status="confirmed"),
    lambda: Hold(appt_status="cancelled"),
    lambda: Hold(tenant_extra={"square_appointments_enabled": False}),
])
async def test_only_square_bookings_still_on_hold_are_touched(hold):
    h = hold()
    assert (await h.run())["released"] == 0
    assert h.calls == []


async def test_a_stripe_deposit_waits_for_stripe_to_expire_it():
    h = Hold(provider="stripe", status="pending")
    assert (await h.run())["released"] == 0 and "cancel" not in h.calls
    h = Hold(provider="stripe", status="expired")
    assert (await h.run())["released"] == 1 and "delete" not in h.calls


async def test_an_unknown_cancel_goes_to_reconciliation_not_release():
    h = Hold()
    h.cancel = "unknown"
    out = await h.run()
    assert out["released"] == 0 and ("appt", "cancelled") not in h.calls and h.texts == []


async def test_the_kill_switch_stops_everything(monkeypatch):
    monkeypatch.setenv("DEPOSIT_HOLD_EXPIRY", "off")
    h = Hold()
    assert await h.run() == {"released": 0, "skipped": 0} and h.calls == []


async def test_order_and_link_helpers_classify_square_responses():
    import httpx

    class R:
        def __init__(self, code, body=None):
            self.status_code, self._b, self.is_success, self.text = code, body or {}, 200 <= code < 300, ""

        def json(self):
            return self._b

    async def get(self, url, **k):
        return R(200, {"order": {"state": "OPEN", "tenders": []}})

    with patch.object(httpx.AsyncClient, "get", get):
        assert await sq.order_payment_state("t", "O") == sq.ORDER_UNPAID

    async def get_paid(self, url, **k):
        return R(200, {"order": {"state": "OPEN", "tenders": [{"id": "x"}]}})

    with patch.object(httpx.AsyncClient, "get", get_paid):
        assert await sq.order_payment_state("t", "O") == sq.ORDER_PAID

    async def get_500(self, url, **k):
        return R(500)

    with patch.object(httpx.AsyncClient, "get", get_500):
        assert await sq.order_payment_state("t", "O") == sq.ORDER_UNKNOWN
    assert await sq.order_payment_state("t", "") == sq.ORDER_UNKNOWN

    for code, want in ((200, sq.LINK_DELETED), (404, sq.LINK_GONE), (500, sq.LINK_FAILED)):
        async def delete(self, url, _c=code, **k):
            return R(_c)
        with patch.object(httpx.AsyncClient, "delete", delete):
            assert await sq.delete_payment_link("t", "L") == want


# ═════════════════════════ "1 dollar", not "1 dollars" ════════════════════════

@pytest.mark.parametrize("amount,code,want", [
    ("1", "cad", "1 dollar"), ("1.00", "usd", "1 dollar"), ("1", "eur", "1 euro"),
    ("1", "gbp", "1 pound"), ("25", "cad", "25 dollars"), ("1.50", "cad", "1.50 dollars"),
    ("10", "eur", "10 euros"), ("1", "jpy", "1 JPY")])
def test_the_amount_is_spoken_in_the_right_number(amount, code, want):
    from services.short_links import format_currency, spoken_amount
    got = spoken_amount(amount, code)
    if code == "jpy":
        assert got == f"1 {format_currency('jpy')}".strip()
    else:
        assert got == want


async def test_the_booking_result_says_one_dollar():
    with deposits_on(Shop()).env() as shop:
        said = await book(shop)
    assert "1 dollars" not in said
    assert "A 1 dollar deposit link" in said and "pay the 1 dollar deposit" in said
