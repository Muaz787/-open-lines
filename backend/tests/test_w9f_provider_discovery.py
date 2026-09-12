"""W9F — provider-number discovery must distinguish "holds nothing" from "we don't know".

WHY THIS EXISTS. W9D's helper returned [] both when Twilio said an account holds no
numbers and when the call to Twilio failed. For ordinary runtime code that conflation
is a safe default. For an OWNERSHIP MIGRATION it is wrong in both directions:

  * reading a provider outage as "owns no numbers" would let a backfill conclude a
    live number does not exist
  * reading a genuinely empty account as "unknown" hides a real, permanent data
    inconsistency behind a reason string that reads like a transient outage

W9E hit the second case for real: a tenant whose number had been released at Twilio
was reported as `provider_numbers_unavailable`. The number was gone for good.
"""
from unittest.mock import patch

import pytest

from services import phone_backfill as bf
from services import telephony

SUB = "ACsubaccount0000000000000000000001"
PN = "PNnumber000000000000000000000001"
NUMBER = "+14374769911"


class _Numbers:
    def __init__(self, rows): self._rows = rows
    def list(self, limit=None): return self._rows


class _SubClient:
    def __init__(self, rows): self.incoming_phone_numbers = _Numbers(rows)


class _Row:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _twilio_row(**over):
    base = dict(sid=PN, phone_number=NUMBER, account_sid=SUB, date_created=None,
                status="in-use", origin="twilio")
    base.update(over)
    return _Row(**base)


# ── 1-3: the three distinct outcomes ───────────────────────────────────────

@pytest.mark.asyncio
async def test_success_with_zero_numbers_is_AUTHORITATIVELY_EMPTY():
    with patch("services.telephony._sub_client", return_value=_SubClient([])):
        r = await telephony.fetch_subaccount_numbers(SUB, "tok")
    assert r.ok is True
    assert r.numbers == ()
    assert r.is_empty is True
    assert r.error_detail == ""


@pytest.mark.asyncio
async def test_provider_exception_is_UNAVAILABLE_and_never_looks_empty():
    class _Boom:
        @property
        def incoming_phone_numbers(self):
            raise RuntimeError("network down")
    with patch("services.telephony._sub_client", return_value=_Boom()):
        r = await telephony.fetch_subaccount_numbers(SUB, "tok")
    assert r.ok is False
    assert r.is_empty is False, "unknown must never read as empty"
    assert r.numbers == ()
    assert "RuntimeError" in r.error_detail


@pytest.mark.asyncio
async def test_success_with_one_number_returns_a_usable_list():
    with patch("services.telephony._sub_client",
               return_value=_SubClient([_twilio_row()])):
        r = await telephony.fetch_subaccount_numbers(SUB, "tok")
    assert r.ok and not r.is_empty
    assert len(r.numbers) == 1
    assert r.numbers[0]["phone_number"] == NUMBER
    assert r.numbers[0]["sid"] == PN
    assert r.numbers[0]["account_sid"] == SUB


@pytest.mark.asyncio
async def test_missing_credentials_is_an_ERROR_not_an_empty_account():
    """We have not asked the provider anything, so we know nothing."""
    for sid, tok in ((""," tok"), (SUB, ""), ("", "")):
        r = await telephony.fetch_subaccount_numbers(sid, tok.strip())
        assert r.ok is False
        assert r.is_empty is False
        assert r.error_detail == "missing_credentials"


@pytest.mark.asyncio
async def test_error_detail_carries_no_provider_message_or_credential():
    """The detail is built from the exception type, HTTP status and Twilio code only.
    A provider message body echoes the request, including the account SID used to
    authenticate it."""
    class _Exc(Exception):
        status = 401
        code = 20003
        msg = f"Authentication Error for {SUB} with token SUPERSECRETTOKEN at https://api.twilio.com/2010-04-01/Accounts/{SUB}"
    class _Boom:
        @property
        def incoming_phone_numbers(self):
            raise _Exc("Authentication Error")
    with patch("services.telephony._sub_client", return_value=_Boom()):
        r = await telephony.fetch_subaccount_numbers(SUB, "tok")
    assert r.ok is False
    assert "http=401" in r.error_detail
    assert "twilio_code=20003" in r.error_detail
    assert SUB not in r.error_detail
    assert "SUPERSECRETTOKEN" not in r.error_detail
    assert "twilio.com" not in r.error_detail
    assert "Authentication Error" not in r.error_detail


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [ValueError("bad"), TypeError("worse"),
                                 ConnectionResetError("reset"), Exception("plain")])
async def test_the_helper_never_raises_for_any_provider_exception(exc):
    """Deliberately NOT parametrised over BaseException (KeyboardInterrupt,
    SystemExit): those must keep propagating, because swallowing them would make a
    long backfill un-interruptible."""
    class _Boom:
        @property
        def incoming_phone_numbers(self):
            raise exc
    with patch("services.telephony._sub_client", return_value=_Boom()):
        r = await telephony.fetch_subaccount_numbers(SUB, "tok")
    assert r.ok is False
    assert r.is_empty is False
    assert type(exc).__name__ in r.error_detail


@pytest.mark.asyncio
async def test_an_interrupt_is_NOT_swallowed():
    """A backfill over every tenant must stay interruptible."""
    class _Boom:
        @property
        def incoming_phone_numbers(self):
            raise KeyboardInterrupt("stop")
    with patch("services.telephony._sub_client", return_value=_Boom()):
        with pytest.raises(KeyboardInterrupt):
            await telephony.fetch_subaccount_numbers(SUB, "tok")


