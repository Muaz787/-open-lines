"""W9G.3 — the provider declaration policy, and everything it must NOT do.

Twilio Support confirmed, for OpenLines as an ISV with one subaccount per customer
and the number living in that subaccount:

    the SMB customer is the EndUser (for DANI: DANI, not OpenLines)
    business_identity = DIRECT_CUSTOMER   -- describes the SMB customer
    is_subassigned    = NO                -- also describes the SMB customer
    no separate OpenLines ISV identity is required inside the customer's Bundle
    the subaccount architecture does not change the answer

That answer is specific. It is not a general truth about regulatory bundles, so the
mapping is keyed on the full context with no fallback, and it stays subordinate to
whatever the live Regulation API currently accepts.
"""
import pytest

from services import regulatory_declaration as rd
from services import regulatory_requirements as rq
from tests.test_w9g_regulation_discovery import FakeRegulation, IE_REQUIREMENTS

IE = dict(iso_country="IE", number_type="local", end_user_type="business")
REQS = rq.normalize_regulation(FakeRegulation())


# ── 1-2: the confirmed context resolves exactly what Twilio said ───────────

def test_the_confirmed_context_resolves_DIRECT_CUSTOMER():
    assert rd.resolve(**IE).business_identity == "DIRECT_CUSTOMER"


def test_the_confirmed_context_resolves_is_subassigned_NO():
    assert rd.resolve(**IE).is_subassigned == "NO"


def test_the_policy_records_who_the_declaration_describes():
    """Twilio was explicit that both fields describe the SMB customer, not
    OpenLines. Recording it keeps the reasoning with the value."""
    p = rd.resolve(**IE)
    assert p.subject == rd.SUBJECT_TENANT_END_USER
    assert p.architecture == rd.ARCHITECTURE_ISV_CUSTOMER_SUBACCOUNT
    assert "twilio_support" in p.source


def test_as_attributes_returns_exactly_the_two_fields():
    assert rd.resolve(**IE).as_attributes() == {
        "business_identity": "DIRECT_CUSTOMER", "is_subassigned": "NO"}


# ── 3-10: nothing inherits the mapping ────────────────────────────────────

@pytest.mark.parametrize("country", ["US", "CA", "GB", "FR", "DE", "AU", "NZ", "ZZ"])
def test_no_other_country_inherits_the_mapping(country):
    assert rd.resolve(iso_country=country, number_type="local",
                      end_user_type="business") is None


@pytest.mark.parametrize("number_type", ["mobile", "toll-free", "national",
                                         "shared-cost", ""])
def test_no_other_number_type_inherits_the_mapping(number_type):
    assert rd.resolve(iso_country="IE", number_type=number_type,
                      end_user_type="business") is None


@pytest.mark.parametrize("end_user_type", ["individual", "personal", ""])
def test_no_other_end_user_type_inherits_the_mapping(end_user_type):
    assert rd.resolve(iso_country="IE", number_type="local",
                      end_user_type=end_user_type) is None


@pytest.mark.parametrize("provider", ["vonage", "bandwidth", "messagebird", ""])
def test_no_other_provider_inherits_the_mapping(provider):
    assert rd.resolve(provider=provider, **IE) is None


@pytest.mark.parametrize("architecture", [
    "direct_customer_own_account", "reseller_parent_account", "unknown", ""])
def test_no_other_architecture_inherits_the_mapping(architecture):
    """A future arrangement where OpenLines holds the number itself could invert
    the answer, so the architecture is part of the key."""
    assert rd.resolve(**IE, architecture=architecture) is None


def test_there_is_exactly_one_policy_and_no_wildcard():
    assert len(rd._POLICIES) == 1
    for key in rd._POLICIES:
        assert all(part and part != "*" for part in key)


def test_case_and_whitespace_are_normalised_but_nothing_else_is():
    assert rd.resolve(provider="TWILIO", iso_country=" ie ", number_type="LOCAL",
                      end_user_type="Business") is not None
    assert rd.resolve(iso_country="IE", number_type="local ie",
                      end_user_type="business") is None


# ── 11-16: the live Regulation stays the authority ────────────────────────

def test_the_current_regulation_accepts_both_confirmed_values():
    status, detail = rd.validate_against_regulation(rd.resolve(**IE), REQS)
    assert status == rd.RESOLVED and detail == ""


def _with_options(field, options_text):
    return rq.normalize_regulation(FakeRegulation(requirements={
        "end_user": [{**IE_REQUIREMENTS["end_user"][0],
                      "detailed_fields": [
                          {**d, "description": options_text}
                          if d["machine_name"] == field else d
                          for d in IE_REQUIREMENTS["end_user"][0]["detailed_fields"]]}],
        "supporting_document": IE_REQUIREMENTS["supporting_document"]}))


def test_a_provider_that_stops_accepting_DIRECT_CUSTOMER_fails_closed():
    """A support answer from the past is not licence to file a value the provider
    now rejects."""
    reqs = _with_options("business_identity",
                         "Choose any one of the following values: [RESELLER, AGENCY].")
    status, detail = rd.validate_against_regulation(rd.resolve(**IE), reqs)
    assert status == rd.VALUE_REJECTED
    assert "business_identity=DIRECT_CUSTOMER" in detail


def test_a_provider_that_stops_accepting_NO_fails_closed():
    reqs = _with_options("is_subassigned",
                         "Choose any one of the following values : [YES, PARTIAL].")
    status, detail = rd.validate_against_regulation(rd.resolve(**IE), reqs)
    assert status == rd.VALUE_REJECTED
    assert "is_subassigned=NO" in detail


