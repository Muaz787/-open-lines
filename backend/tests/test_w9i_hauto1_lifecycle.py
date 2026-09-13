"""W9I-H.AUTO.1 — the Irish lifecycle spine.

W9I-H.AUTO found three complete orchestration units with no production caller.
These pin the driver that now connects them, and the policy it enforces.

THE TWO PROPERTIES EVERYTHING ELSE SERVES
  * a free line is handed out only on provider-verified genuine review, and
  * the seven-day trial begins only when a permanent +353 is live -- no amount
    of temporary testing moves it earlier.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db import ireland_temp_access as ita
from services import ireland_lifecycle as il
from services import phone_lifecycle as pl
from services import temporary_numbers as temp
from tests.module_identifiers import identifiers

T = "11111111-2222-4333-8444-555555555555"


def _tenant(**o):
    return {"id": T, "business_name": "Acme IE", "business_country_code": "IE",
            "twilio_subaccount_sid": "AC_sub", "twilio_auth_token": "tok",
            "vapi_assistant_id": "asst_1", **o}


def _profile(**o):
    return {"id": "p1", "tenant_id": T, "iso_country": "IE",
            "bundle_sid": "BU123", "provider_account_sid": "AC_sub",
            "state": "pending_review", **o}


def _access(**o):
    return {"tenant_id": T, "provider_attempt_at": None, "e164": None,
            "provider_sid": None, "seconds_used": 0, "access_started_at": None,
            "action_required_at": None, "rejected_at": None, "cutover_at": None,
            "suspended_at": None, "suspend_reason": None,
            "retirement_claimed_at": None, "released_at": None, **o}


def _phone(purpose, status, e164="+14165550100"):
    return {"id": "r1", "tenant_id": T, "e164": e164, "purpose": purpose,
            "status": status, "provider_sid": "PN1", "provider_account_sid": "AC_sub"}


def _bundle(status):
    return MagicMock(status=status, account_sid="AC_sub")


def _provider(status, *, raises=None):
    """A fake Twilio regulatory client returning one Bundle status."""
    client = MagicMock()
    fetch = client.numbers.v2.regulatory_compliance.bundles.return_value.fetch
    if raises:
        fetch.side_effect = raises
    else:
        fetch.return_value = _bundle(status)
    return client


# ═══ 1. the provider is the authority ════════════════════════════════════

@pytest.mark.asyncio
async def test_a_local_pending_state_alone_cannot_buy_a_free_line():
    """THE defect this gate closes. tenant_regulatory_profiles.state is a memory
    of a delivery; a stale or forged one must buy nobody anything."""
    with patch.object(il.db_reg, "list_profiles",
                      new=AsyncMock(return_value=[_profile(state="pending_review")])), \
         patch.object(il.telephony, "regulatory_client",
                      return_value=_provider("draft")), \
         patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[])), \
         patch.object(il.temporary_numbers, "ensure_temporary_number",
                      new=AsyncMock(side_effect=AssertionError("BOUGHT A NUMBER"))):
        out = await il.advance(T)
    assert out["outcome"] == il.AWAITING_CUSTOMER
    assert out["provider_status"] == "draft"


@pytest.mark.parametrize("provider_status", [
    "draft", "pending-review", "in-review", "twilio-approved",
    "twilio-rejected", "provisionally-approved", "",
])
@pytest.mark.asyncio
async def test_the_provider_status_is_read_fresh_every_time(provider_status):
    client = _provider(provider_status)
    with patch.object(il.db_reg, "list_profiles",
                      new=AsyncMock(return_value=[_profile()])), \
         patch.object(il.telephony, "regulatory_client", return_value=client):
        state = await il.provider_filing_state(_tenant())
    assert state["known"] is True
    assert state["status"] == provider_status
    assert client.numbers.v2.regulatory_compliance.bundles.called


@pytest.mark.parametrize("boom", [
    TimeoutError("timed out"), RuntimeError("HTTP 401"),
    RuntimeError("HTTP 429"), RuntimeError("HTTP 500"),
])
@pytest.mark.asyncio
async def test_a_provider_outage_is_unknown_not_rejection(boom):
    """An outage must not issue a line, suspend one, or decide anything."""
    with patch.object(il.db_reg, "list_profiles",
                      new=AsyncMock(return_value=[_profile()])), \
         patch.object(il.telephony, "regulatory_client",
                      return_value=_provider(None, raises=boom)):
        state = await il.provider_filing_state(_tenant())
    assert state["known"] is False
    assert state["status"] == ""


@pytest.mark.asyncio
async def test_an_outage_stops_the_driver_without_side_effects():
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[])), \
         patch.object(il, "provider_filing_state",
                      new=AsyncMock(return_value={"known": False, "status": "",
                                                  "reason": "TimeoutError"})), \
         patch.object(il.temporary_numbers, "ensure_temporary_number",
                      new=AsyncMock(side_effect=AssertionError("BOUGHT"))), \
         patch.object(il.permanent_numbers, "ensure_permanent_irish_number",
                      new=AsyncMock(side_effect=AssertionError("BOUGHT +353"))), \
         patch.object(il.ita, "suspend",
                      new=AsyncMock(side_effect=AssertionError("SUSPENDED"))):
        out = await il.advance(T)
    assert out["outcome"] == il.PROVIDER_UNKNOWN


@pytest.mark.asyncio
async def test_a_bundle_on_another_account_is_never_believed():
    client = MagicMock()
    client.numbers.v2.regulatory_compliance.bundles.return_value.fetch.return_value = \
        MagicMock(status="twilio-approved", account_sid="AC_someone_else")
    with patch.object(il.db_reg, "list_profiles",
                      new=AsyncMock(return_value=[_profile()])), \
         patch.object(il.telephony, "regulatory_client", return_value=client):
        state = await il.provider_filing_state(_tenant())
    assert state["known"] is False
    assert state["reason"] == "bundle_account_mismatch"


@pytest.mark.asyncio
async def test_a_profile_not_on_the_tenants_subaccount_is_skipped():
    with patch.object(il.db_reg, "list_profiles", new=AsyncMock(
            return_value=[_profile(provider_account_sid="AC_other")])), \
         patch.object(il.telephony, "regulatory_client",
                      side_effect=AssertionError("READ SOMEONE ELSE'S BUNDLE")):
        state = await il.provider_filing_state(_tenant())
    assert state["reason"] == "no_owned_filing"


# ═══ 2. temporary acquisition needs proof, in the signature ══════════════

@pytest.mark.parametrize("bad", ["", "draft", "twilio-approved", "twilio-rejected",
                                 "pending_review", None])
@pytest.mark.asyncio
async def test_acquisition_refuses_anything_that_is_not_verified_review(bad):
    """`pending_review` with an underscore is OUR local value, not the
    provider's -- it must not be accepted as provider proof."""
    with patch.object(temp, "get_client",
                      side_effect=AssertionError("REACHED THE DATABASE")):
        out = await temp.ensure_temporary_number(T, verified_provider_status=bad)
    assert out["status"] == temp.NOT_ELIGIBLE
    assert out["reason"] == "provider_review_not_verified"