# ── 4-8: what the backfill does with each outcome ──────────────────────────

TENANT = "11111111-1111-1111-1111-111111111111"


def tenant(**over):
    base = {"id": TENANT, "business_name": "Visado", "twilio_phone_number": NUMBER,
            "twilio_subaccount_sid": SUB, "twilio_auth_token": "tok",
            "vapi_phone_number_id": "vapi-1", "country": "US"}
    base.update(over)
    return base


@pytest.fixture
def world(monkeypatch):
    state = {"listing": telephony.ProviderNumberList(
                 status="success", numbers=(dict(sid=PN, phone_number=NUMBER,
                                                 account_sid=SUB, date_created=None,
                                                 status="in-use", origin="twilio"),)),
             "country": "CA", "existing": [], "inserted": []}

    async def fake_fetch(sub_sid, sub_token):
        return state["listing"]
    async def fake_country(number):
        return state["country"]
    async def fake_existing(tenant_id, purpose="", statuses=()):
        return state["existing"]
    async def fake_insert(row):
        state["inserted"].append(row)
        return {**row, "id": "new-id"}

    monkeypatch.setattr(bf.telephony, "fetch_subaccount_numbers", fake_fetch)
    monkeypatch.setattr(bf.telephony, "lookup_iso_country", fake_country)
    monkeypatch.setattr(bf.db_phone, "list_for_tenant", fake_existing)
    monkeypatch.setattr(bf.db_phone, "insert_number", fake_insert)
    return state


@pytest.mark.asyncio
async def test_backfill_skips_an_EMPTY_ACCOUNT_with_its_own_precise_reason(world):
    """The W9E Visado case: Twilio answered, the account holds nothing, so the scalar
    points at a number we do not own. Permanent, not retryable."""
    world["listing"] = telephony.ProviderNumberList(status="success", numbers=())
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("skip", "provider_account_empty")
    assert "provider_error" not in r


@pytest.mark.asyncio
async def test_backfill_skips_a_PROVIDER_OUTAGE_with_a_different_reason(world):
    world["listing"] = telephony.ProviderNumberList(
        status="error", error_detail="TwilioRestException http=500")
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("skip", "provider_numbers_unavailable")
    assert r["provider_error"] == "TwilioRestException http=500"


@pytest.mark.asyncio
async def test_the_two_skip_reasons_are_never_the_same_string(world):
    world["listing"] = telephony.ProviderNumberList(status="success", numbers=())
    empty = (await bf.plan_tenant(tenant()))["reason"]
    world["listing"] = telephony.ProviderNumberList(status="error", error_detail="x")
    outage = (await bf.plan_tenant(tenant()))["reason"]
    assert empty != outage
    assert {empty, outage} == {"provider_account_empty", "provider_numbers_unavailable"}


@pytest.mark.asyncio
@pytest.mark.parametrize("listing,reason", [
    (telephony.ProviderNumberList(status="success", numbers=()), "provider_account_empty"),
    (telephony.ProviderNumberList(status="error", error_detail="boom"),
     "provider_numbers_unavailable"),
])
async def test_neither_skip_state_writes_anything_even_in_live_mode(world, listing, reason):
    world["listing"] = listing
    r = await bf.backfill_tenant(tenant(), dry_run=False)
    assert (r["action"], r["reason"]) == ("skip", reason)
    assert world["inserted"] == []


@pytest.mark.asyncio
async def test_a_tenant_blocked_by_an_outage_becomes_READY_on_retry(world):
    """The distinction has to be actionable: an outage is retryable, and the retry
    must succeed without anyone editing data."""
    world["listing"] = telephony.ProviderNumberList(status="error", error_detail="boom")
    assert (await bf.plan_tenant(tenant()))["reason"] == "provider_numbers_unavailable"

    world["listing"] = telephony.ProviderNumberList(
        status="success", numbers=(dict(sid=PN, phone_number=NUMBER, account_sid=SUB,
                                        date_created=None, status="in-use",
                                        origin="twilio"),))
    r = await bf.plan_tenant(tenant())
    assert r["action"] == "propose"
    assert r["row"]["provider_sid"] == PN


@pytest.mark.asyncio
async def test_an_empty_account_NEVER_becomes_ready_on_retry(world):
    """A stale scalar is not a transient condition. Retrying changes nothing, and no
    canonical ownership row is ever produced for a number we do not own."""
    world["listing"] = telephony.ProviderNumberList(status="success", numbers=())
    for _ in range(3):
        r = await bf.backfill_tenant(tenant(), dry_run=False)
        assert (r["action"], r["reason"]) == ("skip", "provider_account_empty")
    assert world["inserted"] == []


@pytest.mark.asyncio
async def test_a_stale_scalar_never_produces_a_canonical_ownership_row(world):
    """Belt and braces: even if the account holds OTHER numbers, a scalar that does
    not match any of them must not become an ownership claim."""
    world["listing"] = telephony.ProviderNumberList(
        status="success", numbers=(dict(sid="PNother", phone_number="+14160000000",
                                        account_sid=SUB, date_created=None,
                                        status="in-use", origin="twilio"),))
    r = await bf.backfill_tenant(tenant(), dry_run=False)
    assert (r["action"], r["reason"]) == ("skip", "no_provider_match")
    assert world["inserted"] == []
