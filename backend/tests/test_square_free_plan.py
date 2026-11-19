"""
Square's free Appointments plan refuses bookings, moves and cancellations from
apps (HTTP 403 "Merchant subscription does not support write operations."). The
assistant must not promise them: it hands each one to the team as a request.

Before this, a free-plan salon's caller heard a generic calendar error after we
had already created their Square customer, and nobody was told.
"""
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from routers import tools
from services import reschedule_handoff, square_booking, square_plan
from tests.test_inplace_test_deposit import ME, TID, Shop

REFUSAL = ('{"errors":[{"category":"AUTHENTICATION_ERROR","code":"FORBIDDEN",'
           '"detail":"Merchant subscription does not support write operations."}]}')


class _Req:
    client = type("c", (), {"host": "127.0.0.1"})()
    headers: dict = {}


def free_plan():
    return patch("services.square_booking.retrieve_booking_profile",
                 new=AsyncMock(return_value={"booking_enabled": True,
                                             "support_seller_level_writes": False}))


def paid_plan():
    return patch("services.square_booking.retrieve_booking_profile",
                 new=AsyncMock(return_value={"booking_enabled": True,
                                             "support_seller_level_writes": True}))


# ═══════════════════════════ detecting the plan ══════════════════════════════

@pytest.mark.parametrize("code,body,want", [
    (403, REFUSAL, True),
    (403, '{"errors":[{"code":"FORBIDDEN","detail":"Not authorized"}]}', False),
    (401, REFUSAL, False),
    (400, "", False),
])
def test_only_squares_plan_refusal_counts(code, body, want):
    assert square_plan.is_plan_refusal(code, body) is want


async def test_the_profile_answer_is_cached_per_token():
    with free_plan() as prof:
        assert await square_plan.seller_writes("tok") is False
        assert await square_plan.seller_writes("tok") is False
    assert prof.await_count == 1
    with paid_plan():
        assert await square_plan.seller_writes("other") is True


async def test_an_unreadable_profile_is_unknown_not_free():
    # conftest stubs the profile as {}: callers go ahead and try as before.
    assert await square_plan.seller_writes("tok") is None
    assert await square_plan.seller_writes("") is None


async def test_a_refused_write_marks_the_token_read_only():
    with paid_plan():
        assert await square_plan.seller_writes("tok") is True
    square_plan.mark_no_writes("tok")
    assert await square_plan.seller_writes("tok") is False


async def test_create_booking_marks_the_plan_when_square_refuses():
    resp = httpx.Response(403, text=REFUSAL, request=httpx.Request("POST", "https://x"))
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
        with pytest.raises(httpx.HTTPStatusError):
            await square_booking.create_booking(
                "tok", location_id="L", start_at_iso="2026-11-20T14:00:00Z", customer_id="C",
                team_member_id="TM", service_variation_id="V", service_variation_version=1,
                duration_minutes=60)
    assert await square_plan.seller_writes("tok") is False


# ═══════════════════════════════ booking ════════════════════════════════════

async def book(shop):
    res = await tools._square_book_appointment(
        "tc", "call-1", shop.tenant, TID, {"service": "Dress Fitting"}, caller_name="Ricks",
        caller_phone=ME, service="Dress Fitting", date_str="2026-11-20", time_str="09:00",
        party_size=1, metadata_phone=ME)
    return res["results"][0]["result"]


def recorder():
    return patch("services.square_plan.record_request", new=AsyncMock(return_value=True))


async def test_a_free_plan_booking_becomes_a_request_for_the_team():
    with Shop().env() as shop, free_plan(), recorder() as rec, \
            patch("services.square_booking.resolve_customer", new=AsyncMock()) as cust, \
            patch("services.square_booking.create_booking", new=AsyncMock()) as create:
        said = await book(shop)
    cust.assert_not_awaited()
    create.assert_not_awaited()
    assert shop.appts == [] and shop.links == [] and shop.texts == []
    kw = rec.await_args.kwargs
    assert kw["kind"] == square_plan.KIND_BOOK and kw["caller_phone"] == ME
    assert kw["detail"].startswith("Dress Fitting on Friday, November 20 at 9:00 AM")
    assert said.startswith("NOT BOOKED YET") and "Do not say it is booked" in said
    assert "already been sent to the team" in said


