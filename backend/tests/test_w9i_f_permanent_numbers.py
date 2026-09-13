"""W9I-F — acquiring the permanent regulated number, and stopping there.

WHAT THIS SUITE IS DEFENDING

1. TWO INDEPENDENT GATES. Twilio approving a customer's Bundle says their
   identity documents satisfy the Irish regulator. It says nothing about whether
   OpenLines may commercially resell Irish numbering under a per-customer
   sub-account. Approval must never authorise the commercial decision.

2. APPROVAL IS A FACT, NOT A MEMORY. Persisted "approved" is a record of a
   callback or a sweep. Before spending money the Bundle is re-read from the
   provider, and only an explicit twilio-approved counts -- "we could not reach
   Twilio" is not an approval.

3. THE GATE ENDS AT `provisioning`. A fully successful run leaves the number
   bought, recorded and wired, and NOT active, NOT mirrored to the legacy
   scalar, NOT billed, and with the temporary line still carrying every call.
"""
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import permanent_numbers as perm
from services import phone_lifecycle as lifecycle
from services import phone_registry
from services import regulatory_state as st
from services import telephony
from tests.module_identifiers import identifiers

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
SUB = "AC" + "1" * 32
OTHER_SUB = "AC" + "2" * 32
ADDR = "33333333-3333-3333-3333-333333333333"
BUNDLE = "BU" + "a" * 32
ADDRESS_SID = "AD" + "b" * 32
IE_E164 = "+35315550123"
TEMP_E164 = "+442071234567"


def _tenant(**over):
    return {"id": TENANT, "business_name": "Acme", "business_country_code": "IE",
            "twilio_subaccount_sid": SUB, "twilio_auth_token": "tok",
            "vapi_assistant_id": "asst_1", "twilio_phone_number": None, **over}


def _profile(state=st.APPROVED, **over):
    return {"id": "p1", "tenant_id": TENANT, "iso_country": "IE", "state": state,
            "bundle_sid": BUNDLE, "regulatory_address_id": ADDR,
            "provider_account_sid": SUB, "number_type": "local",
            "end_user_type": "business", **over}


def _address(**over):
    return {"id": ADDR, "tenant_id": TENANT, "iso_country": "IE", "validated": True,
            "address_sid": ADDRESS_SID, "provider_account_sid": SUB,
            "tenant_location_id": None, **over}


def _row(purpose=lifecycle.PURPOSE_PERMANENT, status=lifecycle.STATUS_PROVISIONING,
         e164=IE_E164, **over):
    return {"id": "r1", "tenant_id": TENANT, "e164": e164, "purpose": purpose,
            "status": status, "provider": "twilio", "provider_account_sid": SUB,
            "provider_sid": "PN" + "c" * 32, "iso_country": "IE", **over}


def _candidate(number=IE_E164, voice=True, locality="Dublin"):
    return telephony.NumberCandidate(number, locality, "Dublin",
                                     {"voice": voice, "sms": False})


#: Distinguishes "use the default" from "there genuinely is none" -- None had to
#: mean both, which silently turned a missing-address test into a passing one.
_DEFAULT = object()


def _world(*, profiles=None, rows=None, address=_DEFAULT):
    return [
        patch.object(perm.db_phones, "list_for_tenant",
                     new=AsyncMock(return_value=rows if rows is not None else [])),
        patch.object(perm.db_reg, "list_profiles",
                     new=AsyncMock(return_value=profiles if profiles is not None
                                   else [_profile()])),
        patch.object(perm.db_reg, "get_address",
                     new=AsyncMock(return_value=_address() if address is _DEFAULT
                                   else address)),
    ]


def _with(patches):
    import contextlib
    stack = contextlib.ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


def _client_with(tenant):
    class QB:
        def table(self, n): return self
        def select(self, *a): return self
        def eq(self, *a): return self
        def limit(self, *a): return self
        def execute(self): return type("R", (), {"data": [tenant]})()
    return QB()


