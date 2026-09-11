"""
W6A2-D3.1 — the reschedule tool goes only to tenants that can finish the job.

THE DEAD END THIS CLOSES
D3 added reschedule_appointment to build_calendar_tools(), which is assembled
whenever has_calendar is true — Google OR Microsoft OR Square Appointments. But
the flow needs an opaque slot_ref, and slot_refs are minted by exactly ONE code
path: the multi-location Square availability branch. A Google tenant could
therefore start a move, be told to fetch availability, never receive a slot_ref,
and loop — after the assistant had already promised the caller their appointment
would be moved.

Nothing was ever destroyed by that: every path fails closed. What it cost was
truthfulness, which on a phone call is the whole product.

THE TWO HALVES MUST AGREE
The tool list and the prompt are chosen from the same predicate. Handing the
model a policy that says "call reschedule_appointment" while withholding the tool
is the same bug wearing different clothes, so both are asserted together here.
"""
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from services import vapi

TID = "t1"


def tools_for(**flags):
    return {t["function"]["name"]
            for t in vapi.build_calendar_tools(TID, **flags)}


def tenant(**kw):
    base = {"id": "tenant-uuid", "square_appointments_enabled": False,
            "google_refresh_token": None, "microsoft_refresh_token": None}
    return {**base, **kw}


@pytest.fixture
def multi_location():
    def _patch(is_multi):
        return patch("services.call_location.is_multi_location",
                     new=AsyncMock(return_value=(is_multi, [])))
    return _patch


# ── the capability predicate ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_predicate_true_only_for_square_plus_multi_location(multi_location):
    with multi_location(True):
        assert await vapi.supports_safe_reschedule(
            tenant(square_appointments_enabled=True)) is True


@pytest.mark.asyncio
async def test_predicate_false_for_square_without_multi_location(multi_location):
    """D — a Square tenant on the legacy single-location path mints no slot_refs."""
    with multi_location(False):
        assert await vapi.supports_safe_reschedule(
            tenant(square_appointments_enabled=True)) is False


@pytest.mark.asyncio
async def test_predicate_false_for_google_only(multi_location):
    with multi_location(True):          # even if it somehow had locations
        assert await vapi.supports_safe_reschedule(
            tenant(google_refresh_token="x")) is False


@pytest.mark.asyncio
async def test_predicate_false_for_microsoft_only(multi_location):
    with multi_location(True):
        assert await vapi.supports_safe_reschedule(
            tenant(microsoft_refresh_token="x")) is False


@pytest.mark.asyncio
async def test_predicate_fails_closed_when_the_location_check_raises():
    with patch("services.call_location.is_multi_location",
               new=AsyncMock(side_effect=RuntimeError("db down"))):
        assert await vapi.supports_safe_reschedule(
            tenant(square_appointments_enabled=True)) is False


@pytest.mark.asyncio
async def test_predicate_fails_closed_without_a_tenant_id(multi_location):
    with multi_location(True):
        assert await vapi.supports_safe_reschedule(
            {"square_appointments_enabled": True}) is False


# ── A/F: the supported Square multi-location tenant keeps everything ──────────

def test_A_supported_tenant_gets_the_full_tool_set():
    names = tools_for(supports_reschedule=True)
    assert names == {"caller_lookup", "check_availability", "book_appointment",
                     "cancel_appointment", "reschedule_appointment"}


def test_F_dani_like_tenant_still_gets_the_reschedule_tool():
    assert "reschedule_appointment" in tools_for(supports_reschedule=True)


def test_G_supported_schema_is_still_exactly_the_two_opaque_refs():
    t = next(x for x in vapi.build_calendar_tools(TID, supports_reschedule=True)
             if x["function"]["name"] == "reschedule_appointment")
    params = t["function"]["parameters"]
    assert set(params["properties"]) == {"appointment_ref", "slot_ref"}
    assert params["required"] == []


# ── B/C/D/E: unsupported providers ───────────────────────────────────────────

def test_B_C_D_unsupported_tenant_does_not_get_the_reschedule_tool():
    names = tools_for()
    assert "reschedule_appointment" not in names


def test_B_cancellation_survives_for_unsupported_tenants():
    """The scope change touches reschedule ONLY. Safe cancellation is untouched."""
    names = tools_for()
    assert "cancel_appointment" in names
    t = next(x for x in vapi.build_calendar_tools(TID)
             if x["function"]["name"] == "cancel_appointment")
    assert set(t["function"]["parameters"]["properties"]) == {"appointment_ref"}


def test_B_ordinary_booking_and_availability_survive_for_unsupported_tenants():
    names = tools_for()
    assert {"book_appointment", "check_availability", "caller_lookup"} <= names
    book = next(x for x in vapi.build_calendar_tools(TID)
                if x["function"]["name"] == "book_appointment")
    # byte-identical to the supported tenant's booking tool
    book_on = next(x for x in vapi.build_calendar_tools(TID, supports_reschedule=True)
                   if x["function"]["name"] == "book_appointment")
    assert book == book_on