def test_the_proof_parameter_has_no_default():
    """So acquiring without provider proof is not something a caller can do by
    forgetting a keyword."""
    import inspect
    sig = inspect.signature(temp.ensure_temporary_number)
    param = sig.parameters["verified_provider_status"]
    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_the_eligible_provider_states_exclude_every_decided_one():
    for forbidden in ("draft", "twilio-approved", "twilio-rejected", "rejected",
                      "action-required", "expired", "", "pending_review"):
        assert forbidden not in temp.PROVIDER_REVIEW_STATES, forbidden
    assert set(temp.PROVIDER_REVIEW_STATES) == set(il.PROVIDER_REVIEW_STATES)


# ═══ 3. the attempt boundary and unambiguous adoption ════════════════════

@pytest.mark.asyncio
async def test_an_unconfirmed_purchase_never_buys_a_second_number():
    """An attempt is recorded; the response was lost. Time is not evidence."""
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[])), \
         patch.object(il, "provider_filing_state", new=AsyncMock(
             return_value={"known": True, "status": "pending-review",
                           "profile": _profile()})), \
         patch.object(il.ita, "claim", new=AsyncMock(return_value=False)), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=_access(
             provider_attempt_at="2020-01-01T00:00:00+00:00"))), \
         patch.object(il.tenant_subaccount, "ensure", new=AsyncMock(
             return_value={"status": il.tenant_subaccount.OK,
                           "sid": "AC_sub", "auth_token": "tok"})), \
         patch.object(il.temporary_numbers, "held_numbers", new=AsyncMock(
             return_value={"status": temp.OK, "numbers": []})), \
         patch.object(il.temporary_numbers, "ensure_temporary_number",
                      new=AsyncMock(side_effect=AssertionError("BOUGHT AGAIN"))):
        out = await il.advance(T)
    assert out["outcome"] == il.TEMP_BLOCKED
    assert out["reason"] == "purchase_outcome_unresolved"


