"""W9I-E — the temporary test number, and the promise attached to it.

THE PROMISE
"Temporary test access is free WHILE GENUINE REGULATORY REVIEW IS PENDING."

Both halves are defended here. A number issued before anything was filed is not
free access during review -- it is a free phone line, given on the strength of a
form. And a number that quietly starts a trial is the opposite of free.

THE THREE FAILURES THAT COST REAL MONEY
  * buying twice, because a purchase response was lost
  * buying at all, for a tenant local state already proves ineligible
  * charging someone for a line they were told was free while they waited

Each has its own section, and each is mutation-tested.
"""
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import phone_lifecycle as lifecycle
from services import phone_registry
from services import regulatory_state as st
from services import temporary_numbers as tmp
from services import tenant_subaccount as subacct
from tests.module_identifiers import identifiers

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
SUB = "AC" + "1" * 32
TEMP_E164 = "+442071234567"
PERM_E164 = "+35312345678"


def _tenant(**over):
    return {"id": TENANT, "business_name": "Acme", "business_country_code": "IE",
            "onboarding_state": "regulatory_required",
            "twilio_subaccount_sid": SUB, "twilio_auth_token": "tok",
            "vapi_assistant_id": "asst_1", "twilio_phone_number": None, **over}


def _profile(state=st.PENDING_REVIEW, **over):
    return {"id": "p1", "tenant_id": TENANT, "iso_country": "IE", "state": state,
            "bundle_sid": "BU" + "a" * 32, **over}


def _row(purpose=lifecycle.PURPOSE_TEMPORARY, status=lifecycle.STATUS_ACTIVE, **over):
    return {"id": "r1", "tenant_id": TENANT, "e164": TEMP_E164, "purpose": purpose,
            "status": status, "provider": "twilio", "provider_account_sid": SUB,
            "provider_sid": "PN" + "b" * 32, "iso_country": "GB", **over}


def _eligible_world(profiles=None, rows=None):
    """Patch the two reads eligibility() makes. Nothing else."""
    return [
        patch.object(tmp.db_phones, "list_for_tenant",
                     new=AsyncMock(return_value=rows if rows is not None else [])),
        patch.object(tmp.db_reg, "list_profiles",
                     new=AsyncMock(return_value=profiles if profiles is not None
                                   else [_profile()])),
    ]


def _with(patches):
    import contextlib
    stack = contextlib.ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


# ═══ 1. eligibility is grounded in a real filing ═════════════════════════

@pytest.mark.asyncio
async def test_a_pending_review_filing_makes_a_tenant_eligible():
    with _with(_eligible_world()):
        out = await tmp.eligibility(_tenant())
    assert out["eligible"] is True


@pytest.mark.parametrize("state", list(tmp.NOT_YET_FILED_STATES))
@pytest.mark.asyncio
async def test_nothing_filed_yet_means_no_temporary_number(state):
    """A number here would be free service with no review pending at all."""
    with _with(_eligible_world(profiles=[_profile(state)])):
        out = await tmp.eligibility(_tenant())
    assert out["eligible"] is False
    assert out["reason"] == "filing_not_submitted"


@pytest.mark.asyncio
async def test_no_filing_at_all_means_no_temporary_number():
    with _with(_eligible_world(profiles=[])):
        out = await tmp.eligibility(_tenant())
    assert out["eligible"] is False and out["reason"] == "no_regulatory_filing"


@pytest.mark.asyncio
async def test_an_unconfirmed_submission_is_reconciled_before_answering():
    """SUBMITTING means the submit call's outcome was never confirmed. That is a
    question, not an entitlement and not a refusal."""
    with _with(_eligible_world(profiles=[_profile(st.SUBMITTING)])):
        out = await tmp.eligibility(_tenant())
    assert out["eligible"] is False
    assert out["reason"] == "filing_outcome_unconfirmed"
    assert out["detail"] == "reconcile_before_asking_again"


@pytest.mark.parametrize("state", [st.REJECTED, st.MORE_INFORMATION_REQUIRED,
                                   st.APPROVED])
@pytest.mark.asyncio
async def test_a_decided_filing_gets_no_new_temporary_number(state):
    """Nothing is pending review any more, so nothing new is issued. What the
    customer ALREADY has is a separate question -- see the retention tests."""
    with _with(_eligible_world(profiles=[_profile(state)])):
        out = await tmp.eligibility(_tenant())
    assert out["eligible"] is False
    assert out["reason"] == "filing_already_decided"
    assert out["detail"] == state


@pytest.mark.asyncio
async def test_approval_does_not_buy_a_permanent_number_here():
    """Approval makes a tenant eligible for W9I-F. It does nothing in this gate."""
    referenced = identifiers(tmp)
    for forbidden in ("purchase_permanent", "register_permanent", "mark_active",
                      "promote", "reprovision_tenant_number"):
        assert forbidden not in referenced, forbidden


@pytest.mark.asyncio
async def test_an_unregulated_country_gets_no_temporary_number():
    """CA and US get their permanent number at signup; a temporary one would be a
    second line nobody needs and someone pays for."""
    with _with(_eligible_world()):
        out = await tmp.eligibility(_tenant(business_country_code="CA"))
    assert out["eligible"] is False and out["reason"] == "country_is_not_regulated"


@pytest.mark.asyncio
async def test_a_live_permanent_number_means_no_temporary_one():
    rows = [_row(purpose=lifecycle.PURPOSE_PERMANENT, e164=PERM_E164)]
    with _with(_eligible_world(rows=rows)):
        out = await tmp.eligibility(_tenant())
    assert out["eligible"] is False
    assert out["reason"] == "permanent_number_already_live"