def test_the_only_difference_between_the_two_tool_sets_is_the_reschedule_tool():
    off = vapi.build_calendar_tools(TID)
    on = vapi.build_calendar_tools(TID, supports_reschedule=True)
    assert on[:len(off)] == off
    assert len(on) == len(off) + 1
    assert on[-1]["function"]["name"] == "reschedule_appointment"


def test_E_no_calendar_tenant_is_unaffected():
    """A tenant with no calendar never reaches build_calendar_tools at all."""
    src = inspect.getsource(__import__("routers.webhooks", fromlist=["x"]))
    assert "build_calendar_tools(tenant_id, supports_reschedule=can_reschedule)" in src
    assert "else [build_caller_lookup_tool(tenant_id)]" in src


# ── §3: the prompt must agree with the tool list ─────────────────────────────

def test_unsupported_prompt_says_moving_is_not_supported():
    note = vapi.caller_lookup_note(supports_reschedule=False)
    assert "MOVING AN EXISTING APPOINTMENT — NOT SUPPORTED" in note
    assert "not something you can do" in note
    assert "never offer cancelling as a way to move one" in note
    assert "Never tell a caller their appointment has been moved" in note


def test_unsupported_prompt_never_mentions_the_absent_tool():
    """appointment_ref still appears — it belongs to CANCELLING, which is
    unaffected. What must be absent is the reschedule tool and its slot_ref."""
    note = vapi.caller_lookup_note(supports_reschedule=False)
    assert "reschedule_appointment" not in note
    assert "slot_ref" not in note
    assert "BOTH the appointment_ref and the slot_ref" not in note
    # the only appointment_ref instruction left is the cancellation one
    assert "cancel_appointment again with the appointment_ref" in note


def test_supported_prompt_describes_the_real_flow():
    note = vapi.caller_lookup_note(supports_reschedule=True)
    assert "MOVING AN EXISTING APPOINTMENT" in note
    assert "NOT SUPPORTED" not in note
    assert "reschedule_appointment" in note
    assert "BOTH the appointment_ref and the slot_ref" in note
    assert ("Do NOT call reschedule_appointment, book_appointment or "
            "cancel_appointment again to try to fix it") in note


def test_both_policies_forbid_cancel_then_rebook():
    for flag in (True, False):
        note = vapi.caller_lookup_note(supports_reschedule=flag).lower()
        assert "cancel" in note and "book" in note
        assert "must not chain them" in note or "must never chain them" in note


def test_the_module_constant_defaults_to_the_safe_policy():
    """Every call site that was not updated keeps today's truthful behaviour."""
    assert vapi._CALLER_LOOKUP_NOTE == vapi.caller_lookup_note()
    assert "NOT SUPPORTED" in vapi._CALLER_LOOKUP_NOTE
    assert "reschedule_appointment" not in vapi._CALLER_LOOKUP_NOTE


def test_cancelling_instructions_are_present_in_both_policies():
    for flag in (True, False):
        note = vapi.caller_lookup_note(supports_reschedule=flag)
        assert "CANCELLING" in note
        assert "call cancel_appointment with NO arguments first" in note


# ── H: the live path computes the flag and uses it for BOTH halves ───────────

def test_H_the_live_call_path_gates_tools_and_prompt_on_the_same_predicate():
    from routers import webhooks
    src = inspect.getsource(webhooks)
    assert "can_reschedule = await supports_safe_reschedule(tenant)" in src
    assert "caller_lookup_note(supports_reschedule=can_reschedule)" in src
    assert "build_calendar_tools(tenant_id, supports_reschedule=can_reschedule)" in src
    # the old unconditional forms are gone
    assert "system_prompt += _CALLER_LOOKUP_NOTE" not in src
    assert "build_calendar_tools(tenant_id) if has_calendar" not in src


def test_H_an_unsupported_tenant_cannot_be_handed_the_tool_by_default():
    """The default is the safety property: forgetting the flag removes the tool
    rather than shipping one the tenant cannot honour."""
    import inspect as _i
    sig = _i.signature(vapi.build_calendar_tools)
    assert sig.parameters["supports_reschedule"].default is False
    assert sig.parameters["supports_reschedule"].kind is _i.Parameter.KEYWORD_ONLY


def test_H_the_endpoint_still_exists_and_is_unchanged_by_scoping():
    """Scoping changes EXPOSURE only. The server route is untouched, so a tenant
    that is genuinely capable still reaches the same D1/D2 engine."""
    from routers import tools as tools_router
    src = inspect.getsource(tools_router)
    assert '@router.post("/{tenant_id}/reschedule")' in src
    assert "reschedule_intent.move_appointment" in src
