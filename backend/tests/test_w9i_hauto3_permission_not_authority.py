"""W9I-H.AUTO.3 — with the purchase gate OPEN, permission is still not authority.

Every test here runs with IRELAND_PERMANENT_NUMBER_PURCHASE_ENABLED=true, which
is now the live production value. That flag is a kill switch, not a decision: it
says "we are willing to buy Irish numbering commercially", and nothing more. The
chain that decides whether THIS tenant may have THIS number is untouched by it.

The provider-state matrix is the heart of it. Only one value in the entire space
of things Twilio can say permits spending money, and it has to be read fresh,
from the tenant's own sub-account, at the moment of asking.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import ireland_lifecycle as il
from services import permanent_numbers as perm
from services import phone_lifecycle as pl
from services import temporary_numbers as temp

T = "11111111-2222-4333-8444-555555555555"


@pytest.fixture(autouse=True)
def _gate_open(monkeypatch):
    """The now-live production value. Everything below runs with it TRUE."""
    monkeypatch.setenv("IRELAND_PERMANENT_NUMBER_PURCHASE_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_SOURCE_COUNTRY", "CA")
    assert perm.purchase_enabled() is True, "these tests are meaningless if it is off"


def _tenant(**o):
    return {"id": T, "business_name": "Acme IE", "business_country_code": "IE",
            "twilio_subaccount_sid": "AC_sub", "twilio_auth_token": "tok",
            "vapi_assistant_id": "asst_1", **o}


def _profile(**o):
    return {"id": "p1", "tenant_id": T, "iso_country": "IE", "bundle_sid": "BU1",
            "provider_account_sid": "AC_sub", "state": "approved", **o}


def _provider(status, *, account="AC_sub", raises=None):
    c = MagicMock()
    f = c.numbers.v2.regulatory_compliance.bundles.return_value.fetch
    if raises:
        f.side_effect = raises
    else:
        f.return_value = MagicMock(status=status, account_sid=account)
    return c


def _drive(*, provider_status=None, raises=None, tenant=None, profiles=None,
           phones=None, account="AC_sub"):
    """Run advance() with everything that could spend money booby-trapped."""
    spent = {"permanent": [], "temporary": []}
    tenant = tenant if tenant is not None else _tenant()
    profiles = _profile() if profiles is None else profiles
    profiles = [profiles] if isinstance(profiles, dict) else profiles

    async def buy_perm(*a, **k):
        spent["permanent"].append((a, k))
        return {"status": perm.OK}

    async def buy_temp(*a, **k):
        spent["temporary"].append((a, k))
        return {"status": temp.OK, "e164": "+14165550100", "row": {}}

    ctx = [
        patch.object(il, "_tenant", new=AsyncMock(return_value=tenant)),
        patch.object(il.db_phones, "list_for_tenant",
                     new=AsyncMock(return_value=phones or [])),
        patch.object(il.db_reg, "list_profiles", new=AsyncMock(return_value=profiles)),
        patch.object(il.telephony, "regulatory_client",
                     return_value=_provider(provider_status, account=account,
                                            raises=raises)),
        patch.object(il.permanent_numbers, "ensure_permanent_irish_number",
                     new=buy_perm),
        patch.object(il.temporary_numbers, "ensure_temporary_number", new=buy_temp),
        # The lifecycle now asks what is refusable WITHOUT reaching a provider
        # before it records an attempt, so this collaborator has to be stubbed
        # alongside the purchase it guards. Its own behaviour is covered in
        # test_temporary_attempt_boundary.
        patch.object(il.temporary_numbers, "preflight",
                     new=AsyncMock(return_value={"ok": True, "tenant": tenant, "policy": None})),
        patch.object(il.ita, "claim", new=AsyncMock(return_value=True)),
        patch.object(il.ita, "get", new=AsyncMock(return_value=None)),
        patch.object(il.ita, "mark_attempt", new=AsyncMock(return_value=True)),
        patch.object(il.ita, "attach_number", new=AsyncMock(return_value=True)),
        patch.object(il.ita, "start_access", new=AsyncMock(return_value=True)),
        patch.object(il.ita, "start_action_required", new=AsyncMock(return_value=True)),
        patch.object(il.ita, "start_rejected", new=AsyncMock(return_value=True)),
    ]
    import contextlib
    stack = contextlib.ExitStack()
    for cm in ctx:
        stack.enter_context(cm)
    return stack, spent


# ═══ THE PROVIDER-STATE MATRIX ═══════════════════════════════════════════
# One value in this entire space permits spending. Everything else does not.

NEVER_PERMANENT = [
    "draft", "pending-review", "in-review", "provisionally-approved",
    "twilio-rejected", "rejected", "action-required", "twilio-action-required",
    "expired", "", "approved",          # "approved" is OUR word, not Twilio's
]


@pytest.mark.parametrize("status", NEVER_PERMANENT)
@pytest.mark.asyncio
async def test_no_provider_state_but_exact_approval_buys_a_permanent_number(status):
    stack, spent = _drive(provider_status=status)
    with stack:
        await il.advance(T)
    assert spent["permanent"] == [], f"{status!r} bought a +353"


@pytest.mark.parametrize("status", ["twilio-approved", "TWILIO-APPROVED",
                                    " twilio-approved "])
@pytest.mark.asyncio
async def test_the_approval_check_normalises_case_and_whitespace(status):
    """Twilio sends lowercase; normalising is defensive, not a loophole. The
    VALUE still has to be the approval -- no other string survives it."""
    stack, spent = _drive(provider_status=status)
    with stack:
        await il.advance(T)
    assert len(spent["permanent"]) == 1, status


@pytest.mark.asyncio
async def test_only_the_exact_provider_approval_reaches_acquisition():
    stack, spent = _drive(provider_status="twilio-approved")
    with stack:
        out = await il.advance(T)
    assert len(spent["permanent"]) == 1
    assert out["outcome"] == il.PERMANENT_ACQUIRED


@pytest.mark.parametrize("boom", [
    TimeoutError("timed out"), RuntimeError("HTTP 401"), RuntimeError("HTTP 403"),
    RuntimeError("HTTP 429"), RuntimeError("HTTP 500"), ValueError("malformed"),
])
@pytest.mark.asyncio
async def test_an_unreadable_provider_buys_nothing_at_all(boom):
    """UNKNOWN is not approval and not rejection. It spends nothing either way."""
    stack, spent = _drive(provider_status=None, raises=boom)
    with stack:
        out = await il.advance(T)
    assert spent["permanent"] == [] and spent["temporary"] == []
    assert out["outcome"] == il.PROVIDER_UNKNOWN


# ═══ the rest of the chain the flag does not replace ═════════════════════

@pytest.mark.asyncio
async def test_a_non_irish_tenant_never_reaches_acquisition():
    stack, spent = _drive(provider_status="twilio-approved",
                          tenant=_tenant(business_country_code="CA"))
    with stack:
        out = await il.advance(T)
    assert spent["permanent"] == []
    assert out["outcome"] == il.NOT_APPLICABLE


@pytest.mark.asyncio
async def test_a_tenant_with_no_filing_never_reaches_acquisition():
    stack, spent = _drive(provider_status="twilio-approved", profiles=[])
    with stack:
        out = await il.advance(T)
    assert spent["permanent"] == []


@pytest.mark.asyncio
async def test_a_bundle_held_on_another_account_never_buys():
    """The filing must be on the tenant's OWN sub-account."""
    stack, spent = _drive(provider_status="twilio-approved", account="AC_someone_else")
    with stack:
        out = await il.advance(T)
    assert spent["permanent"] == []
    assert out["outcome"] == il.PROVIDER_UNKNOWN