@pytest.mark.asyncio
async def test_an_unconfirmed_purchase_adopts_the_one_number_held():
    attached = {}

    async def attach(*, tenant_id, e164, provider_sid):
        attached.update({"e164": e164, "sid": provider_sid})
        return True

    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[])), \
         patch.object(il, "provider_filing_state", new=AsyncMock(
             return_value={"known": True, "status": "in-review", "profile": _profile()})), \
         patch.object(il.ita, "claim", new=AsyncMock(return_value=False)), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=_access(
             provider_attempt_at="2026-01-01T00:00:00+00:00"))), \
         patch.object(il.tenant_subaccount, "ensure", new=AsyncMock(
             return_value={"status": il.tenant_subaccount.OK,
                           "sid": "AC_sub", "auth_token": "tok"})), \
         patch.object(il.temporary_numbers, "held_numbers", new=AsyncMock(
             return_value={"status": temp.OK,
                           "numbers": [{"e164": "+14165550100", "sid": "PN9"}]})), \
         patch.object(il.ita, "attach_number", new=attach), \
         patch.object(il.temporary_numbers, "ensure_temporary_number",
                      new=AsyncMock(side_effect=AssertionError("BOUGHT AGAIN"))):
        out = await il.advance(T)
    assert out["outcome"] == il.TEMP_PROVISIONED and out["adopted"] is True
    assert attached == {"e164": "+14165550100", "sid": "PN9"}


@pytest.mark.asyncio
async def test_two_held_numbers_are_ambiguous_and_nothing_is_adopted():
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[])), \
         patch.object(il, "provider_filing_state", new=AsyncMock(
             return_value={"known": True, "status": "in-review", "profile": _profile()})), \
         patch.object(il.ita, "claim", new=AsyncMock(return_value=False)), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=_access(
             provider_attempt_at="2026-01-01T00:00:00+00:00"))), \
         patch.object(il.tenant_subaccount, "ensure", new=AsyncMock(
             return_value={"status": il.tenant_subaccount.OK,
                           "sid": "AC_sub", "auth_token": "tok"})), \
         patch.object(il.temporary_numbers, "held_numbers", new=AsyncMock(
             return_value={"status": temp.OK, "numbers": [
                 {"e164": "+14165550100", "sid": "PN1"},
                 {"e164": "+14165550200", "sid": "PN2"}]})), \
         patch.object(il.ita, "attach_number",
                      new=AsyncMock(side_effect=AssertionError("GUESSED"))):
        out = await il.advance(T)
    assert out["outcome"] == il.TEMP_BLOCKED
    assert out["reason"] == "ambiguous_provider_inventory"


def test_pick_unambiguous_refuses_to_guess():
    one = {"e164": "+1", "sid": "PN1"}
    assert temp.pick_unambiguous([one]) == one
    assert temp.pick_unambiguous([]) is None
    assert temp.pick_unambiguous([one, {"e164": "+2", "sid": "PN2"}]) is None


# ═══ 4. the allowance ════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_temporary_minutes_never_reach_billing():
    """record_call_minutes accumulates into the plan allocation AND can
    auto-convert a card trial. A free test call must not go near it."""
    with patch.object(il, "is_temporary_line", new=AsyncMock(return_value=True)), \
         patch.object(il.ita, "consume_seconds", new=AsyncMock(
             return_value={"seconds_used": 120, "suspended_at": None})), \
         patch.object(il.ita, "suspend", new=AsyncMock()):
        free = await il.record_temporary_usage(
            tenant_id=T, called_number="+14165550100", duration_secs=120)
    assert free is True


@pytest.mark.asyncio
async def test_a_permanent_line_call_is_billed_normally():
    with patch.object(il, "is_temporary_line", new=AsyncMock(return_value=False)), \
         patch.object(il.ita, "consume_seconds",
                      new=AsyncMock(side_effect=AssertionError("SPENT ALLOWANCE"))):
        free = await il.record_temporary_usage(
            tenant_id=T, called_number="+353871234567", duration_secs=120)
    assert free is False


@pytest.mark.asyncio
async def test_crossing_the_allowance_suspends_testing():
    suspended = {}

    async def suspend(*, tenant_id, reason):
        suspended.update({"tenant": tenant_id, "reason": reason})
        return True

    with patch.object(il, "is_temporary_line", new=AsyncMock(return_value=True)), \
         patch.object(il.ita, "consume_seconds", new=AsyncMock(
             return_value={"seconds_used": il.FREE_SECONDS, "suspended_at": None})), \
         patch.object(il.ita, "suspend", new=suspend):
        await il.record_temporary_usage(tenant_id=T, called_number="+1416",
                                        duration_secs=60)
    assert suspended["reason"] == il.SUSPEND_ALLOWANCE


