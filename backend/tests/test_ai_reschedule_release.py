"""
The AI moves deposit appointments itself, within the business's rules; when it
can't, the team gets a real request instead of an empty promise.

Call 2e8ce4c7 (7 Nov 2026, demo line):
  * a caller asked to move a $1-deposit Square appointment from Nov 11 to Nov 12
    9 AM. The in-place move only ran for the one armed #179 test appointment, so
    it was handed to the team ("take a message"), and nothing recorded it;
  * a demo that had ended eleven hours earlier was read out as "today at 12PM".
"""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools
from services import deposit_moves, reschedule_handoff, relative_dates
from services import reschedule_intent as ri, square_inplace_reschedule as sq_in
from tests.test_square_deposit_reschedule import (CALL, NOW, OWED, PAID, PHONE, SRC, TID, SqWorld,
                                                  assert_moved_in_place)

_TEST_VARS = ("SQUARE_INPLACE_TEST_TENANT_ID", "SQUARE_INPLACE_TEST_LOCATION_ID",
              "SQUARE_INPLACE_TEST_CALLER_PHONE", "SQUARE_INPLACE_TEST_EXPIRES_AT")


@pytest.fixture(autouse=True)
def _no_validation_run(monkeypatch, inplace_runs_store):
    """The general release: no validation window, no armed run."""
    for v in _TEST_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.delenv("SQUARE_DEPOSIT_MOVES", raising=False)
    inplace_runs_store.rows.clear()


@pytest.fixture
def team(monkeypatch):
    """callback_requests + owner alerts, recorded instead of sent."""
    class Team:
        rows: list = []
        emails: list = []
        texts: list = []
    t = Team()
    t.rows, t.emails, t.texts = [], [], []

    async def create(tenant_id, data):
        row = {**data, "tenant_id": tenant_id, "id": f"cb-{len(t.rows) + 1}"}
        t.rows.append(row)
        return row

    async def listing(tenant_id, status="open"):
        return [r for r in t.rows if r["tenant_id"] == tenant_id and r["status"] == status]

    async def email(**kw):
        t.emails.append(kw)
        return True

    async def text(tenant, **kw):
        t.texts.append(kw)

    ps = [patch("db.routing.create_callback", new=AsyncMock(side_effect=create)),
          patch("db.routing.list_callbacks", new=AsyncMock(side_effect=listing)),
          patch("services.email.send_reschedule_request_email", new=AsyncMock(side_effect=email)),
          patch("services.owner_notify.send_owner_sms_whatsapp", new=AsyncMock(side_effect=text))]
    for p in ps:
        p.start()
    yield t
    for p in ps:
        p.stop()


# ══════════════════════════ the release switch ═══════════════════════════════

@pytest.mark.parametrize("value,on", [(None, True), ("on", True), ("", True), ("off", False),
                                      ("OFF", False), ("0", False), ("false", False), ("no", False)])
def test_deposit_moves_are_on_unless_switched_off(value, on, monkeypatch):
    if value is not None:
        monkeypatch.setenv("SQUARE_DEPOSIT_MOVES", value)
    assert deposit_moves.released() is on
    assert deposit_moves.any_enabled() is on


@pytest.mark.parametrize("payments", [PAID, OWED], ids=["paid", "owed"])
@pytest.mark.parametrize("multi", [False, True])
async def test_any_workspace_moves_a_deposit_appointment_in_place(payments, multi, team):
    """The 7 Nov request, with no test run armed: the AI moves it itself."""
    status = "pending_payment" if payments is OWED else "confirmed"
    with SqWorld(multi=multi, payments=payments, status=status).env() as w:
        await w.call()
        said = await w.move()
    assert_moved_in_place(w, said)
    assert team.rows == [] and team.emails == [], "nothing handed to the team"


async def test_switched_off_the_team_gets_a_real_request(monkeypatch, team):
    monkeypatch.setenv("SQUARE_DEPOSIT_MOVES", "off")
    with SqWorld(payments=PAID).env() as w:
        w.tenant["notification_email"] = "owner@example.com"
        await w.call()
        said = await w.move()
    assert said.startswith(ri.message_for(ri.PAYMENT_ON_FILE))
    assert "already been sent to the team" in said
    assert w.updates == [] and not w.moved()
    [row] = team.rows
    assert row["tenant_id"] == TID and row["caller_phone"] == PHONE and row["caller_name"] == "Sam"
    assert row["status"] == "open"
    assert row["reason"].startswith("Reschedule request: move Consultation on Fri Nov 6, 9:00 AM "
                                    "to Fri Nov 6, 11:00 AM."), row["reason"]
    assert "deposit" in row["reason"]
    [mail] = team.emails
    assert mail["idempotency_key"] == f"reschedule-handoff:{CALL}:a-1"
    assert mail["reason"] == row["reason"]
    assert len(team.texts) == 1 and team.texts[0]["event"] == "reschedule_handoff"