@pytest.mark.asyncio
async def test_a_profile_recorded_against_another_account_is_skipped():
    stack, spent = _drive(provider_status="twilio-approved",
                          profiles=[_profile(provider_account_sid="AC_other")])
    with stack:
        out = await il.advance(T)
    assert spent["permanent"] == []


@pytest.mark.asyncio
async def test_a_locally_approved_profile_with_a_pending_bundle_never_buys():
    """THE forgery case: our row says approved, Twilio says otherwise."""
    stack, spent = _drive(provider_status="pending-review",
                          profiles=[_profile(state="approved")])
    with stack:
        await il.advance(T)
    assert spent["permanent"] == []


@pytest.mark.asyncio
async def test_a_tenant_already_holding_a_permanent_number_buys_no_second():
    stack, spent = _drive(provider_status="twilio-approved", phones=[
        {"id": "r1", "tenant_id": T, "e164": "+353871234567",
         "purpose": pl.PURPOSE_PERMANENT, "status": pl.STATUS_ACTIVE,
         "provider_sid": "PN1", "provider_account_sid": "AC_sub"}])
    with stack, \
         patch.object(il.ita, "start_cutover", new=AsyncMock(return_value=False)):
        out = await il.advance(T)
    assert spent["permanent"] == []


@pytest.mark.asyncio
async def test_the_acquisition_module_itself_still_runs_its_own_chain():
    """advance() delegating is not the same as the chain being skipped."""
    reached = []
    with patch.object(perm, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(perm, "eligibility", new=AsyncMock(
             side_effect=lambda *a, **k: reached.append("eligibility") or {
                 "eligible": False, "reason": "no_regulatory_filing", "detail": "",
                 "profile": None, "address": None})), \
         patch.object(perm.telephony, "purchase_regulated_number",
                      new=AsyncMock(side_effect=AssertionError("BOUGHT"))):
        out = await perm.ensure_permanent_irish_number(T)
    assert reached == ["eligibility"]
    assert out["status"] == perm.NOT_ELIGIBLE


@pytest.mark.asyncio
async def test_acquisition_reverifies_approval_at_the_provider_itself():
    """Even reached through an approved driver pass, the module asks again."""
    import inspect
    src = inspect.getsource(perm.ensure_permanent_irish_number)
    assert "verify_approval" in src
    i, j = src.index("verify_approval"), src.index("find_regulated_candidates")
    assert i < j, "approval must be re-read before inventory is searched"


# ═══ temporary and permanent cannot be confused ══════════════════════════

@pytest.mark.parametrize("status", ["pending-review", "in-review",
                                    "provisionally-approved"])
@pytest.mark.asyncio
async def test_genuine_review_buys_a_TEMPORARY_number_and_never_a_permanent(status):
    stack, spent = _drive(provider_status=status)
    with stack:
        out = await il.advance(T)
    assert len(spent["temporary"]) == 1, status
    assert spent["permanent"] == [], status
    assert out["outcome"] == il.TEMP_PROVISIONED


@pytest.mark.asyncio
async def test_approval_buys_a_PERMANENT_number_and_never_another_temporary():
    stack, spent = _drive(provider_status="twilio-approved")
    with stack:
        await il.advance(T)
    assert len(spent["permanent"]) == 1
    assert spent["temporary"] == []


def test_the_two_eligible_state_sets_do_not_overlap():
    assert il.PROVIDER_APPROVED not in il.PROVIDER_REVIEW_STATES
    assert set(temp.PROVIDER_REVIEW_STATES) == set(il.PROVIDER_REVIEW_STATES)
    assert il.PROVIDER_APPROVED == "twilio-approved"


# ═══ ordering: health, then ACTIVE, then trial, then email ═══════════════

def test_promotion_cannot_precede_the_health_check():
    import inspect
    from services import permanent_activation as act
    src = inspect.getsource(act.activate_permanent_irish_number)
    # The LAST health call before the promotion -- there are two, because a
    # repairable number is re-checked after one bounded repair.
    assert src.rindex("health_check") < src.index("promote_permanent_cas")


def test_billing_precedes_the_email_and_both_follow_promotion():
    import inspect
    from services import permanent_activation as act
    fin = inspect.getsource(act._finish)
    assert fin.index("_ensure_trial") < fin.index("ensure_activation_email")
    # The trial itself is created inside _ensure_trial, never in _finish.
    assert "create_trial_subscription" in inspect.getsource(act._ensure_trial)
    assert "create_trial_subscription" not in fin


def test_a_failed_trial_stops_before_the_email():
    """The customer is told their line is live and their trial has begun. If
    billing did not converge, the second half of that sentence is not true."""
    import inspect
    from services import permanent_activation as act
    fin = inspect.getsource(act._finish)
    guard = fin.index('if billing["status"] not in (OK,):')
    assert guard < fin.index("ensure_activation_email")


def test_the_driver_starts_no_trial_and_sends_no_email_itself():
    from tests.module_identifiers import identifiers
    refs = identifiers(il)
    for forbidden in ("create_trial_subscription", "ensure_activation_email",
                      "record_call_minutes"):
        assert forbidden not in refs, forbidden


# ═══ Stage F: permanent purchase idempotency, gate OPEN ══════════════════

def _held(*nums):
    return [MagicMock(phone_number=n, sid=f"PN{i}") for i, n in enumerate(nums)]


def _acq_world(held, *, bought=None):
    """permanent_numbers with everything up to inventory satisfied."""
    ledger = {"purchases": []}

    async def purchase(*a, **k):
        ledger["purchases"].append(a)
        return (bought or "+353871111111"), "PNnew"

    import contextlib
    stack = contextlib.ExitStack()
    for cm in (
        patch.object(perm, "_tenant", new=AsyncMock(return_value=_tenant())),
        patch.object(perm, "eligibility", new=AsyncMock(return_value={
            "eligible": True, "reason": "", "detail": "",
            "profile": _profile(), "address": {"address_sid": "AD1", "tenant_location_id": None},
            "existing": None})),
        patch.object(perm.tenant_subaccount, "ensure", new=AsyncMock(return_value={
            "status": perm.tenant_subaccount.OK, "sid": "AC_sub",
            "auth_token": "tok"})),
        patch.object(perm, "verify_approval", new=AsyncMock(return_value={
            "ok": True, "status": perm.OK, "provider_status": "twilio-approved"})),
        patch.object(perm, "_held_regulated_numbers", new=AsyncMock(return_value={
            "status": perm.OK, "numbers": held})),
        patch.object(perm.telephony, "purchase_regulated_number", new=purchase),
        patch.object(perm, "_record_and_route", new=AsyncMock(
            side_effect=lambda **k: {"status": perm.OK, "adopted": k.get("adopted"),
                                     "e164": k.get("e164")})),
    ):
        stack.enter_context(cm)
    return stack, ledger


@pytest.mark.asyncio
async def test_a_lost_purchase_response_adopts_the_one_number_held():
    """Twilio committed, we never saw the answer, the worker restarted. The
    number it already holds is the one, and no second is bought."""
    held = [{"e164": "+353871234567", "sid": "PNheld"}]
    stack, ledger = _acq_world(held)
    with stack:
        out = await perm.ensure_permanent_irish_number(T)
    assert ledger["purchases"] == [], "bought again after a lost response"
    assert out["status"] == perm.OK and out["adopted"] is True
    assert out["e164"] == "+353871234567"


@pytest.mark.asyncio
async def test_two_held_candidates_fail_closed_and_buy_nothing():
    held = [{"e164": "+353871234567", "sid": "PN1"},
            {"e164": "+353879999999", "sid": "PN2"}]
    stack, ledger = _acq_world(held)
    with stack:
        out = await perm.ensure_permanent_irish_number(T)
    assert ledger["purchases"] == []
    assert out["status"] == perm.PURCHASE_OUTCOME_UNKNOWN
    assert out["reason"] == "multiple_unassigned_numbers"


@pytest.mark.asyncio
async def test_nothing_held_proceeds_to_exactly_one_purchase():
    stack, ledger = _acq_world([])
    with stack, \
         patch.object(perm.telephony, "find_regulated_candidates", new=AsyncMock(
             return_value=[MagicMock(phone_number="+353871234567",
                                     supports=lambda *a: True)])):
        out = await perm.ensure_permanent_irish_number(T)
    assert len(ledger["purchases"]) == 1
    assert out["status"] == perm.OK


@pytest.mark.asyncio
async def test_an_unreadable_inventory_buys_nothing():
    """Not knowing what we hold is not proof that we hold nothing."""
    stack, ledger = _acq_world([])
    with stack, \
         patch.object(perm, "_held_regulated_numbers", new=AsyncMock(
             return_value={"status": perm.PROVIDER_UNAVAILABLE, "numbers": []})):
        out = await perm.ensure_permanent_irish_number(T)
    assert ledger["purchases"] == []
    assert out["status"] == perm.PROVIDER_UNAVAILABLE


def test_adoption_never_picks_the_first_of_many():
    import inspect
    src = inspect.getsource(perm.ensure_permanent_irish_number)
    assert "_pick_unambiguous" in src
    assert 'held["numbers"][0]' not in src