def test_the_allowance_is_sixty_minutes():
    assert il.FREE_SECONDS == 3600


@pytest.mark.asyncio
async def test_the_allowance_lives_on_the_lifecycle_not_the_number():
    """So replacing, retiring or re-acquiring a number cannot reset it."""
    import inspect
    src = inspect.getsource(ita)
    assert 'TABLE = "ireland_temporary_access"' in src
    # There is no statement anywhere here that lowers a spent allowance.
    for reset in ('"seconds_used": 0', "seconds_used=0", "seconds_used = 0"):
        assert reset not in src, reset


def test_claiming_an_existing_lifecycle_row_is_not_a_reset():
    import inspect
    src = inspect.getsource(ita.claim)
    assert "insert" in src and "update" not in src


# ═══ 5. fraud: inbound only ══════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_transfer_is_refused_on_a_temporary_line():
    with patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(
            return_value=[_phone(pl.PURPOSE_TEMPORARY, pl.STATUS_ACTIVE)])):
        assert await il.transfer_allowed(T) is False


@pytest.mark.asyncio
async def test_a_transfer_is_allowed_once_the_permanent_line_is_live():
    with patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[
            _phone(pl.PURPOSE_TEMPORARY, pl.STATUS_ACTIVE),
            _phone(pl.PURPOSE_PERMANENT, pl.STATUS_ACTIVE, "+353871234567")])):
        assert await il.transfer_allowed(T) is True


@pytest.mark.asyncio
async def test_an_ordinary_tenant_is_unaffected():
    with patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(
            return_value=[_phone(pl.PURPOSE_PERMANENT, pl.STATUS_ACTIVE)])):
        assert await il.transfer_allowed(T) is True


def test_the_transfer_refusal_is_server_side_not_a_prompt():
    import inspect
    from routers import tools
    src = inspect.getsource(tools)
    i = src.index("ireland_lifecycle.transfer_allowed")
    j = src.index("entitlements.transfer_execution_enabled", i - 2000)
    assert i < j, "the temporary-line refusal must precede the entitlement check"


# ═══ 6. the clocks ══════════════════════════════════════════════════════

def test_the_approved_durations():
    assert (il.PENDING_DAYS, il.ACTION_REQUIRED_DAYS, il.REJECTED_DAYS,
            il.CUTOVER_HOURS) == (30, 14, 7, 24)


@pytest.mark.parametrize("column,days,reason", [
    ("rejected_at", il.REJECTED_DAYS, il.SUSPEND_REJECTED),
    ("action_required_at", il.ACTION_REQUIRED_DAYS, il.SUSPEND_ACTION_EXPIRED),
    ("access_started_at", il.PENDING_DAYS, il.SUSPEND_PENDING_EXPIRED),
])
@pytest.mark.asyncio
async def test_each_deadline_suspends_when_it_expires(column, days, reason):
    old = (datetime.now(timezone.utc) - timedelta(days=days + 1)).isoformat()
    suspended = {}

    async def suspend(*, tenant_id, reason):
        suspended["reason"] = reason
        return True

    with patch.object(il.ita, "suspend", new=suspend):
        out = await il._enforce(_tenant(), _access(**{column: old}), "pending-review")
    assert out["outcome"] == il.TEMP_SUSPENDED
    assert suspended["reason"] == reason


@pytest.mark.parametrize("column,days", [
    ("rejected_at", il.REJECTED_DAYS),
    ("action_required_at", il.ACTION_REQUIRED_DAYS),
    ("access_started_at", il.PENDING_DAYS),
])
@pytest.mark.asyncio
async def test_a_deadline_that_has_not_expired_does_nothing(column, days):
    recent = (datetime.now(timezone.utc) - timedelta(days=days - 1)).isoformat()
    with patch.object(il.ita, "suspend",
                      new=AsyncMock(side_effect=AssertionError("SUSPENDED EARLY"))):
        out = await il._enforce(_tenant(), _access(**{column: recent}), "pending-review")
    assert out["outcome"] == il.NOTHING_TO_DO


@pytest.mark.asyncio
async def test_a_correction_does_not_restart_the_thirty_day_lifetime():
    """Otherwise a customer earns a fresh month by cycling through corrections.

    Parsed, not grepped: the docstring is allowed to name access_started_at
    precisely because the code must leave it alone."""
    import ast, inspect, textwrap
    fn = ast.parse(textwrap.dedent(
        inspect.getsource(ita.clear_action_required))).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    code = ast.unparse(fn)
    assert "action_required_at" in code
    assert "access_started_at" not in code
    for clock in ("rejected_at", "cutover_at", "seconds_used"):
        assert clock not in code, clock


