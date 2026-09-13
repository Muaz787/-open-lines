"""W9I-H.AUTO Stage R — the Irish purchase gate is authoritative everywhere.

W9I-H.PRE found the admin reprovision path refusing an Irish tenant only by
accident: the tenant happened to have no Vapi assistant, and Twilio happened to
reject a number bought without an AddressSid. Neither is a gate we own. The
first disappears the moment a regulated tenant legitimately has an assistant,
and the second is a provider behaviour we observed rather than a rule we set.

These pin the ownership: regulated acquisition belongs to permanent_numbers,
behind IRELAND_PERMANENT_NUMBER_PURCHASE_ENABLED, and every other path refuses
before it can spend.
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import onboarding_lifecycle as ob
from services import permanent_numbers as perm
from services import provisioning
from services import telephony
from services import temporary_numbers as temp


# ── the choke point ──────────────────────────────────────────────────────

def test_the_regulated_prefix_table_cannot_drift_from_the_country_list():
    """Adding a regulated country without its dial prefix would silently
    reopen this path for that country."""
    missing = ob.REGULATED_COUNTRIES - set(telephony._REGULATED_DIAL_PREFIXES)
    assert not missing, f"no dial prefix for regulated {missing}"


@pytest.mark.parametrize("number,expected", [
    ("+353871234567", "IE"),
    ("+353 87 123 4567", "IE"),
    ("+14165550100", ""),
    ("+12899071026", ""),
    ("+442071234567", ""),
    ("", ""),
])
def test_regulated_numbers_are_recognised_by_their_prefix(number, expected):
    assert telephony._regulated_country_of(number) == expected


@pytest.mark.asyncio
async def test_the_unregulated_path_refuses_an_irish_number():
    """The refusal must be OURS, and must happen before Twilio is called."""
    client = MagicMock()
    with patch.object(telephony, "_sub_client", return_value=client):
        with pytest.raises(telephony.RegulatedNumberRefused) as exc:
            await telephony.purchase_number_with_sid("AC_sub", "tok", "+353871234567")
    assert exc.value.iso_country == "IE"
    client.incoming_phone_numbers.create.assert_not_called()


@pytest.mark.asyncio
async def test_the_unregulated_path_still_buys_canadian_numbers():
    """CA/US behaviour is untouched -- the gate must not become a blanket."""
    client = MagicMock()
    client.incoming_phone_numbers.create.return_value = MagicMock(
        phone_number="+14165550100", sid="PN123")
    with patch.object(telephony, "_sub_client", return_value=client):
        e164, sid = await telephony.purchase_number_with_sid(
            "AC_sub", "tok", "+14165550100")
    assert (e164, sid) == ("+14165550100", "PN123")
    assert client.incoming_phone_numbers.create.call_count == 1


def test_the_refusal_has_its_own_type():
    """So a caller reports it honestly instead of as a generic provider fault."""
    assert issubclass(telephony.RegulatedNumberRefused, Exception)
    assert not issubclass(telephony.RegulatedNumberRefused,
                          telephony.CountryNotSupported)


# ── admin reprovision ────────────────────────────────────────────────────

def _tenant(**over):
    return {"id": "t1", "country": "CA", "twilio_phone_number": None,
            "twilio_subaccount_sid": "AC_sub", "twilio_auth_token": "tok",
            "vapi_assistant_id": "asst_1", **over}


@pytest.mark.asyncio
async def test_admin_reprovision_refuses_a_regulated_tenant_deliberately():
    """Refused for the RIGHT reason -- not because an assistant is missing."""
    with patch.object(provisioning.phone_registry, "current_permanent_conflict",
                      new=AsyncMock(return_value=None)), \
         patch.object(provisioning.telephony, "find_available_number",
                      new=AsyncMock(side_effect=AssertionError("SEARCHED"))), \
         patch.object(provisioning.telephony, "purchase_number_with_sid",
                      new=AsyncMock(side_effect=AssertionError("BOUGHT"))):
        out = await provisioning.reprovision_tenant_number(_tenant(country="IE"))
    assert out["provisioned"] is False
    assert out["reason"] == "country_requires_regulated_acquisition"


@pytest.mark.asyncio
async def test_admin_reprovision_refuses_even_a_fully_equipped_irish_tenant():
    """The incidental guard PRE relied on -- a missing assistant -- is gone
    here, so only the deliberate one can be doing the work."""
    with patch.object(provisioning.phone_registry, "current_permanent_conflict",
                      new=AsyncMock(return_value=None)), \
         patch.object(provisioning.telephony, "find_available_number",
                      new=AsyncMock(side_effect=AssertionError("SEARCHED"))), \
         patch.object(provisioning.telephony, "purchase_number_with_sid",
                      new=AsyncMock(side_effect=AssertionError("BOUGHT"))):
        out = await provisioning.reprovision_tenant_number(
            _tenant(country="IE", vapi_assistant_id="asst_real"))
    assert out["reason"] == "country_requires_regulated_acquisition"


@pytest.mark.asyncio
async def test_admin_reprovision_still_works_for_canada():
    with patch.object(provisioning.phone_registry, "current_permanent_conflict",
                      new=AsyncMock(return_value=None)), \
         patch.object(provisioning.telephony, "find_available_number",
                      new=AsyncMock(return_value="+14165550100")), \
         patch.object(provisioning.telephony, "purchase_number_with_sid",
                      new=AsyncMock(return_value=("+14165550100", "PN1"))), \
         patch.object(provisioning.vapi, "import_twilio_number",
                      new=AsyncMock(return_value="vp1")), \
         patch.object(provisioning.phone_registry, "register_permanent",
                      new=AsyncMock(return_value={"ok": True})), \
         patch("db.supabase.update_tenant", new=AsyncMock()):
        out = await provisioning.reprovision_tenant_number(_tenant())
    assert out.get("reason") != "country_requires_regulated_acquisition"


# ── the temporary source ─────────────────────────────────────────────────

def test_a_regulated_temporary_source_is_refused(monkeypatch):
    """TEMP_NUMBER_SOURCE_COUNTRY=IE would buy an Irish number through the
    unregulated path -- no Bundle, no Address, no commercial gate -- and hand
    the customer a +353 that is NOT the one their filing covers."""
    monkeypatch.setenv(temp.ENABLED_ENV, "true")
    monkeypatch.setenv(temp.SOURCE_ENV, "IE")
    problem = temp.source_problem(temp.source_policy())
    assert problem == "source_country_is_regulated:IE"


@pytest.mark.parametrize("source", ["CA", "US", "GB"])
def test_an_unregulated_temporary_source_is_accepted(monkeypatch, source):
    monkeypatch.setenv(temp.ENABLED_ENV, "true")
    monkeypatch.setenv(temp.SOURCE_ENV, source)
    assert temp.source_problem(temp.source_policy()) == ""


def test_the_temporary_source_is_still_never_defaulted(monkeypatch):
    monkeypatch.setenv(temp.ENABLED_ENV, "true")
    monkeypatch.delenv(temp.SOURCE_ENV, raising=False)
    assert temp.source_problem(temp.source_policy()) == "no_source_country_configured"


@pytest.mark.asyncio
async def test_a_regulated_source_stops_before_any_provider_call(monkeypatch):
    monkeypatch.setenv(temp.ENABLED_ENV, "true")
    monkeypatch.setenv(temp.SOURCE_ENV, "IE")
    tenant = {"id": "t1", "business_country_code": "IE"}
    with patch.object(temp, "get_client", return_value=MagicMock(
            **{"table.return_value.select.return_value.eq.return_value"
               ".limit.return_value.execute.return_value.data": [tenant]})), \
         patch.object(temp, "eligibility",
                      new=AsyncMock(return_value={"eligible": True, "reason": "",
                                                  "detail": "", "profile": {},
                                                  "existing": None, "active": False})), \
         patch.object(temp.tenant_subaccount, "ensure",
                      new=AsyncMock(side_effect=AssertionError("REACHED PROVIDER"))):
        out = await temp.ensure_temporary_number("t1",
        verified_provider_status="pending-review")
    assert out["status"] == temp.UNAVAILABLE
    assert out["reason"] == "source_country_is_regulated:IE"


# ── the permanent gate remains the only route ────────────────────────────

@pytest.mark.asyncio
async def test_regulated_acquisition_still_honours_the_commercial_gate(monkeypatch):
    monkeypatch.delenv(perm.PURCHASE_GATE_ENV, raising=False)
    with patch.object(perm, "_tenant", new=AsyncMock(return_value={"id": "t1"})), \
         patch.object(perm, "eligibility",
                      new=AsyncMock(side_effect=AssertionError("CHECKED ELIGIBILITY"))):
        out = await perm.ensure_permanent_irish_number("t1")
    assert out["status"] == perm.GATE_CLOSED


def test_every_purchase_path_is_accounted_for():
    """A new acquisition call site must be a deliberate decision, not a
    surprise. If this fails, classify the new site before changing the number."""
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parent.parent
    sites = []
    for py in list((root / "services").glob("*.py")) + list((root / "routers").glob("*.py")):
        for i, line in enumerate(py.read_text().splitlines(), 1):
            if re.search(r"\.(purchase_number_with_sid|purchase_regulated_number)\(", line):
                sites.append(f"{py.name}:{i}")
    # temporary_numbers (unregulated source only), provisioning signup (regulated
    # countries divert before it), provisioning reprovision (now refuses
    # regulated), permanent_numbers (the one regulated path, gated).
    assert len(sites) == 4, f"unclassified acquisition sites: {sites}"