def _without(field):
    return rq.normalize_regulation(FakeRegulation(requirements={
        "end_user": [{**IE_REQUIREMENTS["end_user"][0],
                      "fields": [f for f in IE_REQUIREMENTS["end_user"][0]["fields"]
                                 if f != field]}],
        "supporting_document": IE_REQUIREMENTS["supporting_document"]}))


@pytest.mark.parametrize("field", ["business_identity", "is_subassigned"])
def test_a_field_the_regulation_drops_is_simply_not_declared(field):
    """Not every change is a failure. A field the provider stopped asking for is
    nothing to declare -- and sending it would be stating something the regulation
    no longer defines."""
    reqs = _without(field)
    status, _ = rd.validate_against_regulation(rd.resolve(**IE), reqs)
    assert status == rd.RESOLVED
    assert field not in rd.applicable_attributes(rd.resolve(**IE), reqs)


def test_applicable_attributes_never_sends_an_unasked_field():
    reqs = _without("is_subassigned")
    attrs = rd.applicable_attributes(rd.resolve(**IE), reqs)
    assert attrs == {"business_identity": "DIRECT_CUSTOMER"}


def test_a_free_text_field_is_not_rejected_for_its_value():
    """If the provider stops enumerating options, we cannot judge the value -- and
    guessing that it is now invalid would block onboarding for no reason."""
    reqs = _with_options("business_identity", "Any text is accepted here.")
    status, _ = rd.validate_against_regulation(rd.resolve(**IE), reqs)
    assert status == rd.RESOLVED


# ── 21-23: nothing can override the system-sourced value ──────────────────

def test_no_environment_variable_can_override_the_policy(monkeypatch):
    monkeypatch.setenv("BUSINESS_IDENTITY", "INDEPENDENT_SOFTWARE_VENDOR")
    monkeypatch.setenv("IS_SUBASSIGNED", "YES")
    monkeypatch.setenv("REGULATORY_BUSINESS_IDENTITY", "RESELLER")
    p = rd.resolve(**IE)
    assert p.business_identity == "DIRECT_CUSTOMER" and p.is_subassigned == "NO"


def test_the_policy_module_reads_no_environment_at_all():
    import inspect
    src = inspect.getsource(rd)
    assert "os.environ" not in src and "getenv" not in src


def test_the_policy_object_is_immutable():
    """An operator default cannot be installed at runtime by mutating it."""
    p = rd.resolve(**IE)
    with pytest.raises(Exception):
        p.business_identity = "INDEPENDENT_SOFTWARE_VENDOR"


def test_the_declaration_values_live_in_exactly_one_place():
    """The whole point of the policy module: the values must not be scattered."""
    import inspect
    import sys
    sys.path.insert(0, ".")
    from tests.test_w9g1_durability import _executable_source
    from services import regulatory_engine, regulatory_ireland, regulatory_requirements
    for mod in (regulatory_engine, regulatory_ireland, regulatory_requirements):
        code = _executable_source(mod)
        for value in ("DIRECT_CUSTOMER", "INDEPENDENT_SOFTWARE_VENDOR"):
            assert value not in code, f"{mod.__name__} hardcodes {value}"
    # and exactly once in the policy module itself
    policy_code = _executable_source(rd)
    assert policy_code.count("DIRECT_CUSTOMER") == 1


# ── the customer cannot inject a declaration ──────────────────────────────
#
# A mutation run exposed this: the policy merged OVER customer input, but customer
# input was still PERSISTED first -- so a value POSTed once came back as "history"
# on the next request and was honoured. Anyone could have injected a false
# regulatory declaration by sending it a single time.

import pytest as _pytest  # noqa: E402
from services import regulatory_engine as engine  # noqa: E402
from tests.test_w9g_engine import (GOOD_ADDRESS, GOOD_ATTRS, tenant, world)  # noqa: F401,E402


@_pytest.mark.asyncio
async def test_a_customer_supplied_declaration_is_IGNORED_not_persisted(world):
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    hostile = {**GOOD_ATTRS,
               "business_identity": "INDEPENDENT_SOFTWARE_VENDOR",
               "is_subassigned": "YES"}
    r = await engine.prepare_profile(tenant(), attributes=hostile)
    assert r["ok"], r
    sent = world["twilio"].last_end_user_attributes
    assert sent["business_identity"] == "DIRECT_CUSTOMER", "the policy must win"
    assert sent["is_subassigned"] == "NO"
    stored = world["details"][0]
    assert stored["business_identity"] == "DIRECT_CUSTOMER"
    assert stored["is_subassigned"] == "NO"


@_pytest.mark.asyncio
async def test_an_injected_value_cannot_come_back_as_history_on_a_later_request(world):
    """The exact hole: persist once, honour forever."""
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    await engine.prepare_profile(
        tenant(), attributes={**GOOD_ATTRS,
                              "business_identity": "INDEPENDENT_SOFTWARE_VENDOR",
                              "is_subassigned": "YES"})
    world["twilio"].last_end_user_attributes = None
    world["profiles"].clear()
    world["twilio"].created["end_user"] = 0
    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["ok"], r
    assert world["details"][0]["business_identity"] == "DIRECT_CUSTOMER"


@_pytest.mark.asyncio
async def test_customer_facts_are_still_accepted_normally(world):
    """Stripping the declaration must not strip anything else."""
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    await engine.prepare_profile(
        tenant(), attributes={**GOOD_ATTRS, "business_name": "DANI Retail Ltd"})
    stored = world["details"][0]
    assert stored["business_name"] == "DANI Retail Ltd"
    assert stored["authorized_rep_email"] == "ann@dani.ie"