def test_a_clock_is_never_restamped():
    """A pass that runs hourly must not push a 14-day window 14 hours further."""
    import inspect
    src = inspect.getsource(ita._start_clock)
    assert '.is_(column, "null")' in src


@pytest.mark.asyncio
async def test_an_exhausted_allowance_outranks_an_unexpired_deadline():
    with patch.object(il.ita, "suspend", new=AsyncMock(return_value=True)):
        out = await il._enforce(_tenant(), _access(seconds_used=il.FREE_SECONDS),
                                "pending-review")
    assert out["reason"] == il.SUSPEND_ALLOWANCE


@pytest.mark.asyncio
async def test_an_already_suspended_lifecycle_is_not_resuspended():
    with patch.object(il.ita, "suspend",
                      new=AsyncMock(side_effect=AssertionError("RE-SUSPENDED"))):
        out = await il._enforce(_tenant(),
                                _access(suspended_at="2026-01-01T00:00:00+00:00",
                                        suspend_reason=il.SUSPEND_ALLOWANCE),
                                "pending-review")
    assert out["already"] is True


# ═══ 7. the commercial boundary ═════════════════════════════════════════

def test_the_driver_never_starts_a_trial_or_sends_an_email():
    """Both belong to permanent_activation, after a healthy permanent line."""
    refs = identifiers(il)
    for forbidden in ("create_trial_subscription", "record_call_minutes",
                      "send_welcome_email", "Subscription", "MeterEvent"):
        assert forbidden not in refs, forbidden


@pytest.mark.asyncio
async def test_a_live_temporary_line_never_triggers_activation():
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(
             return_value=[_phone(pl.PURPOSE_TEMPORARY, pl.STATUS_ACTIVE)])), \
         patch.object(il, "provider_filing_state", new=AsyncMock(
             return_value={"known": True, "status": "pending-review",
                           "profile": _profile()})), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=_access(
             e164="+14165550100", provider_attempt_at="2026-01-01T00:00:00+00:00"))), \
         patch.object(il.ita, "claim", new=AsyncMock(return_value=False)), \
         patch.object(il.ita, "start_access", new=AsyncMock(return_value=True)), \
         patch.object(il.permanent_activation, "activate_permanent_irish_number",
                      new=AsyncMock(side_effect=AssertionError("ACTIVATED"))):
        out = await il.advance(T)
    assert out["outcome"] == il.NOTHING_TO_DO


# ═══ 8. approval → permanent ════════════════════════════════════════════

@pytest.mark.asyncio
async def test_verified_approval_acquires_the_permanent_number():
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[])), \
         patch.object(il, "provider_filing_state", new=AsyncMock(
             return_value={"known": True, "status": "twilio-approved",
                           "profile": _profile()})), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=_access())), \
         patch.object(il.permanent_numbers, "ensure_permanent_irish_number",
                      new=AsyncMock(return_value={"status": il.permanent_numbers.OK})) as buy:
        out = await il.advance(T)
    assert out["outcome"] == il.PERMANENT_ACQUIRED
    buy.assert_awaited_once_with(T)


@pytest.mark.asyncio
async def test_a_provisioning_permanent_number_is_activated():
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(
             return_value=[_phone(pl.PURPOSE_PERMANENT, pl.STATUS_PROVISIONING,
                                  "+353871234567")])), \
         patch.object(il.permanent_activation, "activate_permanent_irish_number",
                      new=AsyncMock(return_value={"status": il.permanent_activation.OK})), \
         patch.object(il.ita, "start_cutover", new=AsyncMock(return_value=True)), \
         patch.object(il, "provider_filing_state",
                      new=AsyncMock(side_effect=AssertionError("RE-READ PROVIDER"))):
        out = await il.advance(T)
    assert out["outcome"] == il.PERMANENT_ACTIVATED


@pytest.mark.asyncio
async def test_acquisition_and_activation_are_separate_passes():
    """So each is independently restartable after a crash between them."""
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[])), \
         patch.object(il, "provider_filing_state", new=AsyncMock(
             return_value={"known": True, "status": "twilio-approved",
                           "profile": _profile()})), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=_access())), \
         patch.object(il.permanent_numbers, "ensure_permanent_irish_number",
                      new=AsyncMock(return_value={"status": il.permanent_numbers.OK})), \
         patch.object(il.permanent_activation, "activate_permanent_irish_number",
                      new=AsyncMock(side_effect=AssertionError("SAME PASS"))):
        await il.advance(T)


