"""
Ending a call cleanly.

On 2 November a caller said "You too. Thanks." and the assistant answered "Thank
you. Take care." The line stayed open: the per-call tool list (which replaces the
assistant's own) had no endCall tool, and "take care" was not an end-call phrase.
Eleven seconds later background speech was transcribed as "My mom." and the
assistant started again from its introduction.

What can be tested here is the setup the model is given on every call and the
fallback that hangs up without it. Whether the model follows the rules is checked
on real calls.
"""
from unittest.mock import AsyncMock, patch

import pytest

from routers import webhooks
from services import vapi

TENANT = {"id": "t1", "business_name": "Open Lines", "vapi_assistant_id": "asst-1",
          "last_system_prompt": "You are the receptionist for Open Lines. Greet callers warmly.",
          "google_refresh_token": "rt", "calendar_timezone": "America/Toronto",
          "greeting_template": "Thanks for calling Open Lines."}


async def _per_call_setup(tenant=TENANT):
    msg = {"type": "assistant-request", "phoneNumber": {"number": "+14385550000"},
           "call": {"id": "c1", "customer": {"number": "+16475550100"}}}
    with patch("db.supabase.get_tenant_by_phone", new=AsyncMock(return_value=tenant)), \
            patch("routers.webhooks._calls_allowed", new=AsyncMock(return_value=True)), \
            patch("db.supabase.get_lead_by_phone", new=AsyncMock(return_value=None)), \
            patch("routers.webhooks.supports_safe_reschedule", new=AsyncMock(return_value=False)), \
            patch("services.call_location.location_prompt_block_for", new=AsyncMock(return_value="")), \
            patch("services.square_booking.service_menu_block", new=AsyncMock(return_value="")), \
            patch("services.analytics.capture"):
        return await webhooks._handle_assistant_request(msg)


def _would_hang_up(utterance: str) -> bool:
    """Vapi ends the call when the assistant says an end-call phrase (case-insensitive)."""
    said = utterance.lower()
    return any(p in said for p in vapi.CLOSING_PHRASES)


# ── the setup every call receives ─────────────────────────────────────────────

def _end_call(out):
    ends = [t for t in out["assistantOverrides"]["model"]["tools"] if t.get("type") == "endCall"]
    assert len(ends) == 1
    return ends[0]


async def test_every_call_can_end_itself():
    _end_call(await _per_call_setup())


async def test_a_tenant_without_a_calendar_can_end_its_calls_too():
    _end_call(await _per_call_setup({**TENANT, "google_refresh_token": None}))


async def test_the_fallback_phrases_are_set_per_call():
    ov = (await _per_call_setup())["assistantOverrides"]
    assert ov["endCallPhrases"] == ["goodbye for now", "bye for now", "bye bye"]


async def test_silence_handling_is_unchanged():
    """Ending cleanly must not come from hanging up on quiet callers."""
    ov = (await _per_call_setup())["assistantOverrides"]
    assert ov["silenceTimeoutSeconds"] == 25


async def test_the_closing_rules_reach_the_prompt_once_and_last():
    prompt = (await _per_call_setup())["assistantOverrides"]["model"]["messages"][0]["content"]
    assert prompt.count("ENDING THE CALL") == 1
    assert prompt.index("ENDING THE CALL") > prompt.index("HOW YOU SPEAK")
    assert vapi.ensure_call_closing(prompt) == prompt, "idempotent"


# ── a clear goodbye ───────────────────────────────────────────────────────────

async def test_the_goodbye_is_the_end_call_message_not_a_tool_message():
    """3 Nov, call 424d2579: endCall with nothing said — silence, then a dead line.
    3 Nov, call 46ac9156: a blocking request-start goodbye on endCall was cut after
    its first sentence. The goodbye is now Vapi's endCallMessage, the line spoken
    when the assistant ends the call, and endCall carries no message of its own."""
    out = await _per_call_setup()
    assert _end_call(out) == {"type": "endCall"}
    assert out["assistantOverrides"]["endCallMessage"] == "Thanks for calling. Take care."