def _acquire_world(*, approved=True, held=None, candidates=None,
                   purchase=(IE_E164, "PNbought"), purchase_error=None):
    """Everything ensure_permanent_irish_number touches, with the provider
    answers under test."""
    bundle = MagicMock(status="twilio-approved" if approved else "pending-review",
                       account_sid=SUB)
    rc = MagicMock()
    rc.bundles.return_value.fetch.return_value = bundle
    client = MagicMock()
    client.numbers.v2.regulatory_compliance = rc

    listing = MagicMock(ok=True, numbers=[
        MagicMock(phone_number=n["e164"], sid=n["sid"]) for n in (held or [])])

    async def buy(sid, tok, number, *, address_sid, bundle_sid):
        if purchase_error:
            raise purchase_error
        return purchase

    return [
        patch.object(perm, "get_client", return_value=_client_with(_tenant())),
        patch.object(perm.tenant_subaccount, "ensure",
                     new=AsyncMock(return_value={"status": "ok", "sid": SUB,
                                                 "auth_token": "tok"})),
        patch.object(perm.telephony, "regulatory_client", return_value=client),
        patch.object(perm.telephony, "fetch_subaccount_numbers",
                     new=AsyncMock(return_value=listing)),
        patch.object(perm.telephony, "find_regulated_candidates",
                     new=AsyncMock(return_value=candidates if candidates is not None
                                   else [_candidate()])),
        patch.object(perm.telephony, "purchase_regulated_number", new=buy),
    ]


# ═══ 1. the commercial gate ═════════════════════════════════════════════

def test_the_purchase_gate_is_off_by_default(monkeypatch):
    monkeypatch.delenv(perm.PURCHASE_GATE_ENV, raising=False)
    assert perm.purchase_enabled() is False


def test_the_purchase_gate_is_separate_from_the_signup_flag():
    """They answer different questions and can legitimately move at different
    times: one is whether Irish businesses may sign up, the other is whether we
    are willing to buy Irish numbering commercially."""
    from services import onboarding_lifecycle as ob
    assert perm.PURCHASE_GATE_ENV != "IRELAND_ONBOARDING_ENABLED"
    assert perm.PURCHASE_GATE_ENV == "IRELAND_PERMANENT_NUMBER_PURCHASE_ENABLED"
    import inspect
    assert "ireland_onboarding_enabled" not in inspect.getsource(perm.purchase_enabled)


@pytest.mark.asyncio
async def test_a_closed_gate_does_not_even_search_inventory(monkeypatch):
    """A search that could lead to a purchase is part of what is gated -- and it
    bills us for lookups nobody decided to make."""
    monkeypatch.delenv(perm.PURCHASE_GATE_ENV, raising=False)
    with _with(_world()), \
         patch.object(perm, "get_client", return_value=_client_with(_tenant())), \
         patch.object(perm.telephony, "find_regulated_candidates", new=AsyncMock()) as find, \
         patch.object(perm.telephony, "purchase_regulated_number", new=AsyncMock()) as buy, \
         patch.object(perm.telephony, "regulatory_client") as verify, \
         patch.object(perm.tenant_subaccount, "ensure", new=AsyncMock()) as sub:
        out = await perm.ensure_permanent_irish_number(TENANT)
    assert out["status"] == perm.GATE_CLOSED
    find.assert_not_called(); buy.assert_not_called()
    verify.assert_not_called(); sub.assert_not_called()


@pytest.mark.asyncio
async def test_an_approved_bundle_does_not_open_the_gate(monkeypatch):
    """Pins the invariant: provider approval is NOT purchase authority."""
    monkeypatch.delenv(perm.PURCHASE_GATE_ENV, raising=False)
    with _with(_world(profiles=[_profile(st.APPROVED)])), \
         patch.object(perm, "get_client", return_value=_client_with(_tenant())), \
         patch.object(perm.telephony, "purchase_regulated_number", new=AsyncMock()) as buy:
        out = await perm.ensure_permanent_irish_number(TENANT)
    assert out["status"] == perm.GATE_CLOSED
    buy.assert_not_called()


def test_no_callback_or_sweep_can_purchase_a_number():
    """W9I-D's callback and reconciliation must not reach acquisition."""
    from services import regulatory_callback as cb
    from services import regulatory_reconcile as rec
    for module in (cb, rec):
        referenced = identifiers(module)
        for forbidden in ("ensure_permanent_irish_number", "purchase_regulated_number",
                          "permanent_numbers"):
            assert forbidden not in referenced, (module.__name__, forbidden)


# ═══ 2. approval is re-read from the provider ═══════════════════════════