@pytest.mark.asyncio
async def test_an_existing_temporary_number_is_reported_not_duplicated():
    with _with(_eligible_world(rows=[_row()])):
        out = await tmp.eligibility(_tenant())
    assert out["eligible"] is False
    assert out["reason"] == tmp.ALREADY_ACTIVE
    assert out["active"] is True


def test_the_eligible_states_are_pinned_to_the_filing_state_machine():
    """Every state is accounted for exactly once, so a new one cannot fall
    through into 'eligible' by omission."""
    covered = (set(tmp.REVIEW_PENDING_STATES) | set(tmp.DECIDED_STATES)
               | set(tmp.NOT_YET_FILED_STATES) | set(tmp.NEEDS_RECONCILIATION_STATES))
    remaining = set(st.ALL_STATES) - covered
    # Only the post-approval telephony states are outside this gate's vocabulary.
    assert remaining == {st.NUMBER_PROVISIONING, st.ACTIVE, st.FAILED}, remaining
    assert st.READY_TO_SUBMIT in tmp.NOT_YET_FILED_STATES
    assert st.PENDING_REVIEW in tmp.REVIEW_PENDING_STATES
    assert st.APPROVED not in tmp.REVIEW_PENDING_STATES


# ═══ 2. no country is ever chosen silently ═══════════════════════════════

def test_there_is_no_default_source_country(monkeypatch):
    for var in (tmp.SOURCE_ENV, tmp.TYPE_ENV, tmp.ENABLED_ENV):
        monkeypatch.delenv(var, raising=False)
    policy = tmp.source_policy()
    assert policy.iso_country == ""
    assert policy.enabled is False
    assert tmp.source_problem(policy) == "temporary_numbers_disabled"


def test_an_enabled_policy_with_no_country_is_still_unusable(monkeypatch):
    monkeypatch.setenv(tmp.ENABLED_ENV, "true")
    monkeypatch.delenv(tmp.SOURCE_ENV, raising=False)
    assert tmp.source_problem(tmp.source_policy()) == "no_source_country_configured"


def test_an_unsupported_source_country_fails_closed(monkeypatch):
    monkeypatch.setenv(tmp.ENABLED_ENV, "true")
    monkeypatch.setenv(tmp.SOURCE_ENV, "ZZ")
    assert tmp.source_problem(tmp.source_policy()).startswith("source_country_not_supported")


def test_the_module_never_names_a_fallback_country():
    """W9I-B found purchase_number silently falling back to Canada. An Irish
    business given a Canadian number and told it was theirs is the failure this
    rules out structurally."""
    import inspect
    src = inspect.getsource(tmp)
    body = src[src.index("REQUIRED_CAPABILITIES"):]
    for literal in ('"CA"', "'CA'", '"US"', "'US'", '"GB"', "'GB'", '"IE"'):
        assert literal not in body, literal


@pytest.mark.asyncio
async def test_an_unconfigured_source_returns_unavailable_and_spends_nothing(monkeypatch):
    monkeypatch.delenv(tmp.ENABLED_ENV, raising=False)
    with _with(_eligible_world()), \
         patch.object(tmp, "get_client", return_value=_client_with(_tenant())), \
         patch.object(tmp.telephony, "purchase_number_with_sid", new=AsyncMock()) as buy, \
         patch.object(tmp.tenant_subaccount, "ensure", new=AsyncMock()) as sub:
        out = await tmp.ensure_temporary_number(TENANT)
    assert out["status"] == tmp.UNAVAILABLE
    buy.assert_not_called()
    sub.assert_not_called()          # not even a sub-account is created


def _client_with(tenant):
    class QB:
        def table(self, n): return self
        def select(self, *a): return self
        def eq(self, *a): return self
        def limit(self, *a): return self
        def is_(self, *a): return self
        def update(self, *a): return self
        def execute(self): return type("R", (), {"data": [tenant]})()
    return QB()


# ═══ 3. capability contract ══════════════════════════════════════════════

def test_only_voice_is_required_of_a_temporary_number():
    """SMS is not required: Irish numbers are voice-only and Square sends DANI's
    appointment notifications. Demanding SMS would reject good inventory for a
    capability nothing uses."""
    assert tmp.REQUIRED_CAPABILITIES == ("voice",)
    assert "sms" not in tmp.REQUIRED_CAPABILITIES


def test_the_temporary_path_does_not_touch_transfer_policy():
    """A tenant being Irish is not a reason to enable international transfer."""
    referenced = identifiers(tmp)
    for forbidden in ("build_transfer_call_tool", "transfer_enabled",
                      "allow_international_transfer", "build_routing_tools"):
        assert forbidden not in referenced, forbidden


def test_the_temporary_path_sends_no_sms():
    referenced = identifiers(tmp)
    for forbidden in ("send_sms", "send_whatsapp", "messages"):
        assert forbidden not in referenced, forbidden


# ═══ 4. the billing firewall ═════════════════════════════════════════════

def test_the_temporary_path_cannot_reach_billing():
    """MANDATORY. A customer charged for a line they were promised free while
    waiting on a regulator is not a bug to find from a support ticket."""
    referenced = identifiers(tmp)
    for forbidden in ("create_trial_subscription", "create_subscription",
                      "stripe", "start_trial", "trial_status", "subscriptions",
                      "send_welcome_email", "send_activation_email",
                      "PLAN_LIST_PRICES", "trial_start"):
        assert forbidden not in referenced, forbidden