async def test_a_returning_callers_goodbye_uses_their_first_name():
    lead = {"id": "l1", "name": "Ricks Littlebaugh", "summary": ""}
    with patch("db.supabase.get_lead_by_phone", new=AsyncMock(return_value=lead)), \
            patch("db.supabase.get_upcoming_appointment_by_phone", new=AsyncMock(return_value=None)):
        msg = {"type": "assistant-request", "phoneNumber": {"number": "+14385550000"},
               "call": {"id": "c1", "customer": {"number": "+16475550100"}}}
        with patch("db.supabase.get_tenant_by_phone", new=AsyncMock(return_value=TENANT)), \
                patch("routers.webhooks._calls_allowed", new=AsyncMock(return_value=True)), \
                patch("routers.webhooks.supports_safe_reschedule", new=AsyncMock(return_value=False)), \
                patch("services.call_location.location_prompt_block_for", new=AsyncMock(return_value="")), \
                patch("services.square_booking.service_menu_block", new=AsyncMock(return_value="")), \
                patch("services.analytics.capture"):
            out = await webhooks._handle_assistant_request(msg)
    assert out["assistantOverrides"]["endCallMessage"] == "Thanks for calling, Ricks. Take care."


def test_the_model_never_adds_its_own_goodbye():
    note = vapi.CALL_CLOSING_NOTE
    assert "call endCall and say NOTHING yourself in that turn" in note
    assert "Never say your own goodbye" in note
    assert "ONE short line" not in note


@pytest.mark.parametrize("name", ["", "Sam", "Ricks Littlebaugh"])
def test_the_goodbye_never_contains_an_end_call_phrase(name):
    """A fallback phrase inside the goodbye could end the call as it starts."""
    assert not _would_hang_up(vapi.closing_line(name))


# ── the caller changes their mind before the close ────────────────────────────

def test_a_new_request_before_closing_keeps_the_call_going():
    note = vapi.CALL_CLOSING_NOTE
    assert "Only close once the caller is clearly done" in note
    assert "a change of mind" in note and "keep helping" in note
    assert "Is there anything else I can help with?" in note


@pytest.mark.parametrize("mid_call", [
    # Real assistant lines from the 2 November calls, and lines built to trip a
    # careless phrase list. None of them may end a call.
    "I'm not able to change an existing appointment on this call. But I can take a message for the team, and they'll sort it out.",
    "No problem at all. If you change your mind or want any other help, just give us a call.",
    "We'll take care of that for you right away.",
    "Open Lines helps you say goodbye to missed calls for good.",
    "Thanks for calling Open Lines. How can I help you today?",
    "Perfect. Your demo is now confirmed for Wednesday the fourth at 9 a.m. Anything else I can help with?",
    "One moment. You actually have three upcoming demo appointments.",
])
def test_ordinary_lines_never_trip_the_fallback(mid_call):
    assert not _would_hang_up(mid_call)


def test_no_phrase_is_a_word_that_appears_in_ordinary_speech():
    for p in vapi.CLOSING_PHRASES:
        assert p not in ("goodbye", "take care", "thanks for calling", "have a great day")


# ── background speech after the close ─────────────────────────────────────────

def test_background_speech_after_closing_ends_the_call_instead_of_restarting():
    note = vapi.CALL_CLOSING_NOTE
    assert '"my mom"' in note and "call endCall" in note
    assert "don't start over" in note


def test_the_introduction_is_never_repeated():
    note = vapi.CALL_CLOSING_NOTE
    assert "Never greet the caller again, introduce yourself again, or ask for their name again" in note


def test_ending_never_comes_from_pauses():
    assert "Never end the call during an ordinary pause" in vapi.CALL_CLOSING_NOTE