@pytest.mark.asyncio
async def test_a_freshly_approved_bundle_permits_the_purchase(monkeypatch):
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    with _with(_world()), _with(_acquire_world(approved=True)), \
         patch.object(perm, "_record_and_route",
                      new=AsyncMock(return_value={"status": perm.OK})) as rec:
        out = await perm.ensure_permanent_irish_number(TENANT)
    assert out["status"] == perm.OK
    assert rec.call_args.kwargs["provider_sid"] == "PNbought"


@pytest.mark.parametrize("provider_status", [
    "pending-review", "in-review", "twilio-rejected", "draft",
    "provisionally-approved",
])
@pytest.mark.asyncio
async def test_a_bundle_not_approved_at_the_provider_never_buys(monkeypatch, provider_status):
    """Persisted state says approved; the provider says otherwise. The provider
    wins. 'provisionally-approved' is included deliberately -- W9C measured a
    purchase refused on exactly that."""
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    bundle = MagicMock(status=provider_status, account_sid=SUB)
    client = MagicMock()
    client.numbers.v2.regulatory_compliance.bundles.return_value.fetch.return_value = bundle

    with _with(_world()), \
         patch.object(perm, "get_client", return_value=_client_with(_tenant())), \
         patch.object(perm.tenant_subaccount, "ensure",
                      new=AsyncMock(return_value={"status": "ok", "sid": SUB,
                                                  "auth_token": "tok"})), \
         patch.object(perm.telephony, "regulatory_client", return_value=client), \
         patch.object(perm.telephony, "find_regulated_candidates", new=AsyncMock()) as find, \
         patch.object(perm.telephony, "purchase_regulated_number", new=AsyncMock()) as buy:
        out = await perm.ensure_permanent_irish_number(TENANT)

    assert out["status"] == perm.NOT_APPROVED
    find.assert_not_called(); buy.assert_not_called()


@pytest.mark.parametrize("failure", [
    pytest.param(TimeoutError("read timed out"), id="timeout"),
    pytest.param(RuntimeError("HTTP 401 Unauthorized"), id="401"),
    pytest.param(RuntimeError("HTTP 403 Forbidden"), id="403"),
    pytest.param(RuntimeError("HTTP 429 Too Many Requests"), id="429"),
    pytest.param(RuntimeError("HTTP 500 Internal Server Error"), id="500"),
    pytest.param(ValueError("Expecting value: line 1 column 1"), id="malformed"),
    pytest.param(ConnectionResetError("connection reset"), id="transport"),
])
@pytest.mark.asyncio
async def test_an_unverifiable_approval_never_buys(monkeypatch, failure):
    """'We could not reach Twilio' is not an approval."""
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    client = MagicMock()
    client.numbers.v2.regulatory_compliance.bundles.return_value.fetch.side_effect = failure

    with _with(_world()), \
         patch.object(perm, "get_client", return_value=_client_with(_tenant())), \
         patch.object(perm.tenant_subaccount, "ensure",
                      new=AsyncMock(return_value={"status": "ok", "sid": SUB,
                                                  "auth_token": "tok"})), \
         patch.object(perm.telephony, "regulatory_client", return_value=client), \
         patch.object(perm.telephony, "purchase_regulated_number", new=AsyncMock()) as buy:
        out = await perm.ensure_permanent_irish_number(TENANT)
    assert out["status"] == perm.VERIFICATION_UNAVAILABLE
    buy.assert_not_called()


@pytest.mark.asyncio
async def test_a_bundle_held_by_another_account_is_refused(monkeypatch):
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    bundle = MagicMock(status="twilio-approved", account_sid=OTHER_SUB)
    client = MagicMock()
    client.numbers.v2.regulatory_compliance.bundles.return_value.fetch.return_value = bundle
    out = await perm.verify_approval(sub_sid=SUB, sub_tok="tok", profile=_profile())
    with patch.object(perm.telephony, "regulatory_client", return_value=client):
        out = await perm.verify_approval(sub_sid=SUB, sub_tok="tok", profile=_profile())
    assert out["ok"] is False and out["detail"] == "bundle_account_mismatch"


def test_only_one_provider_status_counts_as_approved():
    assert perm.PROVIDER_APPROVED_STATUS == "twilio-approved"
    assert st.PROVIDER_STATUS_MAP["provisionally-approved"] == st.PENDING_REVIEW