def test_the_registry_temporary_writers_cannot_reach_billing():
    referenced = identifiers(phone_registry)
    for forbidden in ("create_trial_subscription", "stripe", "send_welcome_email"):
        assert forbidden not in referenced, forbidden


@pytest.mark.asyncio
async def test_activating_a_temporary_number_starts_no_trial():
    with patch.object(phone_registry.db_phones, "update_number",
                      new=AsyncMock(return_value=_row())) as upd, \
         patch.object(phone_registry.db, "update_tenant", new=AsyncMock()) as tenant_upd:
        await phone_registry.mark_temporary_active(
            tenant_id=TENANT, number_row_id="r1", vapi_phone_number_id="vp1")
    # The tenant row is not touched at all: no scalar, no trial field, nothing.
    tenant_upd.assert_not_called()
    assert upd.call_args.args[1]["status"] == lifecycle.STATUS_ACTIVE


# ═══ 5. the legacy scalar stays the PERMANENT number's ═══════════════════

@pytest.mark.asyncio
async def test_registering_a_temporary_number_does_not_write_the_legacy_scalar():
    """Every reader treats tenants.twilio_phone_number as the one primary
    business number: the reclaim sweep selects on it, the release path clears it,
    the welcome email prints it. A temporary number there would make all of them
    describe a line that is by design going away."""
    with patch.object(phone_registry.db_phones, "find_owned_by_e164",
                      new=AsyncMock(return_value=None)), \
         patch.object(phone_registry.db_phones, "list_for_tenant",
                      new=AsyncMock(return_value=[])), \
         patch.object(phone_registry.db_phones, "insert_number",
                      new=AsyncMock(return_value=_row())), \
         patch.object(phone_registry.db, "update_tenant", new=AsyncMock()) as upd:
        out = await phone_registry.register_temporary(
            tenant_id=TENANT, e164=TEMP_E164, provider_account_sid=SUB,
            provider_sid="PNx", iso_country="GB")
    assert out["status"] == phone_registry.OK
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_a_temporary_number_starts_provisioning_not_active():
    inserted = {}

    async def ins(row):
        inserted.update(row)
        return _row(status=row["status"])

    with patch.object(phone_registry.db_phones, "find_owned_by_e164",
                      new=AsyncMock(return_value=None)), \
         patch.object(phone_registry.db_phones, "list_for_tenant",
                      new=AsyncMock(return_value=[])), \
         patch.object(phone_registry.db_phones, "insert_number", new=ins):
        await phone_registry.register_temporary(
            tenant_id=TENANT, e164=TEMP_E164, provider_account_sid=SUB,
            provider_sid="PNx", iso_country="GB")
    assert inserted["status"] == lifecycle.STATUS_PROVISIONING
    assert inserted["purpose"] == lifecycle.PURPOSE_TEMPORARY
    assert lifecycle.STATUS_PROVISIONING not in lifecycle.ROUTABLE_STATUSES


@pytest.mark.asyncio
async def test_a_second_live_temporary_is_refused_before_the_database_has_to():
    with patch.object(phone_registry.db_phones, "find_owned_by_e164",
                      new=AsyncMock(return_value=None)), \
         patch.object(phone_registry.db_phones, "list_for_tenant",
                      new=AsyncMock(return_value=[_row()])), \
         patch.object(phone_registry.db_phones, "insert_number", new=AsyncMock()) as ins:
        out = await phone_registry.register_temporary(
            tenant_id=TENANT, e164="+442079999999", provider_account_sid=SUB,
            provider_sid="PNy", iso_country="GB")
    assert out["status"] == phone_registry.CONFLICT
    assert out["detail"] == "tpn_one_live_temporary"
    ins.assert_not_called()


@pytest.mark.asyncio
async def test_another_tenants_number_cannot_be_registered_as_temporary():
    with patch.object(phone_registry.db_phones, "find_owned_by_e164",
                      new=AsyncMock(return_value=_row(tenant_id=OTHER))), \
         patch.object(phone_registry.db_phones, "insert_number", new=AsyncMock()) as ins:
        out = await phone_registry.register_temporary(
            tenant_id=TENANT, e164=TEMP_E164, provider_account_sid=SUB,
            provider_sid="PNx", iso_country="GB")
    assert out["status"] == phone_registry.CONFLICT
    ins.assert_not_called()


# ═══ 6. routing ══════════════════════════════════════════════════════════

def test_an_active_temporary_number_is_routable():
    assert lifecycle.is_routable(_row(status=lifecycle.STATUS_ACTIVE)) is True


@pytest.mark.parametrize("status", ["provisioning", "released", "failed"])
def test_a_non_live_temporary_number_is_not_routable(status):
    assert lifecycle.is_routable(_row(status=status)) is False


def test_routing_does_not_require_a_permanent_purpose():
    """ROUTABLE_STATUSES is keyed on STATUS, not purpose -- which is what lets an
    active temporary number take calls at all."""
    import inspect
    src = inspect.getsource(lifecycle.is_routable)
    assert "purpose" not in src
    assert lifecycle.is_routable({"status": lifecycle.STATUS_ACTIVE,
                                  "purpose": lifecycle.PURPOSE_TEMPORARY})