# ═══ 9. cutover and retirement ══════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_temporary_line_survives_the_cutover_window():
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[
             _phone(pl.PURPOSE_PERMANENT, pl.STATUS_ACTIVE, "+353871234567"),
             _phone(pl.PURPOSE_TEMPORARY, pl.STATUS_ACTIVE)])), \
         patch.object(il.ita, "start_cutover", new=AsyncMock(return_value=False)), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=_access(cutover_at=recent))), \
         patch.object(il.telephony, "release_number",
                      new=AsyncMock(side_effect=AssertionError("RELEASED EARLY"))):
        out = await il.advance(T)
    assert out["outcome"] == il.NOTHING_TO_DO
    assert out["reason"] == "within_cutover_grace"


@pytest.mark.asyncio
async def test_the_temporary_line_retires_after_the_cutover_window():
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[
             _phone(pl.PURPOSE_PERMANENT, pl.STATUS_ACTIVE, "+353871234567"),
             _phone(pl.PURPOSE_TEMPORARY, pl.STATUS_ACTIVE)])), \
         patch.object(il.ita, "start_cutover", new=AsyncMock(return_value=False)), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=_access(cutover_at=old))), \
         patch.object(il.ita, "claim_retirement", new=AsyncMock(return_value=True)), \
         patch.object(il.ita, "mark_released", new=AsyncMock(return_value=True)), \
         patch.object(il.telephony, "release_number", new=AsyncMock(return_value=True)), \
         patch.object(il.phone_registry, "mark_released",
                      new=AsyncMock(return_value={"status": "ok"})):
        out = await il.advance(T)
    assert out["outcome"] == il.TEMP_RETIRED


@pytest.mark.asyncio
async def test_retirement_never_releases_a_permanent_number():
    """The permanent row is unreachable from here by construction."""
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(
             return_value=[_phone(pl.PURPOSE_PERMANENT, pl.STATUS_ACTIVE,
                                  "+353871234567")])), \
         patch.object(il.telephony, "release_number",
                      new=AsyncMock(side_effect=AssertionError("RELEASED PERMANENT"))):
        out = await il.retire_temporary(T)
    assert out["outcome"] == il.NOTHING_TO_DO
    assert out["reason"] == "no_live_temporary_number"


@pytest.mark.asyncio
async def test_only_one_worker_releases_the_number():
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(
             return_value=[_phone(pl.PURPOSE_TEMPORARY, pl.STATUS_ACTIVE)])), \
         patch.object(il.ita, "claim_retirement", new=AsyncMock(return_value=False)), \
         patch.object(il.telephony, "release_number",
                      new=AsyncMock(side_effect=AssertionError("SECOND RELEASE"))):
        out = await il.retire_temporary(T)
    assert out["reason"] == "retirement_already_claimed"


@pytest.mark.asyncio
async def test_an_unconfirmed_release_does_not_update_the_books():
    """"We asked and something went wrong" is not proof the number is gone."""
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(
             return_value=[_phone(pl.PURPOSE_TEMPORARY, pl.STATUS_ACTIVE)])), \
         patch.object(il.ita, "claim_retirement", new=AsyncMock(return_value=True)), \
         patch.object(il.telephony, "release_number",
                      new=AsyncMock(side_effect=TimeoutError("lost"))), \
         patch.object(il.phone_registry, "mark_released",
                      new=AsyncMock(side_effect=AssertionError("MARKED RELEASED"))):
        out = await il.retire_temporary(T)
    assert out["reason"] == "release_outcome_unknown"


# ═══ 10. wake-ups converge ══════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_wake_up_never_raises():
    with patch.object(il, "advance", new=AsyncMock(side_effect=RuntimeError("boom"))):
        out = await il.wake(T, source="callback")
    assert out["outcome"] == il.NOTHING_TO_DO


@pytest.mark.asyncio
async def test_repeated_wake_ups_converge():
    """Three identical passes over an already-provisioned lifecycle buy nothing."""
    calls = []
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(return_value=[])), \
         patch.object(il, "provider_filing_state", new=AsyncMock(
             return_value={"known": True, "status": "pending-review",
                           "profile": _profile()})), \
         patch.object(il.ita, "claim", new=AsyncMock(return_value=False)), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=_access(
             e164="+14165550100", provider_attempt_at="2026-01-01T00:00:00+00:00"))), \
         patch.object(il.ita, "start_access", new=AsyncMock(return_value=False)), \
         patch.object(il.temporary_numbers, "ensure_temporary_number",
                      new=AsyncMock(side_effect=lambda *a, **k: calls.append(1))):
        for _ in range(3):
            out = await il.advance(T)
    assert calls == []
    assert out["reason"] == "temporary_number_already_held"