# ═══ 3. local eligibility, and cross-tenant refusal ═════════════════════

@pytest.mark.asyncio
async def test_an_unapproved_filing_is_not_eligible():
    for state in (st.PENDING_REVIEW, st.READY_TO_SUBMIT, st.REJECTED,
                  st.MORE_INFORMATION_REQUIRED, st.DETAILS_REQUIRED):
        with _with(_world(profiles=[_profile(state)])):
            out = await perm.eligibility(_tenant())
        assert out["eligible"] is False
        assert out["reason"] == "filing_not_approved", state


@pytest.mark.asyncio
async def test_a_profile_from_another_account_is_refused():
    """Numbers v2 is credential-scoped: another account's bundle is invisible at
    purchase time, and another TENANT's would file one customer's number against
    a different customer's identity."""
    with _with(_world(profiles=[_profile(provider_account_sid=OTHER_SUB)])):
        out = await perm.eligibility(_tenant())
    assert out["eligible"] is False and out["reason"] == "profile_account_mismatch"


@pytest.mark.asyncio
async def test_an_address_from_another_account_is_refused():
    with _with(_world(address=_address(provider_account_sid=OTHER_SUB))):
        out = await perm.eligibility(_tenant())
    assert out["eligible"] is False and out["reason"] == "address_account_mismatch"


@pytest.mark.asyncio
async def test_an_unvalidated_address_is_refused():
    for bad in (_address(validated=False), _address(address_sid=None)):
        with _with(_world(address=bad)):
            out = await perm.eligibility(_tenant())
        assert out["eligible"] is False
        assert out["reason"] == "regulatory_address_not_validated"


@pytest.mark.asyncio
async def test_a_missing_address_or_bundle_is_refused():
    with _with(_world(address=None)):
        assert (await perm.eligibility(_tenant()))["reason"] == "regulatory_address_missing"
    with _with(_world(profiles=[_profile(bundle_sid=None)])):
        assert (await perm.eligibility(_tenant()))["reason"] == "filing_has_no_bundle"


@pytest.mark.asyncio
async def test_no_filing_at_all_is_refused():
    with _with(_world(profiles=[])):
        assert (await perm.eligibility(_tenant()))["reason"] == "no_regulatory_filing"


@pytest.mark.asyncio
async def test_a_live_permanent_number_stops_a_second_acquisition():
    for status in (lifecycle.STATUS_PROVISIONING, lifecycle.STATUS_ACTIVE,
                   lifecycle.STATUS_RETIRING):
        with _with(_world(rows=[_row(status=status)])):
            out = await perm.eligibility(_tenant())
        assert out["eligible"] is False
        assert out["reason"] == perm.ALREADY_HELD, status


@pytest.mark.asyncio
async def test_an_active_temporary_number_does_not_block_acquisition():
    """The expected transitional state: the customer is taking calls on the
    temporary line while the permanent one is bought."""
    temp = _row(purpose=lifecycle.PURPOSE_TEMPORARY,
                status=lifecycle.STATUS_ACTIVE, e164=TEMP_E164, iso_country="GB")
    with _with(_world(rows=[temp])):
        out = await perm.eligibility(_tenant())
    assert out["eligible"] is True


@pytest.mark.asyncio
async def test_an_ineligible_tenant_never_reaches_the_provider(monkeypatch):
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    with _with(_world(profiles=[_profile(st.PENDING_REVIEW)])), \
         patch.object(perm, "get_client", return_value=_client_with(_tenant())), \
         patch.object(perm.tenant_subaccount, "ensure", new=AsyncMock()) as sub, \
         patch.object(perm.telephony, "purchase_regulated_number", new=AsyncMock()) as buy:
        out = await perm.ensure_permanent_irish_number(TENANT)
    assert out["status"] == perm.NOT_ELIGIBLE
    sub.assert_not_called(); buy.assert_not_called()


# ═══ 4. inventory: never substituted ═══════════════════════════════════

@pytest.mark.asyncio
async def test_no_inventory_is_reported_not_substituted(monkeypatch):
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    with _with(_world()), _with(_acquire_world(candidates=[])), \
         patch.object(perm.telephony, "purchase_regulated_number", new=AsyncMock()) as buy:
        out = await perm.ensure_permanent_irish_number(TENANT, locality="Cork")
    assert out["status"] == perm.INVENTORY_UNAVAILABLE
    assert out["locality"] == "Cork"
    buy.assert_not_called()