def test_a_permanent_and_a_temporary_number_coexist_without_conflict():
    perm = _row(purpose=lifecycle.PURPOSE_PERMANENT, e164=PERM_E164, id="r0")
    candidate = {"purpose": lifecycle.PURPOSE_TEMPORARY,
                 "status": lifecycle.STATUS_PROVISIONING, "e164": TEMP_E164}
    assert lifecycle.live_conflict([perm], candidate) == ""
    temp = _row()
    perm_candidate = {"purpose": lifecycle.PURPOSE_PERMANENT,
                      "status": lifecycle.STATUS_PROVISIONING, "e164": PERM_E164}
    assert lifecycle.live_conflict([temp], perm_candidate) == ""


# ═══ 7. one assistant, two phone records ════════════════════════════════

@pytest.mark.asyncio
async def test_the_temporary_number_reuses_the_tenants_assistant():
    """A second assistant would give the temporary line a different receptionist
    -- different prompt, different knowledge base -- drifting from the day the
    permanent number arrives."""
    seen = {}

    async def import_number(**kw):
        seen.update(kw)
        return "vapi_pn_temp"

    with patch.object(phone_registry, "register_temporary",
                      new=AsyncMock(return_value={"status": phone_registry.OK,
                                                  "row": _row(status="provisioning")})), \
         patch("services.vapi.import_twilio_number", new=import_number), \
         patch.object(tmp, "_health_check", new=AsyncMock(return_value={"ok": True, "reason": ""})), \
         patch.object(phone_registry, "mark_temporary_active",
                      new=AsyncMock(return_value={"status": "ok", "row": _row()})):
        out = await tmp._register_and_activate(
            tenant=_tenant(), e164=TEMP_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", iso_country="GB", adopted=False)

    assert out["status"] == tmp.OK
    assert seen["assistant_id"] == "asst_1"
    assert "temporary" in seen["label"].lower()


@pytest.mark.asyncio
async def test_no_assistant_means_no_activation():
    with patch.object(phone_registry, "register_temporary",
                      new=AsyncMock(return_value={"status": phone_registry.OK,
                                                  "row": _row(status="provisioning")})), \
         patch("services.vapi.import_twilio_number", new=AsyncMock()) as imp:
        out = await tmp._register_and_activate(
            tenant=_tenant(vapi_assistant_id=""), e164=TEMP_E164, provider_sid="PNx",
            sub_sid=SUB, sub_tok="tok", iso_country="GB", adopted=False)
    assert out["status"] == tmp.HEALTH_FAILED
    imp.assert_not_called()


def test_the_temporary_vapi_record_is_stored_on_the_canonical_row():
    """tenants.vapi_phone_number_id belongs to the PERMANENT number and is what
    the release path detaches. The temporary record lives beside the temporary
    number so W9I-G can retire them independently."""
    import inspect
    src = inspect.getsource(phone_registry.mark_temporary_active)
    assert "update_number" in src
    assert "update_tenant" not in src


# ═══ 8. the activation contract is not weakened ═════════════════════════

@pytest.mark.asyncio
async def test_a_number_is_not_active_merely_because_it_was_purchased():
    with patch.object(phone_registry, "register_temporary",
                      new=AsyncMock(return_value={"status": phone_registry.OK,
                                                  "row": _row(status="provisioning")})), \
         patch("services.vapi.import_twilio_number",
               new=AsyncMock(return_value="vapi_pn")), \
         patch.object(tmp, "_health_check",
                      new=AsyncMock(return_value={"ok": False,
                                                  "reason": "no_voice_route_configured"})), \
         patch.object(phone_registry, "mark_temporary_active", new=AsyncMock()) as act:
        out = await tmp._register_and_activate(
            tenant=_tenant(), e164=TEMP_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", iso_country="GB", adopted=False)
    assert out["status"] == tmp.HEALTH_FAILED
    act.assert_not_called()


@pytest.mark.asyncio
async def test_a_vapi_failure_leaves_the_number_unroutable_but_not_thrown_away():
    """A health blip must not discard a number we just paid for. The row stays
    `provisioning`: ours, not routable, deterministically retryable."""
    with patch.object(phone_registry, "register_temporary",
                      new=AsyncMock(return_value={"status": phone_registry.OK,
                                                  "row": _row(status="provisioning")})), \
         patch("services.vapi.import_twilio_number",
               new=AsyncMock(side_effect=RuntimeError("vapi 500"))), \
         patch.object(tmp.telephony, "release_number", new=AsyncMock()) as rel, \
         patch.object(phone_registry, "mark_temporary_active", new=AsyncMock()) as act:
        out = await tmp._register_and_activate(
            tenant=_tenant(), e164=TEMP_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", iso_country="GB", adopted=False)
    assert out["status"] == tmp.HEALTH_FAILED
    # The REASON matters: a Vapi failure and a failed health check need different
    # things from an operator, and collapsing them hides which one happened.
    assert out["reason"] == "vapi_import_failed"
    act.assert_not_called()
    rel.assert_not_called()
    assert out["row"]["status"] == "provisioning"


@pytest.mark.asyncio
async def test_the_health_check_reads_the_number_back_from_the_provider():
    """Trusting the import call's return value would prove only that we asked."""
    listing = MagicMock(ok=True, numbers=[
        MagicMock(phone_number=TEMP_E164, voice_url="https://api.vapi.ai/twilio/inbound_call")])
    with patch.object(tmp.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(return_value=listing)):
        assert (await tmp._health_check(SUB, "tok", TEMP_E164))["ok"] is True

    no_route = MagicMock(ok=True, numbers=[
        MagicMock(phone_number=TEMP_E164, voice_url="", voice_application_sid="")])
    with patch.object(tmp.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(return_value=no_route)):
        out = await tmp._health_check(SUB, "tok", TEMP_E164)
    assert out["ok"] is False and out["reason"] == "no_voice_route_configured"

    missing = MagicMock(ok=True, numbers=[])
    with patch.object(tmp.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(return_value=missing)):
        out = await tmp._health_check(SUB, "tok", TEMP_E164)
    assert out["ok"] is False and out["reason"] == "number_not_held_by_subaccount"


@pytest.mark.asyncio
async def test_an_unreadable_provider_is_not_a_passing_health_check():
    with patch.object(tmp.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(return_value=MagicMock(ok=False, numbers=[]))):
        assert (await tmp._health_check(SUB, "tok", TEMP_E164))["ok"] is False


# ═══ 9. the unknown purchase outcome (Stage L) ══════════════════════════

@pytest.mark.asyncio
async def test_an_unknown_purchase_outcome_does_not_buy_a_second_number():
    """Phone purchases cost money. A blind retry is how a tenant pays twice."""
    buys = []

    async def buy(sid, tok, num):
        buys.append(num)
        raise TimeoutError("read timed out")

    # After the error, the provider turns out to hold the number.
    held = MagicMock(ok=True, numbers=[MagicMock(phone_number=TEMP_E164, sid="PNbought")])

    with _with(_eligible_world()), \
         patch.object(tmp, "get_client", return_value=_client_with(_tenant())), \
         patch.object(tmp, "source_policy",
                      return_value=tmp.TemporarySource(enabled=True, iso_country="GB",
                                                       number_type="local")), \
         patch.object(tmp.tenant_subaccount, "ensure",
                      new=AsyncMock(return_value={"status": "ok", "sid": SUB,
                                                  "auth_token": "tok"})), \
         patch.object(tmp.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(side_effect=[MagicMock(ok=True, numbers=[]), held])), \
         patch.object(tmp.telephony, "find_available_number",
                      new=AsyncMock(return_value=TEMP_E164)), \
         patch.object(tmp.telephony, "purchase_number_with_sid", new=buy), \
         patch.object(tmp, "_register_and_activate",
                      new=AsyncMock(return_value={"status": tmp.OK})) as reg:
        out = await tmp.ensure_temporary_number(TENANT)

    assert len(buys) == 1, "bought more than once after an unknown outcome"
    assert out["status"] == tmp.OK
    assert reg.call_args.kwargs["provider_sid"] == "PNbought"


@pytest.mark.asyncio
async def test_an_unverifiable_purchase_fails_closed_for_an_operator():
    """If the provider cannot say what it holds, nothing loops and nothing buys."""
    async def buy(sid, tok, num):
        raise TimeoutError("read timed out")

    with _with(_eligible_world()), \
         patch.object(tmp, "get_client", return_value=_client_with(_tenant())), \
         patch.object(tmp, "source_policy",
                      return_value=tmp.TemporarySource(enabled=True, iso_country="GB",
                                                       number_type="local")), \
         patch.object(tmp.tenant_subaccount, "ensure",
                      new=AsyncMock(return_value={"status": "ok", "sid": SUB,
                                                  "auth_token": "tok"})), \
         patch.object(tmp.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(side_effect=[MagicMock(ok=True, numbers=[]),
                                                 MagicMock(ok=False, numbers=[])])), \
         patch.object(tmp.telephony, "find_available_number",
                      new=AsyncMock(return_value=TEMP_E164)), \
         patch.object(tmp.telephony, "purchase_number_with_sid", new=buy):
        out = await tmp.ensure_temporary_number(TENANT)
    assert out["status"] == tmp.PURCHASE_OUTCOME_UNKNOWN


@pytest.mark.asyncio
async def test_a_number_already_held_is_adopted_rather_than_bought_again():
    """A previous attempt that lost its response left a real number behind."""
    held = MagicMock(ok=True, numbers=[MagicMock(phone_number=TEMP_E164, sid="PNold")])
    with _with(_eligible_world()), \
         patch.object(tmp, "get_client", return_value=_client_with(_tenant())), \
         patch.object(tmp, "source_policy",
                      return_value=tmp.TemporarySource(enabled=True, iso_country="GB",
                                                       number_type="local")), \
         patch.object(tmp.tenant_subaccount, "ensure",
                      new=AsyncMock(return_value={"status": "ok", "sid": SUB,
                                                  "auth_token": "tok"})), \
         patch.object(tmp.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(return_value=held)), \
         patch.object(tmp.telephony, "purchase_number_with_sid", new=AsyncMock()) as buy, \
         patch.object(tmp, "_register_and_activate",
                      new=AsyncMock(return_value={"status": tmp.OK})) as reg:
        out = await tmp.ensure_temporary_number(TENANT)
    buy.assert_not_called()
    assert reg.call_args.kwargs["adopted"] is True


@pytest.mark.asyncio
async def test_no_inventory_is_reported_not_retried_forever():
    with _with(_eligible_world()), \
         patch.object(tmp, "get_client", return_value=_client_with(_tenant())), \
         patch.object(tmp, "source_policy",
                      return_value=tmp.TemporarySource(enabled=True, iso_country="GB",
                                                       number_type="local")), \
         patch.object(tmp.tenant_subaccount, "ensure",
                      new=AsyncMock(return_value={"status": "ok", "sid": SUB,
                                                  "auth_token": "tok"})), \
         patch.object(tmp.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(return_value=MagicMock(ok=True, numbers=[]))), \
         patch.object(tmp.telephony, "find_available_number",
                      new=AsyncMock(return_value="")), \
         patch.object(tmp.telephony, "purchase_number_with_sid", new=AsyncMock()) as buy:
        out = await tmp.ensure_temporary_number(TENANT)
    assert out["status"] == tmp.NO_INVENTORY
    buy.assert_not_called()


@pytest.mark.asyncio
async def test_an_ineligible_tenant_never_reaches_the_provider():
    """The preflight exists to stop PREDICTABLE spend."""
    with _with(_eligible_world(profiles=[_profile(st.READY_TO_SUBMIT)])), \
         patch.object(tmp, "get_client", return_value=_client_with(_tenant())), \
         patch.object(tmp.tenant_subaccount, "ensure", new=AsyncMock()) as sub, \
         patch.object(tmp.telephony, "find_available_number", new=AsyncMock()) as find, \
         patch.object(tmp.telephony, "purchase_number_with_sid", new=AsyncMock()) as buy:
        out = await tmp.ensure_temporary_number(TENANT)
    assert out["status"] == tmp.NOT_ELIGIBLE
    sub.assert_not_called(); find.assert_not_called(); buy.assert_not_called()


@pytest.mark.asyncio
async def test_a_registration_race_hands_the_number_back():
    """Another worker won after our preflight. Keeping a number for a row that
    does not exist would bill for nothing."""
    with patch.object(phone_registry, "register_temporary",
                      new=AsyncMock(return_value={"status": phone_registry.CONFLICT,
                                                  "row": None,
                                                  "detail": "tpn_one_live_temporary"})), \
         patch.object(tmp.telephony, "release_number",
                      new=AsyncMock(return_value=True)) as rel:
        out = await tmp._register_and_activate(
            tenant=_tenant(), e164=TEMP_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", iso_country="GB", adopted=False)
    assert out["status"] == tmp.NOT_ELIGIBLE
    rel.assert_called_once()


@pytest.mark.asyncio
async def test_an_adopted_number_is_never_released_on_a_registration_conflict():
    """We did not buy it in this attempt; handing it back could take away a
    number another worker is mid-registration on."""
    with patch.object(phone_registry, "register_temporary",
                      new=AsyncMock(return_value={"status": phone_registry.CONFLICT,
                                                  "row": None, "detail": "x"})), \
         patch.object(tmp.telephony, "release_number", new=AsyncMock()) as rel:
        await tmp._register_and_activate(
            tenant=_tenant(), e164=TEMP_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", iso_country="GB", adopted=True)
    rel.assert_not_called()


# ═══ 10. the tenant's one sub-account ═══════════════════════════════════

def test_the_subaccount_marker_fits_the_provider_limit():
    marker = subacct.marker_for(TENANT)
    assert marker.startswith(subacct.MARKER_PREFIX)
    assert TENANT in marker
    assert len(marker) <= subacct.MARKER_MAX


@pytest.mark.asyncio
async def test_an_existing_subaccount_is_reused_not_recreated():
    with patch.object(subacct.telephony, "_master_client") as mc:
        out = await subacct.ensure(_tenant())
    assert out["status"] == subacct.OK and out["created"] is False
    mc.assert_not_called()          # not even a lookup: the row already has it


@pytest.mark.asyncio
async def test_a_subaccount_created_by_a_dead_worker_is_adopted():
    """Asked at the PROVIDER, not only in our row. A worker that created an
    account and died before writing left a real, billable account behind."""
    found = MagicMock(sid="AC" + "9" * 32, auth_token="tok9", status="active")
    master = MagicMock()
    master.api.accounts.list.return_value = [found]
    with patch.object(subacct.telephony, "_master_client", return_value=master), \
         patch.object(subacct, "get_client", return_value=_updating_client([{"id": TENANT}])):
        out = await subacct.ensure(_tenant(twilio_subaccount_sid=None,
                                           twilio_auth_token=None))
    assert out["status"] == subacct.OK
    assert out["sid"] == found.sid
    master.api.accounts.create.assert_not_called()


@pytest.mark.asyncio
async def test_an_unreadable_provider_does_not_create_a_second_subaccount():
    """Not knowing is not a licence to create. A second account is billable,
    invisible, and holds regulatory resources nobody revisits."""
    master = MagicMock()
    master.api.accounts.list.side_effect = TimeoutError("read timed out")
    with patch.object(subacct.telephony, "_master_client", return_value=master):
        out = await subacct.ensure(_tenant(twilio_subaccount_sid=None,
                                           twilio_auth_token=None))
    assert out["status"] == subacct.PROVIDER_UNAVAILABLE
    master.api.accounts.create.assert_not_called()


@pytest.mark.asyncio
async def test_the_loser_of_a_subaccount_race_closes_the_one_it_created():
    """Otherwise it bills forever as the account nobody's credentials read."""
    created = MagicMock(sid="AC" + "7" * 32, auth_token="tok7", status="active")
    master = MagicMock()
    master.api.accounts.list.return_value = []
    master.api.accounts.create.return_value = created

    winner_sid = "AC" + "8" * 32
    # The fenced update matches nothing (someone else got there); the re-read
    # shows a DIFFERENT sid.
    client = _updating_client([], reread=[{"twilio_subaccount_sid": winner_sid,
                                           "twilio_auth_token": "tok8"}])
    with patch.object(subacct.telephony, "_master_client", return_value=master), \
         patch.object(subacct, "get_client", return_value=client):
        out = await subacct.ensure(_tenant(twilio_subaccount_sid=None,
                                           twilio_auth_token=None))

    assert out["status"] == subacct.OK
    assert out["sid"] == winner_sid            # the winner's, not ours
    master.api.accounts(created.sid).update.assert_called_with(status="closed")


def _updating_client(update_rows, reread=None):
    state = {"phase": "update"}

    class QB:
        def table(self, n): return self
        def select(self, *a): state["phase"] = "select"; return self
        def update(self, *a): state["phase"] = "update"; return self
        def eq(self, *a): return self
        def is_(self, *a): return self
        def limit(self, *a): return self
        def execute(self):
            data = update_rows if state["phase"] == "update" else (reread or [])
            return type("R", (), {"data": data})()
    return QB()


def test_the_regulated_signup_path_creates_the_subaccount():
    """W9I-E Stage F: the IE branch returns BEFORE Step 3, so without this a
    regulated tenant had no credentials and address validation refused."""
    from services import provisioning
    referenced = identifiers(provisioning)
    assert "tenant_subaccount" in referenced


def test_the_address_route_ensures_a_subaccount_before_calling_the_provider():
    from routers import regulatory_verification as rv
    referenced = identifiers(rv)
    assert "tenant_subaccount" in referenced


# ═══ 11. retirement preparation and release ═════════════════════════════

def test_the_temporary_lifecycle_supports_active_retiring_released():
    assert lifecycle.STATUS_RETIRING in lifecycle.LIVE_TEMPORARY_STATUSES
    assert lifecycle.STATUS_RETIRING in lifecycle.ROUTABLE_STATUSES
    assert lifecycle.STATUS_RELEASED in lifecycle.TERMINAL_STATUSES
    # A retiring temporary still occupies the slot -- a second one alongside it
    # would be a billing leak, not a migration.
    assert lifecycle.live_conflict(
        [_row(status=lifecycle.STATUS_RETIRING)],
        {"purpose": lifecycle.PURPOSE_TEMPORARY,
         "status": lifecycle.STATUS_PROVISIONING, "e164": "+442079999999"}
    ) == "tpn_one_live_temporary"


def test_released_at_already_exists_so_no_migration_is_needed_for_retirement():
    """Stage Q: W9I-G may want a grace deadline, but W9I-E needs no new column."""
    import pathlib
    ddl = (pathlib.Path(__file__).parent.parent.parent / "migrations"
           / "027_regulated_phone_numbers.sql").read_text()
    assert re.search(r"released_at\s+timestamptz null", ddl)
    assert re.search(r"retiring_since\s+timestamptz null", ddl)


@pytest.mark.asyncio
async def test_releasing_a_temporary_number_cannot_clear_the_permanent_scalar():
    """MANDATORY. The scalar names the PERMANENT number. A temporary release that
    cleared it would unlink a live business line."""
    from db import supabase as dbs

    class Recorder:
        def __init__(self): self.calls = []
        def table(self, n): self.cur = {"table": n, "eq": {}}; self.calls.append(self.cur); return self
        def update(self, patch): self.cur["patch"] = patch; return self
        def eq(self, c, v): self.cur["eq"][c] = v; return self
        def execute(self): return type("R", (), {"data": []})()

    rec = Recorder()
    with patch.object(dbs, "get_client", return_value=rec):
        changed = await dbs.clear_tenant_number_fenced(TENANT, TEMP_E164, "2026-09-12")
    # Fenced on the E.164 being released: a tenant whose scalar holds the
    # PERMANENT number matches nothing, so nothing is cleared.
    assert rec.calls[0]["eq"] == {"id": TENANT, "twilio_phone_number": TEMP_E164}
    assert changed == []


def test_temporary_release_reuses_the_canonical_lifecycle():
    """No separate scalar-only temporary release path -- that asymmetry is
    exactly the W9I-B.1 defect."""
    referenced = identifiers(tmp)
    assert "update_tenant" not in referenced
    assert "twilio_phone_number" not in referenced


# ═══ 12. what the customer is shown ═════════════════════════════════════

def test_a_temporary_number_is_always_labelled_temporary():
    view = tmp.customer_view(_row())
    assert view["status"] == tmp.TEMP_NUMBER_READY
    assert view["temporary"] is True
    assert "temporary" in view["message"].lower()
    assert "not your permanent" in view["message"].lower()


def test_the_customer_view_never_calls_a_non_irish_number_irish():
    view = tmp.customer_view(_row(iso_country="GB"))
    assert view["iso_country"] == "GB"
    assert "irish" not in view["message"].lower()


def test_a_provisioning_number_is_not_shown_as_ready():
    view = tmp.customer_view(_row(status="provisioning"))
    assert view["status"] == tmp.TEMP_NUMBER_PREPARING
    assert view["number"] == ""


def test_no_number_yet_reads_as_unavailable_not_broken():
    view = tmp.customer_view(None)
    assert view["status"] == tmp.TEMP_NUMBER_UNAVAILABLE


# ═══ 13. CA/US semantics unchanged, flag still off ══════════════════════

def test_ca_and_us_signup_semantics_are_untouched():
    """The regulated branch is the ONLY thing W9I-E added to provisioning."""
    from services import onboarding_lifecycle as ob
    assert ob.REGULATED_COUNTRIES == frozenset({"IE"})
    assert ob.needs_regulatory_clearance("CA") is False
    assert ob.needs_regulatory_clearance("US") is False
    assert ob.initial_state("CA") == ob.PROVISIONING
    assert ob.initial_state("IE") == ob.REGULATORY_REQUIRED


def test_public_ireland_onboarding_is_still_off(monkeypatch):
    from services import onboarding_lifecycle as ob
    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    assert ob.ireland_onboarding_enabled() is False


# ═══ 14. the real queries and the real wiring ═══════════════════════════
#
# Sections above patch the repository and the orchestrator so the DECISIONS can
# be tested. Mutation testing found what that leaves unguarded: deleting the
# fence from the sub-account attach, and removing the ensure() call from the
# signup path, both left every test green.


class _AttachRecorder:
    """Records the query the fenced attach builds, and returns `rows`."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []
        self._cur = None

    def table(self, n):
        self._cur = {"table": n, "eq": {}, "is": {}, "patch": None, "op": "select"}
        self.calls.append(self._cur)
        return self

    def update(self, patch):
        self._cur["patch"] = patch; self._cur["op"] = "update"; return self

    def select(self, *a): return self
    def limit(self, *a): return self

    def eq(self, c, v):
        self._cur["eq"][c] = v; return self

    def is_(self, c, v):
        self._cur["is"][c] = v; return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


@pytest.mark.asyncio
async def test_the_subaccount_attach_is_fenced_on_there_being_none():
    """WITHOUT `.is_("twilio_subaccount_sid", "null")` this write overwrites the
    sub-account a concurrent winner just attached -- and the tenant's regulatory
    resources, which live in the winner's account, become unreachable with the
    credentials the row now holds."""
    created = MagicMock(sid="AC" + "7" * 32, auth_token="tok7", status="active")
    master = MagicMock()
    master.api.accounts.list.return_value = []
    master.api.accounts.create.return_value = created
    rec = _AttachRecorder([{"id": TENANT}])

    with patch.object(subacct.telephony, "_master_client", return_value=master), \
         patch.object(subacct, "get_client", return_value=rec):
        out = await subacct.ensure(_tenant(twilio_subaccount_sid=None,
                                           twilio_auth_token=None))

    assert out["status"] == subacct.OK
    attach = rec.calls[0]
    assert attach["table"] == "tenants" and attach["op"] == "update"
    assert attach["eq"] == {"id": TENANT}
    assert attach["is"] == {"twilio_subaccount_sid": "null"}
    assert attach["patch"]["twilio_subaccount_sid"] == created.sid
    assert attach["patch"]["twilio_auth_token"] == created.auth_token


@pytest.mark.asyncio
async def test_the_marker_is_what_the_provider_is_searched_by():
    """Reconciliation only works if the search uses a marker only we could have
    written -- otherwise a dead worker's account is invisible and a second one
    gets created."""
    master = MagicMock()
    master.api.accounts.list.return_value = []
    master.api.accounts.create.return_value = MagicMock(
        sid="AC" + "3" * 32, auth_token="t", status="active")
    with patch.object(subacct.telephony, "_master_client", return_value=master), \
         patch.object(subacct, "get_client", return_value=_AttachRecorder([{"id": TENANT}])):
        await subacct.ensure(_tenant(twilio_subaccount_sid=None, twilio_auth_token=None))

    searched = master.api.accounts.list.call_args.kwargs["friendly_name"]
    created_as = master.api.accounts.create.call_args.kwargs["friendly_name"]
    assert searched == subacct.marker_for(TENANT) == created_as


@pytest.mark.asyncio
async def test_a_regulated_signup_actually_creates_the_subaccount():
    """Behavioural, not structural: the import surviving while the CALL is
    removed is exactly the mutation that slipped through first time."""
    from services import provisioning

    called = {}

    async def ensure(tenant):
        called["tenant_id"] = str(tenant.get("id"))
        return {"status": "ok", "sid": SUB, "auth_token": "tok", "created": True}

    with patch.object(provisioning.tenant_subaccount, "ensure", new=ensure), \
         patch.object(provisioning, "_claim_or_resume_tenant",
                      new=AsyncMock(return_value=(
                          {"id": TENANT, "onboarding_state": "provisioning",
                           "business_country_code": "IE"}, False))), \
         patch.object(provisioning.telephony, "create_subaccount", new=AsyncMock()) as legacy:
        out = await provisioning.provision_tenant(
            {"business_name": "Acme", "industry": "realtor", "country": "IE",
             "owner_name": "O", "agent_name": "A", "website_url": ""})

    assert out["onboarding_state"] == "regulatory_required"
    assert called["tenant_id"] == TENANT
    # And it did NOT fall through into the ordinary Step 3 path.
    legacy.assert_not_called()


@pytest.mark.asyncio
async def test_a_subaccount_failure_does_not_fail_the_signup():
    """The account exists and is resumable. Failing a signup because Twilio was
    briefly unreachable is worse than starting verification a moment later."""
    from services import provisioning

    async def boom(tenant):
        raise TimeoutError("read timed out")

    with patch.object(provisioning.tenant_subaccount, "ensure", new=boom), \
         patch.object(provisioning, "_claim_or_resume_tenant",
                      new=AsyncMock(return_value=(
                          {"id": TENANT, "onboarding_state": "provisioning",
                           "business_country_code": "IE"}, False))):
        out = await provisioning.provision_tenant(
            {"business_name": "Acme", "industry": "realtor", "country": "IE",
             "owner_name": "O", "agent_name": "A", "website_url": ""})
    assert out["onboarding_state"] == "regulatory_required"