async def test_a_refusal_we_didnt_see_coming_still_becomes_a_request():
    err = httpx.HTTPStatusError(
        "403", request=httpx.Request("POST", "https://x"),
        response=httpx.Response(403, text=REFUSAL))
    with Shop().env() as shop, recorder() as rec, \
            patch("services.square_booking.create_booking", new=AsyncMock(side_effect=err)):
        said = await book(shop)
    rec.assert_awaited_once()
    assert said.startswith("NOT BOOKED YET") and shop.appts == []


async def test_a_paid_plan_books_exactly_as_before():
    with Shop().env() as shop, paid_plan(), recorder() as rec:
        said = await book(shop)
    rec.assert_not_awaited()
    assert shop.appts and said.startswith("Done! Your Dress Fitting")


async def test_any_other_failure_is_still_the_calendar_error():
    err = httpx.HTTPStatusError(
        "400", request=httpx.Request("POST", "https://x"),
        response=httpx.Response(400, text='{"errors":[{"code":"BAD_REQUEST"}]}'))
    with Shop().env(), recorder() as rec, \
            patch("services.square_booking.create_booking", new=AsyncMock(side_effect=err)):
        said = await book(Shop())
    rec.assert_not_awaited()
    assert said == tools._CALENDAR_ERROR_MSG


# ═══════════════════════════ moving and cancelling ════════════════════════════

SQUARE_TENANT = {"id": TID, "business_name": "Open Lines", "square_appointments_enabled": True,
                 "square_access_token": "enc"}


def tool_body(name, **args):
    return {"message": {"toolCallList": [{"id": "tc", "function": {
        "name": name, "arguments": json.dumps(args)}}],
        "call": {"id": "call-1", "customer": {"number": ME}}}}


async def test_a_free_plan_move_goes_to_the_team_with_the_new_time():
    with free_plan(), \
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=SQUARE_TENANT)), \
            patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
            patch("services.reschedule_intent.move_appointment", new=AsyncMock()) as move, \
            patch("services.reschedule_handoff.record", new=AsyncMock(return_value=True)) as rec, \
            patch("services.analytics.capture"):
        res = await tools.reschedule_appointment(
            _Req(), TID, tool_body("reschedule_appointment", appointment_ref="appt_1", slot_ref="slot_2"))
    said = res["results"][0]["result"]
    move.assert_not_awaited()
    kw = rec.await_args.kwargs
    assert kw["outcome"] == reschedule_handoff.PLAN_NO_WRITES and kw["slot_ref"] == "slot_2"
    assert said.startswith("NOT MOVED YET") and "already been sent to the team" in said


def test_the_owner_reads_why_it_wasnt_moved():
    from zoneinfo import ZoneInfo
    line = reschedule_handoff.reason_text(
        {"service": "Haircut", "appointment_datetime": "2026-11-20T14:00:00Z"},
        "Fri Nov 20, 10:00 AM", reschedule_handoff.PLAN_NO_WRITES, ZoneInfo("America/Toronto"))
    assert "Square plan doesn't let the assistant change bookings" in line
    assert reschedule_handoff.PLAN_NO_WRITES in reschedule_handoff.SQUARE_FOLLOW_UP


async def test_a_move_refused_for_the_plan_mid_call_also_goes_to_the_team():
    async def refused(**k):
        square_plan.mark_no_writes("tok")
        from services import reschedule_intent
        return reschedule_intent.CREATE_FAILED, "couldn't"
    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=SQUARE_TENANT)), \
            patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
            patch("services.reschedule_intent.move_appointment", new=AsyncMock(side_effect=refused)), \
            patch("services.reschedule_handoff.record", new=AsyncMock(return_value=True)) as rec, \
            patch("services.analytics.capture"):
        res = await tools.reschedule_appointment(
            _Req(), TID, tool_body("reschedule_appointment", appointment_ref="appt_1", slot_ref="slot_2"))
    assert res["results"][0]["result"].startswith("NOT MOVED YET")
    assert rec.await_args.kwargs["outcome"] == reschedule_handoff.PLAN_NO_WRITES