@pytest.mark.asyncio
async def test_a_requested_locality_is_never_silently_widened(monkeypatch):
    """A business that asked for Cork must not be handed Dublin."""
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    seen = {}

    async def search(sid, tok, cc, *, locality="", limit=10):
        seen["locality"] = locality
        return []

    with _with(_world()), _with(_acquire_world()), \
         patch.object(perm.telephony, "find_regulated_candidates", new=search):
        out = await perm.ensure_permanent_irish_number(TENANT, locality="Cork")
    assert seen["locality"] == "Cork"
    assert out["status"] == perm.INVENTORY_UNAVAILABLE


def test_the_regulated_search_helper_does_not_fall_back():
    """The CA/US helper walks area codes then goes national. The regulated one
    must not: substituting a city is exactly what Stage F forbids."""
    import inspect
    src = inspect.getsource(telephony.find_regulated_candidates)
    assert "National fallback" not in src
    assert "area_codes" not in src


def test_voice_is_required_and_sms_is_not():
    assert perm.REQUIRED_CAPABILITIES == ("voice",)
    assert _candidate(voice=True).supports("voice") is True
    assert _candidate(voice=False).supports("voice") is False


@pytest.mark.asyncio
async def test_a_voice_incapable_number_is_never_bought(monkeypatch):
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    with _with(_world()), _with(_acquire_world(candidates=[_candidate(voice=False)])), \
         patch.object(perm.telephony, "purchase_regulated_number", new=AsyncMock()) as buy:
        out = await perm.ensure_permanent_irish_number(TENANT)
    assert out["status"] == perm.INVENTORY_UNAVAILABLE
    assert out["reason"] == "no_voice_capable_inventory"
    buy.assert_not_called()


# ═══ 5. the purchase carries its regulatory bindings ═══════════════════

@pytest.mark.asyncio
async def test_the_purchase_passes_the_tenants_own_bundle_and_address(monkeypatch):
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    seen = {}

    async def buy(sid, tok, number, *, address_sid, bundle_sid):
        seen.update({"sid": sid, "number": number, "address_sid": address_sid,
                     "bundle_sid": bundle_sid})
        return IE_E164, "PNbought"

    with _with(_world()), _with(_acquire_world()), \
         patch.object(perm.telephony, "purchase_regulated_number", new=buy), \
         patch.object(perm, "_record_and_route",
                      new=AsyncMock(return_value={"status": perm.OK})):
        await perm.ensure_permanent_irish_number(TENANT)

    assert seen["sid"] == SUB
    assert seen["address_sid"] == ADDRESS_SID
    assert seen["bundle_sid"] == BUNDLE


@pytest.mark.asyncio
async def test_a_regulated_purchase_refuses_to_run_without_bindings():
    """A number bought without its bundle is a number whose compliance record
    does not point at it -- and Twilio would not necessarily say so."""
    for kwargs in ({"address_sid": "", "bundle_sid": BUNDLE},
                   {"address_sid": ADDRESS_SID, "bundle_sid": ""}):
        with pytest.raises(ValueError):
            await telephony.purchase_regulated_number(SUB, "tok", IE_E164, **kwargs)


def test_the_north_american_purchase_path_is_untouched():
    """CA/US must not acquire regulatory bindings it does not need."""
    import inspect
    src = inspect.getsource(telephony.purchase_number_with_sid)
    assert "address_sid" not in src and "bundle_sid" not in src
    assert "incoming_phone_numbers.create(phone_number=phone_number)" in src


# ═══ 6. unknown purchase outcome ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_an_unknown_purchase_outcome_adopts_rather_than_buying_again(monkeypatch):
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    buys = []

    async def buy(sid, tok, number, *, address_sid, bundle_sid):
        buys.append(number)
        raise TimeoutError("read timed out")

    empty = MagicMock(ok=True, numbers=[])
    after = MagicMock(ok=True, numbers=[MagicMock(phone_number=IE_E164, sid="PNreal")])

    with _with(_world()), _with(_acquire_world()), \
         patch.object(perm.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(side_effect=[empty, after])), \
         patch.object(perm.telephony, "purchase_regulated_number", new=buy), \
         patch.object(perm, "_record_and_route",
                      new=AsyncMock(return_value={"status": perm.OK})) as rec:
        out = await perm.ensure_permanent_irish_number(TENANT)

    assert len(buys) == 1
    assert out["status"] == perm.OK
    assert rec.call_args.kwargs["provider_sid"] == "PNreal"
    assert rec.call_args.kwargs["adopted"] is True


