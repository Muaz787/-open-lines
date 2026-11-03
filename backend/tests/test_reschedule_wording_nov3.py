"""
Wording fixes from call 424d2579 (3 Nov).

- The final recap said a cancelled 9:15 appointment was at "9AM".
- Times for the appointment's current day were offered before the caller had said
  which day to move it to.
- "Let me move that for you." was spoken while the tool only listed appointments.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from services import calendar_reschedule as cr, relative_dates, vapi


@pytest.mark.parametrize("h, m, said", [
    (9, 0, "nine a.m."), (9, 15, "nine fifteen a.m."), (14, 5, "two oh five p.m."),
    (12, 30, "twelve thirty p.m."), (0, 45, "twelve forty-five a.m."), (16, 20, "four twenty p.m."),
])
def test_spoken_clock(h, m, said):
    assert relative_dates.spoken_clock(datetime(2026, 11, 3, h, m)) == said


def test_recaps_copy_times_exactly():
    assert "including in a recap of several changes" in vapi.RECEPTIONIST_STYLE
    assert 'never rounded to "nine"' in vapi.RECEPTIONIST_STYLE


def test_a_completed_move_names_its_time_exactly():
    tz = ZoneInfo("America/Toronto")
    msg = cr._message(cr.COMPLETED, tz, {"service": "demo",
                                         "appointment_datetime": "2026-11-05T14:15:00+00:00"}, None)
    assert '"nine fifteen a.m."' in msg


def test_the_cancel_result_names_its_time_exactly():
    import inspect
    from routers import tools
    src = inspect.getsource(tools.cancel_appointment)
    assert "relative_dates.spoken_clock(appt_dt_local)" in src
    assert "say the time exactly" in src


@pytest.mark.parametrize("kind", ["calendar", "square"])
def test_a_move_waits_for_the_target_day_before_offering_times(kind):
    note = vapi.caller_lookup_note(supports_reschedule=True, reschedule_kind=kind)
    assert "Ask which day they want to move it TO" in note
    assert "wait for a clear answer" in note


@pytest.mark.parametrize("kind", ["calendar", "square"])
def test_the_hold_line_does_not_claim_a_move(kind):
    tool = next(t for t in vapi.build_calendar_tools("t1", supports_reschedule=True, reschedule_kind=kind)
                if t["function"]["name"] == "reschedule_appointment")
    start = tool["messages"][0]["content"]
    assert start == "One moment, please." and "move" not in start.lower()