async def test_a_free_plan_cancel_goes_to_the_team_and_touches_nothing():
    appt = {"id": "a-1", "tenant_id": TID, "caller_phone": ME, "caller_name": "Ricks",
            "service": "Haircut — Regular", "appointment_datetime": "2026-11-20T14:00:00+00:00",
            "status": "confirmed", "google_event_id": "BK"}
    with free_plan(), recorder() as rec, \
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=SQUARE_TENANT)), \
            patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
            patch("services.appointment_refs.resolve_for_cancel",
                  new=AsyncMock(return_value=("ok", {"appointment_id": "a-1"}))), \
            patch("db.supabase.get_appointment_by_id", new=AsyncMock(return_value=appt)), \
            patch("services.mutation_ownership.acquire_for_cancel", new=AsyncMock()) as own, \
            patch("services.square_booking.cancel_booking_detailed", new=AsyncMock()) as sq_cancel, \
            patch("services.analytics.capture"):
        res = await tools.cancel_appointment(
            _Req(), TID, tool_body("cancel_appointment", appointment_ref="appt_1"))
    said = res["results"][0]["result"]
    own.assert_not_awaited()
    sq_cancel.assert_not_awaited()
    kw = rec.await_args.kwargs
    assert kw["kind"] == square_plan.KIND_CANCEL and kw["caller_name"] == "Ricks"
    assert kw["detail"] == "cancel Haircut on Fri Nov 20, 9:00 AM"
    assert said.startswith("NOT CANCELLED YET")


# ═══════════════════════════ telling the owner ═══════════════════════════════

async def test_a_request_is_stored_once_and_the_owner_is_alerted():
    rows = []

    async def create(tid, data):
        rows.append(data)
        return data

    async def listed(tid, status="open"):
        return list(rows)

    tenant = {**SQUARE_TENANT, "notification_email": "owner@example.test"}
    with patch("db.routing.create_callback", new=AsyncMock(side_effect=create)), \
            patch("db.routing.list_callbacks", new=AsyncMock(side_effect=listed)), \
            patch("services.email.send_square_request_email", new=AsyncMock()) as mail, \
            patch("services.owner_notify.send_owner_sms_whatsapp", new=AsyncMock()) as sms:
        args = dict(tenant=tenant, tenant_id=TID, call_id="call-1", kind=square_plan.KIND_BOOK,
                    caller_name="Ricks", caller_phone=ME, detail="Haircut on Friday, November 20 at 9:00 AM")
        assert await square_plan.record_request(**args) is True
        assert await square_plan.record_request(**args) is False, "a retried tool call adds nothing"
    assert len(rows) == 1 and rows[0]["reason"] == "Booking request: Haircut on Friday, November 20 at 9:00 AM"
    assert rows[0]["status"] == "open" and rows[0]["caller_phone"] == ME
    mail.assert_awaited_once()
    assert mail.await_args.kwargs["title"] == "Booking request"
    sms.assert_awaited_once()
    assert "Booking request: Haircut" in sms.await_args.kwargs["sms_body"]


async def test_recording_never_breaks_the_call():
    with patch("db.routing.list_callbacks", new=AsyncMock(side_effect=RuntimeError("db down"))):
        assert await square_plan.record_request(
            tenant=SQUARE_TENANT, tenant_id=TID, call_id="c", kind=square_plan.KIND_BOOK,
            caller_name="", caller_phone=ME, detail="x") is False


# ═══════════════════════════════ dashboard ═══════════════════════════════════

async def test_the_dashboard_status_reports_the_plan():
    from routers import square_connect
    with free_plan(), \
            patch("routers.square_connect.verify_tenant_owner", new=AsyncMock()), \
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=SQUARE_TENANT)), \
            patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
            patch("db.supabase.get_square_services", new=AsyncMock(return_value=[])), \
            patch("db.supabase.get_square_staff", new=AsyncMock(return_value=[])):
        out = await square_connect.appointments_status(TID, authorization="Bearer x")
    assert out["seller_writes"] is False


async def test_an_unconnected_account_reports_no_plan():
    from routers import square_connect
    with patch("routers.square_connect.verify_tenant_owner", new=AsyncMock()), \
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value={"id": TID})), \
            patch("db.supabase.get_square_services", new=AsyncMock(return_value=[])), \
            patch("db.supabase.get_square_staff", new=AsyncMock(return_value=[])):
        out = await square_connect.appointments_status(TID, authorization="Bearer x")
    assert out["seller_writes"] is None