@pytest.mark.asyncio
async def test_a_genuine_refusal_is_not_reported_as_unknown(monkeypatch):
    """Commonly the address being incompatible with the number's locality. The
    customer's data is not wrong, so it is not reported as their error."""
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    empty = MagicMock(ok=True, numbers=[])
    with _with(_world()), _with(_acquire_world(
                purchase_error=RuntimeError("21649 not compatible"))), \
         patch.object(perm.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(return_value=empty)):
        out = await perm.ensure_permanent_irish_number(TENANT)
    assert out["status"] == perm.PURCHASE_REFUSED


@pytest.mark.asyncio
async def test_an_unreachable_provider_after_purchase_fails_closed(monkeypatch):
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    empty = MagicMock(ok=True, numbers=[])
    dead = MagicMock(ok=False, numbers=[])
    with _with(_world()), _with(_acquire_world(
                purchase_error=TimeoutError("read timed out"))), \
         patch.object(perm.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(side_effect=[empty, dead])):
        out = await perm.ensure_permanent_irish_number(TENANT)
    assert out["status"] == perm.PURCHASE_OUTCOME_UNKNOWN


@pytest.mark.asyncio
async def test_an_ambiguous_reconciliation_goes_to_an_operator(monkeypatch):
    """Adoption attaches a customer's regulatory filing to a specific number.
    With two candidates and no evidence, we cannot tell -- so nobody guesses."""
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    two = MagicMock(ok=True, numbers=[
        MagicMock(phone_number=IE_E164, sid="PNa"),
        MagicMock(phone_number="+35315550999", sid="PNb")])
    with _with(_world()), _with(_acquire_world()), \
         patch.object(perm.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(return_value=two)), \
         patch.object(perm.telephony, "purchase_regulated_number", new=AsyncMock()) as buy:
        out = await perm.ensure_permanent_irish_number(TENANT)
    assert out["status"] == perm.PURCHASE_OUTCOME_UNKNOWN
    assert out["reason"] == "multiple_unassigned_numbers"
    buy.assert_not_called()


@pytest.mark.asyncio
async def test_a_number_already_held_is_adopted_not_bought(monkeypatch):
    monkeypatch.setenv(perm.PURCHASE_GATE_ENV, "true")
    with _with(_world()), _with(_acquire_world(
                held=[{"e164": IE_E164, "sid": "PNheld"}])), \
         patch.object(perm.telephony, "purchase_regulated_number", new=AsyncMock()) as buy, \
         patch.object(perm, "_record_and_route",
                      new=AsyncMock(return_value={"status": perm.OK})) as rec:
        out = await perm.ensure_permanent_irish_number(TENANT)
    buy.assert_not_called()
    assert rec.call_args.kwargs["adopted"] is True


# ═══ 7. the gate ends at provisioning ══════════════════════════════════