def test_the_callback_is_a_wake_up_and_not_an_authority():
    import inspect
    from routers import regulatory
    src = inspect.getsource(regulatory)
    assert "ireland_lifecycle.wake" in src
    for forbidden in ("ensure_permanent_irish_number", "ensure_temporary_number",
                      "create_trial_subscription"):
        assert forbidden not in src, forbidden


# ═══ 11. Vapi fails closed ══════════════════════════════════════════════

def test_a_tenant_without_a_suborg_key_is_unchanged():
    from services import vapi
    assert vapi.resolve_tenant_key({"id": "t"}) == {
        "ok": True, "key": None, "reason": "no_suborg_key"}


def test_an_undecryptable_key_fails_closed():
    from services import vapi
    with patch("services.security.decrypt", side_effect=ValueError("bad key")):
        out = vapi.resolve_tenant_key({"id": "t", "vapi_suborg_api_key": "enc"})
    assert out["ok"] is False and out["key"] is None


@pytest.mark.asyncio
async def test_provisioning_stops_rather_than_using_the_parent_pool():
    from services import vapi
    tenant = _tenant(vapi_suborg_api_key="broken")
    with patch.object(temp.phone_registry, "register_temporary", new=AsyncMock(
            return_value={"status": temp.phone_registry.OK,
                          "row": _phone(pl.PURPOSE_TEMPORARY, pl.STATUS_PROVISIONING)})), \
         patch.object(vapi, "resolve_tenant_key",
                      return_value={"ok": False, "key": None,
                                    "reason": vapi.KEY_UNAVAILABLE}), \
         patch.object(vapi, "import_twilio_number",
                      new=AsyncMock(side_effect=AssertionError("PROVISIONED SHARED"))):
        out = await temp._register_and_activate(
            tenant=tenant, e164="+14165550100", provider_sid="PN1",
            sub_sid="AC_sub", sub_tok="tok", iso_country="CA", adopted=False)
    assert out["reason"] == vapi.KEY_UNAVAILABLE


# ═══ 12. the acquisition path's own ambiguity refusal ════════════════════

@pytest.mark.asyncio
async def test_acquisition_refuses_to_guess_among_held_numbers():
    """Not just the reconciliation path -- the ordinary adopt-before-buy step
    must refuse too, or a tenant with two stray numbers gets one at random."""
    tenant = _tenant()
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value \
        .limit.return_value.execute.return_value.data = [tenant]
    with patch.object(temp, "get_client", return_value=client), \
         patch.object(temp, "eligibility", new=AsyncMock(return_value={
             "eligible": True, "reason": "", "detail": "", "profile": _profile(),
             "existing": None, "active": False})), \
         patch.dict(__import__("os").environ,
                    {temp.ENABLED_ENV: "true", temp.SOURCE_ENV: "CA"}), \
         patch.object(temp.tenant_subaccount, "ensure", new=AsyncMock(
             return_value={"status": temp.tenant_subaccount.OK,
                           "sid": "AC_sub", "auth_token": "tok"})), \
         patch.object(temp, "held_numbers", new=AsyncMock(return_value={
             "status": temp.OK, "numbers": [
                 {"e164": "+14165550100", "sid": "PN1"},
                 {"e164": "+14165550200", "sid": "PN2"}]})), \
         patch.object(temp, "_register_and_activate",
                      new=AsyncMock(side_effect=AssertionError("ADOPTED A GUESS"))), \
         patch.object(temp.telephony, "purchase_number_with_sid",
                      new=AsyncMock(side_effect=AssertionError("BOUGHT ANOTHER"))):
        out = await temp.ensure_temporary_number(
            T, verified_provider_status="pending-review")
    assert out["status"] == temp.PURCHASE_OUTCOME_UNKNOWN
    assert out["reason"] == "multiple_unassigned_numbers"