async def test_the_store_rule_still_wins_inside_the_cancellation_window(team):
    """A paid deposit already inside the business's own refund window stays put."""
    with SqWorld(payments=PAID, refund_hours=100).env() as w:
        await w.call()
        said = await w.move()
    assert said.startswith(sq_in._MESSAGES[sq_in.POLICY_WINDOW])
    assert w.updates == [] and not w.moved()
    [row] = team.rows
    assert "cancellation window" in row["reason"] and "to Fri Nov 6, 11:00 AM" in row["reason"]


async def test_a_repeated_request_pages_the_owner_once(monkeypatch, team):
    monkeypatch.setenv("SQUARE_DEPOSIT_MOVES", "off")
    with SqWorld(payments=PAID).env() as w:
        w.tenant["notification_email"] = "owner@example.com"
        await w.call()
        first = await w.move()
        second = await w.move()
    assert len(team.rows) == 1 and len(team.emails) == 1 and len(team.texts) == 1
    assert "already been sent to the team" in first
    assert "already been sent" not in second, "only a NEW request is announced"


async def test_a_failed_record_never_breaks_the_call(monkeypatch):
    monkeypatch.setenv("SQUARE_DEPOSIT_MOVES", "off")
    with patch("db.routing.list_callbacks", new=AsyncMock(side_effect=RuntimeError("db down"))), \
            SqWorld(payments=PAID).env() as w:
        await w.call()
        said = await w.move()
    assert said == ri.message_for(ri.PAYMENT_ON_FILE), "today's wording, nothing claimed"


def test_follow_up_outcomes_are_the_ones_that_promise_the_team():
    for outcome in reschedule_handoff.SQUARE_FOLLOW_UP:
        msg = (ri._MESSAGES.get(outcome) or sq_in._MESSAGES.get(outcome) or "").lower()
        if msg:
            assert "team" in msg, outcome
    for done in ("completed", "slot_taken", "invalid_ref", "expired_ref", "service_mismatch",
                 "already_cancelled", "staff_unavailable"):
        assert done not in reschedule_handoff.SQUARE_FOLLOW_UP


def test_the_owner_email_escapes_what_the_caller_said():
    import inspect
    from services import email
    src = inspect.getsource(email.send_reschedule_request_email)
    assert "_kv_table(" in src and "_esc(caller_name" in src


# ══════════════════ past appointments are never offered ══════════════════════

async def test_an_appointment_that_already_happened_is_not_offered(team):
    """7 Nov: a demo eleven hours in the past was read out as "today at 12PM"."""
    with SqWorld(payments=PAID).env() as w:
        past = dict(w.appt, id="a-past", service="Demo",
                    appointment_datetime=(NOW - timedelta(hours=11)).isoformat())
        w.active = AsyncMock(return_value=[past, dict(w.appt)])
        with patch("db.supabase.get_active_appointments_by_phone", new=w.active):
            said = await w.call()
    assert "one upcoming appointment" in said and "Demo" not in said
    assert "Consultation" in said


async def test_only_past_appointments_means_none_upcoming(team):
    with SqWorld().env() as w:
        past = dict(w.appt, appointment_datetime=(NOW - timedelta(minutes=5)).isoformat())
        with patch("db.supabase.get_active_appointments_by_phone",
                   new=AsyncMock(return_value=[past])):
            said = await w.call()
    assert said.startswith("I don't see any upcoming appointment")


async def test_cancel_lists_only_appointments_still_to_come(team):
    from routers import tools as t
    future = {"id": "a-1", "appointment_datetime": SRC.isoformat(), "service": "Consultation"}
    past = {"id": "a-0", "appointment_datetime": (NOW - timedelta(hours=1)).isoformat()}
    seen = {}

    async def refs(**kw):
        seen["ids"] = [a["id"] for a in kw["appointments"]]
        return []

    with patch.object(relative_dates, "_utcnow", lambda: NOW), \
            patch("db.supabase.get_active_appointments_by_phone",
                  new=AsyncMock(return_value=[past, future])), \
            patch("services.appointment_refs.create_refs", new=AsyncMock(side_effect=refs)), \
            patch("services.call_location.is_multi_location", new=AsyncMock(return_value=(False, []))):
        await t._list_cancellable("tc", CALL, {}, TID, PHONE, action="cancel")
    assert seen["ids"] == ["a-1"]


def test_an_unreadable_time_is_kept_rather_than_hidden():
    assert tools._still_to_come({"appointment_datetime": "garbage"}, NOW)
    assert tools._still_to_come({}, NOW)