@pytest.mark.asyncio
async def test_a_fully_successful_run_leaves_the_number_provisioning():
    registered = {}

    async def register(**kw):
        registered.update(kw)
        return {"status": phone_registry.OK, "row": _row()}

    with patch.object(perm.phone_registry, "register_permanent", new=register), \
         patch("services.vapi.import_twilio_number",
               new=AsyncMock(return_value="vapi_pn")), \
         patch.object(perm.phone_registry, "attach_routing",
                      new=AsyncMock(return_value={"status": "ok", "row": _row()})), \
         patch.object(perm.phone_registry, "mark_active", new=AsyncMock()) as act:
        out = await perm._record_and_route(
            tenant=_tenant(), e164=IE_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", profile=_profile(), address=_address(), adopted=False)

    assert out["status"] == perm.OK
    assert out["activated"] is False
    assert out["row"]["status"] == lifecycle.STATUS_PROVISIONING
    assert registered["iso_country"] == "IE"
    act.assert_not_called()


def test_a_provisioning_permanent_number_is_not_routable():
    assert lifecycle.is_routable(_row(status=lifecycle.STATUS_PROVISIONING)) is False


@pytest.mark.asyncio
async def test_acquisition_never_touches_the_legacy_scalar():
    """The scalar stays the compatibility pointer to the ACTIVE permanent line
    until W9I-G promotes this one."""
    with patch.object(perm.phone_registry, "register_permanent",
                      new=AsyncMock(return_value={"status": phone_registry.OK,
                                                  "row": _row()})), \
         patch("services.vapi.import_twilio_number",
               new=AsyncMock(return_value="vapi_pn")), \
         patch.object(perm.phone_registry, "attach_routing",
                      new=AsyncMock(return_value={"status": "ok", "row": _row()})), \
         patch.object(phone_registry.db, "update_tenant", new=AsyncMock()) as upd:
        await perm._record_and_route(
            tenant=_tenant(), e164=IE_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", profile=_profile(), address=_address(), adopted=False)
    upd.assert_not_called()


def test_attach_routing_cannot_change_a_status():
    """Acquisition and promotion are separate acts. A function that could do
    both would eventually be called for the wrong one."""
    import inspect
    src = inspect.getsource(phone_registry.attach_routing)
    body = src.split('"""')[2]
    # The PATCH must carry no status -- the returned envelope legitimately does.
    assert 'patch["status"]' not in body
    assert "STATUS_ACTIVE" not in body and "STATUS_" not in body
    assert '"status": lifecycle' not in body


@pytest.mark.asyncio
async def test_acquisition_never_touches_the_temporary_number():
    referenced = identifiers(perm)
    for forbidden in ("register_temporary", "mark_temporary_active",
                      "mark_released", "release_number", "retire"):
        assert forbidden not in referenced, forbidden


# ═══ 8. the billing firewall ══════════════════════════════════════════

def test_acquisition_cannot_reach_billing_or_activation():
    """MANDATORY. Even a fully successful +353 acquisition is not trial start."""
    referenced = identifiers(perm)
    for forbidden in ("create_trial_subscription", "create_subscription", "stripe",
                      "start_trial", "trial_status", "subscriptions",
                      "send_welcome_email", "send_activation_email",
                      "mark_active", "PLAN_LIST_PRICES"):
        assert forbidden not in referenced, forbidden


# ═══ 9. routing uses the existing assistant ═══════════════════════════

@pytest.mark.asyncio
async def test_routing_uses_the_tenants_existing_assistant():
    seen = {}

    async def import_number(**kw):
        seen.update(kw)
        return "vapi_pn_perm"

    with patch.object(perm.phone_registry, "register_permanent",
                      new=AsyncMock(return_value={"status": phone_registry.OK,
                                                  "row": _row()})), \
         patch("services.vapi.import_twilio_number", new=import_number), \
         patch.object(perm.phone_registry, "attach_routing",
                      new=AsyncMock(return_value={"status": "ok", "row": _row()})):
        await perm._record_and_route(
            tenant=_tenant(), e164=IE_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", profile=_profile(), address=_address(), adopted=False)
    assert seen["assistant_id"] == "asst_1"


def test_no_second_assistant_is_ever_created():
    referenced = identifiers(perm)
    assert "create_assistant" not in referenced
    assert "create_suborg" not in referenced


@pytest.mark.asyncio
async def test_a_routing_failure_leaves_the_number_held_and_retryable():
    """A month's rental is cheap next to losing a number that required
    regulatory approval -- and the customer still has their temporary line."""
    with patch.object(perm.phone_registry, "register_permanent",
                      new=AsyncMock(return_value={"status": phone_registry.OK,
                                                  "row": _row()})), \
         patch("services.vapi.import_twilio_number",
               new=AsyncMock(side_effect=RuntimeError("vapi 500"))), \
         patch.object(perm.telephony, "release_number", new=AsyncMock()) as rel, \
         patch.object(perm.phone_registry, "attach_routing", new=AsyncMock()) as att:
        out = await perm._record_and_route(
            tenant=_tenant(), e164=IE_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", profile=_profile(), address=_address(), adopted=False)
    assert out["status"] == perm.ROUTING_FAILED
    assert out["row"]["status"] == lifecycle.STATUS_PROVISIONING
    rel.assert_not_called()
    att.assert_not_called()


@pytest.mark.asyncio
async def test_a_registration_conflict_does_not_throw_the_number_away():
    """Unlike the temporary path: this number took a regulator's approval to
    obtain, and the winner's row may already describe it."""
    with patch.object(perm.phone_registry, "register_permanent",
                      new=AsyncMock(return_value={"status": phone_registry.CONFLICT,
                                                  "row": None,
                                                  "detail": "tpn_one_current_permanent"})), \
         patch.object(perm.telephony, "release_number", new=AsyncMock()) as rel:
        out = await perm._record_and_route(
            tenant=_tenant(), e164=IE_E164, provider_sid="PNx", sub_sid=SUB,
            sub_tok="tok", profile=_profile(), address=_address(), adopted=False)
    assert out["status"] == perm.PURCHASE_OUTCOME_UNKNOWN
    rel.assert_not_called()


@pytest.mark.asyncio
async def test_no_assistant_means_no_routing_attempt():
    with patch.object(perm.phone_registry, "register_permanent",
                      new=AsyncMock(return_value={"status": phone_registry.OK,
                                                  "row": _row()})), \
         patch("services.vapi.import_twilio_number", new=AsyncMock()) as imp:
        out = await perm._record_and_route(
            tenant=_tenant(vapi_assistant_id=""), e164=IE_E164, provider_sid="PNx",
            sub_sid=SUB, sub_tok="tok", profile=_profile(), address=_address(),
            adopted=False)
    assert out["status"] == perm.ROUTING_FAILED
    imp.assert_not_called()


# ═══ 10. the customer status contract ═════════════════════════════════

LEAKS = re.compile(
    r"\b(?:AC|AD|RN|PN|BU|IT)[0-9a-f]{32}\b|BundleSid|AddressSid|twilio|"
    r"ProviderError|HTTP \d{3}|_sid\b", re.I)


@pytest.mark.parametrize("status", [
    perm.GATE_CLOSED, perm.NOT_APPROVED, perm.VERIFICATION_UNAVAILABLE,
    perm.INVENTORY_UNAVAILABLE, perm.PROVIDER_UNAVAILABLE, perm.PURCHASE_REFUSED,
    perm.PURCHASE_OUTCOME_UNKNOWN, perm.ROUTING_FAILED, perm.ALREADY_HELD,
    perm.OK, perm.NOT_ELIGIBLE, perm.NOT_FOUND, "something_new",
])
def test_every_outcome_has_a_safe_customer_status(status):
    view = perm.customer_status(status, _row())
    assert view["message"]
    assert not LEAKS.search(str(view)), view
    # NOTHING in this gate is active.
    assert view["active"] is False


def test_a_closed_gate_never_mentions_commercial_or_legal_detail():
    view = perm.customer_status(perm.GATE_CLOSED)
    assert view["status"] == perm.PENDING_PLATFORM_ENABLEMENT
    blob = view["message"].lower()
    for leak in ("reseller", "contract", "terms", "commercial", "legal",
                 "licence", "license", "twilio"):
        assert leak not in blob, leak


def test_a_number_is_shown_only_once_it_is_recorded():
    """A number shown from an in-flight purchase is one the customer writes down
    before it fails to register."""
    assert "number" not in perm.customer_status(perm.PROVIDER_UNAVAILABLE, _row())
    assert perm.customer_status(perm.OK, _row())["number"] == IE_E164
    assert "number" not in perm.customer_status(perm.OK, None)


# ═══ 11. nothing else changed ═════════════════════════════════════════

def test_the_temporary_flow_is_untouched():
    from services import temporary_numbers as tmp
    referenced = identifiers(tmp)
    for forbidden in ("ensure_permanent_irish_number", "purchase_regulated_number",
                      "permanent_numbers"):
        assert forbidden not in referenced, forbidden


def test_public_ireland_onboarding_is_still_off(monkeypatch):
    from services import onboarding_lifecycle as ob
    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    assert ob.ireland_onboarding_enabled() is False


def test_ca_and_us_country_config_is_unchanged():
    assert telephony._COUNTRY_CONFIG["CA"]["area_codes"][0] == "416"
    assert telephony._COUNTRY_CONFIG["IE"]["twilio_code"] == "IE"
    assert "IE" in telephony.SUPPORTED_COUNTRIES