@pytest.mark.asyncio
async def test_a_refused_release_leaves_the_books_untouched():
    """release_number returning False is not proof the number is gone. Marking
    it released anyway makes it unfindable by every reconciliation we have."""
    with patch.object(il, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(il.db_phones, "list_for_tenant", new=AsyncMock(
             return_value=[_phone(pl.PURPOSE_TEMPORARY, pl.STATUS_ACTIVE)])), \
         patch.object(il.ita, "claim_retirement", new=AsyncMock(return_value=True)), \
         patch.object(il.telephony, "release_number", new=AsyncMock(return_value=False)), \
         patch.object(il.phone_registry, "mark_released",
                      new=AsyncMock(side_effect=AssertionError("MARKED RELEASED"))), \
         patch.object(il.ita, "mark_released",
                      new=AsyncMock(side_effect=AssertionError("MARKED RELEASED"))):
        out = await il.retire_temporary(T)
    assert out["outcome"] == il.NOTHING_TO_DO
    assert out["reason"] == "release_not_confirmed"


# ═══ 13. the repository fences, as query contracts ══════════════════════
# The fences are WHERE clauses, so this is the only place they can be asserted
# without a live database. stage_x proves the same thing against real Postgres.

class _Query:
    def __init__(self, rows):
        # `tbl`, not `table`: assigning self.table would shadow the method.
        self.rows, self.tbl, self.patch = rows, None, None
        self.eqs, self.nulls, self.not_nulls = {}, [], []
        self._negate = False

    def table(self, name):
        self.tbl = name; return self

    def update(self, patch):
        self.patch = patch; return self

    def insert(self, row):
        self.patch = row; return self

    def select(self, *a):
        return self

    def limit(self, n):
        return self

    def eq(self, col, val):
        self.eqs[col] = val; return self

    @property
    def not_(self):
        self._negate = True; return self

    def is_(self, col, val):
        (self.not_nulls if self._negate else self.nulls).append((col, val))
        self._negate = False
        return self

    def execute(self):
        return MagicMock(data=self.rows)


def _record(rows=None):
    q = _Query(rows if rows is not None else [{"tenant_id": T}])
    return q, patch.object(ita, "get_client", return_value=q)


@pytest.mark.asyncio
async def test_attach_requires_an_unbound_lifecycle_that_did_attempt():
    q, ctx = _record()
    with ctx:
        assert await ita.attach_number(tenant_id=T, e164="+1416", provider_sid="PN1") is True
    assert q.tbl == "ireland_temporary_access"
    assert q.eqs == {"tenant_id": T}
    assert ("e164", "null") in q.nulls                     # never overwrite
    assert ("provider_attempt_at", "null") in q.not_nulls  # 036's CHECK, echoed


@pytest.mark.asyncio
async def test_attach_refuses_a_lifecycle_that_already_has_a_number():
    q, ctx = _record(rows=[])
    with ctx:
        assert await ita.attach_number(tenant_id=T, e164="+1416",
                                       provider_sid="PN1") is False


@pytest.mark.asyncio
async def test_mark_attempt_is_fenced_on_there_being_no_attempt():
    q, ctx = _record()
    with ctx:
        assert await ita.mark_attempt(T) is True
    assert ("provider_attempt_at", "null") in q.nulls
    assert "provider_attempt_at" in q.patch


@pytest.mark.asyncio
async def test_retake_requires_proof_the_provider_was_never_called():
    q, ctx = _record()
    with ctx:
        assert await ita.retake_unattempted(T) is True
    assert ("provider_attempt_at", "null") in q.nulls
    assert ("e164", "null") in q.nulls
    assert q.patch == {"updated_at": q.patch["updated_at"]}   # bookkeeping only


def test_retake_is_gated_on_proof_not_on_time():
    import ast, inspect, textwrap
    src = inspect.getsource(ita.retake_unattempted)
    fn = ast.parse(textwrap.dedent(src)).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    code = ast.unparse(fn)
    for smell in ("timedelta", "STALE", "seconds", "interval", "utcnow"):
        assert smell not in code, smell


def test_the_repository_offers_no_way_to_unmark_an_attempt():
    refs = identifiers(ita)
    assert "clear_attempt" not in refs and "unmark" not in refs
    import inspect
    src = inspect.getsource(ita)
    assert '"provider_attempt_at": None' not in src


@pytest.mark.asyncio
async def test_retirement_claim_elects_exactly_one_worker():
    q, ctx = _record()
    with ctx:
        assert await ita.claim_retirement(T) is True
    assert ("retirement_claimed_at", "null") in q.nulls


@pytest.mark.asyncio
async def test_suspension_keeps_the_first_reason_recorded():
    q, ctx = _record()
    with ctx:
        assert await ita.suspend(tenant_id=T, reason=il.SUSPEND_ALLOWANCE) is True
    assert ("suspended_at", "null") in q.nulls
    assert q.patch["suspend_reason"] == il.SUSPEND_ALLOWANCE
