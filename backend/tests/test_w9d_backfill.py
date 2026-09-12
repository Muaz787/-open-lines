"""W9D — the phone-number backfill: what it proposes, and what it refuses to invent.

The backfill's job is small and its failure mode is large: a wrong row here becomes
the canonical record of a live phone number. So these tests are mostly about the
refusals — every value it cannot establish from the provider must produce a skip
with a reason, never a plausible guess.
"""
from datetime import datetime, timezone

import pytest

from services import phone_backfill as bf
from services import phone_lifecycle as lifecycle

TENANT = "11111111-1111-1111-1111-111111111111"
NUMBER = "+14374769911"
SUB = "ACsubaccount0000000000000000000001"
PN = "PNnumber000000000000000000000001"
CREATED = datetime(2026, 6, 26, 0, 18, 55, tzinfo=timezone.utc)


def tenant(**over):
    base = {"id": TENANT, "business_name": "SmileCare",
            "twilio_phone_number": NUMBER, "twilio_subaccount_sid": SUB,
            "twilio_auth_token": "tok", "vapi_phone_number_id": "vapi-1",
            # Present on purpose: the analyzer's guess must never be used.
            "country": "US"}
    base.update(over)
    return base


def provider_number(**over):
    base = {"sid": PN, "phone_number": NUMBER, "account_sid": SUB,
            "date_created": CREATED, "status": "in-use", "origin": "twilio"}
    base.update(over)
    return base


@pytest.fixture
def world(monkeypatch):
    state = {"provider": [provider_number()], "country": "CA",
             "existing": [], "inserted": [], "lookups": []}

    async def fake_list(sub_sid, sub_token):
        state["lookups"].append(("list", sub_sid))
        if state.get("provider_error"):
            return bf.telephony.ProviderNumberList(status="error",
                                                   error_detail=state["provider_error"])
        return bf.telephony.ProviderNumberList(status="success",
                                              numbers=tuple(state["provider"]))

    async def fake_country(number):
        state["lookups"].append(("lookup", number))
        return state["country"]

    async def fake_existing(tenant_id, purpose="", statuses=()):
        rows = state["existing"]
        if purpose:
            rows = [r for r in rows if r.get("purpose") == purpose]
        if statuses:
            rows = [r for r in rows if r.get("status") in statuses]
        return rows

    async def fake_insert(row):
        state["inserted"].append(row)
        return {**row, "id": "new-row-id"}

    monkeypatch.setattr(bf.telephony, "fetch_subaccount_numbers", fake_list)
    monkeypatch.setattr(bf.telephony, "lookup_iso_country", fake_country)
    monkeypatch.setattr(bf.db_phone, "list_for_tenant", fake_existing)
    monkeypatch.setattr(bf.db_phone, "insert_number", fake_insert)
    return state


# ── the happy path proposes an exact row ───────────────────────────────────

@pytest.mark.asyncio
async def test_a_clean_tenant_gets_a_complete_proposal(world):
    r = await bf.plan_tenant(tenant())
    assert r["action"] == "propose" and r["reason"] == ""
    row = r["row"]
    assert row["e164"] == NUMBER
    assert row["purpose"] == lifecycle.PURPOSE_PERMANENT
    assert row["status"] == lifecycle.STATUS_ACTIVE
    assert row["provider_sid"] == PN
    assert row["provider_account_sid"] == SUB
    assert row["iso_country"] == "CA"
    assert row["vapi_phone_number_id"] == "vapi-1"
    assert row["tenant_location_id"] is None
    assert row["regulatory_profile_id"] is None


@pytest.mark.asyncio
async def test_activation_comes_from_the_provider_and_says_so(world):
    row = (await bf.plan_tenant(tenant()))["row"]
    assert row["activated_at"] == CREATED.isoformat()
    assert row["activated_at_source"] == "provider_date_created"


@pytest.mark.asyncio
async def test_activation_is_NULL_rather_than_the_tenant_creation_date(world):
    """Signing up is not activating a phone line. With no provider date, the row
    carries no activation date at all -- and no source, so nothing can later be
    mistaken for an observation."""
    world["provider"] = [provider_number(date_created=None)]
    row = (await bf.plan_tenant(tenant(created_at="2026-01-01T00:00:00Z")))["row"]
    assert row["activated_at"] is None
    assert row["activated_at_source"] is None


@pytest.mark.asyncio
async def test_country_comes_from_lookup_and_never_from_the_analyzer(world):
    """The tenant row says US; Lookup says CA. CA must win, because
    tenants.country is a website scrape and +1 is Canada and the US both."""
    world["country"] = "CA"
    row = (await bf.plan_tenant(tenant(country="US")))["row"]
    assert row["iso_country"] == "CA"
    assert ("lookup", NUMBER) in world["lookups"]


@pytest.mark.asyncio
async def test_the_analyzer_country_is_not_read_at_all(world):
    """Removing tenants.country entirely must change nothing."""
    t = tenant()
    t.pop("country")
    row = (await bf.plan_tenant(t))["row"]
    assert row["iso_country"] == "CA"


# ── every refusal ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_tenant_with_no_number_is_skipped(world):
    r = await bf.plan_tenant(tenant(twilio_phone_number=None))
    assert (r["action"], r["reason"]) == ("skip", "no_number")


@pytest.mark.asyncio
async def test_a_tenant_with_no_subaccount_credentials_is_skipped(world):
    r = await bf.plan_tenant(tenant(twilio_subaccount_sid=""))
    assert (r["action"], r["reason"]) == ("skip", "missing_twilio_credentials")
    r = await bf.plan_tenant(tenant(twilio_auth_token=""))
    assert (r["action"], r["reason"]) == ("skip", "missing_twilio_credentials")


@pytest.mark.asyncio
async def test_an_unreachable_provider_is_unknown_not_empty(world):
    """A failed query means 'could not establish', NOT 'owns nothing'. A live number
    must never be written off because a list call failed. W9F gave this its own
    reason string, distinct from an authoritatively empty account."""
    world["provider_error"] = "TwilioRestException http=500"
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("skip", "provider_numbers_unavailable")


@pytest.mark.asyncio
async def test_an_authoritatively_empty_account_has_its_own_reason(world):
    world["provider"] = []
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("skip", "provider_account_empty")


@pytest.mark.asyncio
async def test_a_number_the_provider_does_not_hold_is_skipped(world):
    world["provider"] = [provider_number(phone_number="+14370000000")]
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("skip", "no_provider_match")


@pytest.mark.asyncio
async def test_matching_is_exact_not_a_prefix(world):
    world["provider"] = [provider_number(phone_number=NUMBER + "0")]
    r = await bf.plan_tenant(tenant())
    assert r["reason"] == "no_provider_match"


@pytest.mark.asyncio
async def test_two_provider_rows_for_one_number_fail_closed(world):
    world["provider"] = [provider_number(sid="PNa"), provider_number(sid="PNb")]
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("skip", "ambiguous_provider_match")
    assert r["matched"] == 2


@pytest.mark.asyncio
async def test_a_number_owned_by_a_different_account_is_skipped(world):
    """The number exists, but not where we believe it does. Writing our belief
    would make the ownership invariant a lie."""
    world["provider"] = [provider_number(account_sid="ACsomeoneelse000000000000000000001")]
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("skip", "account_mismatch")


@pytest.mark.asyncio
async def test_a_missing_provider_sid_is_skipped(world):
    world["provider"] = [provider_number(sid="")]
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("skip", "provider_sid_missing")


@pytest.mark.asyncio
async def test_an_unresolved_country_is_skipped_not_guessed(world):
    world["country"] = ""
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("skip", "country_unresolved")


@pytest.mark.asyncio
async def test_an_already_backfilled_tenant_is_left_alone(world):
    world["existing"] = [{"id": "x", "purpose": lifecycle.PURPOSE_PERMANENT,
                          "status": lifecycle.STATUS_ACTIVE, "e164": NUMBER}]
    r = await bf.plan_tenant(tenant())
    assert (r["action"], r["reason"]) == ("exists", "already_backfilled")
    assert world["lookups"] == [], "an existing row must short-circuit before any provider call"


@pytest.mark.asyncio
async def test_a_uniqueness_clash_is_reported_not_raised(world):
    """A retiring permanent plus this proposal is fine; another tenant-level clash
    must surface as a reason rather than a 23505 mid-run."""
    world["existing"] = [{"id": "other", "purpose": lifecycle.PURPOSE_TEMPORARY,
                          "status": lifecycle.STATUS_ACTIVE, "e164": NUMBER}]
    r = await bf.plan_tenant(tenant())
    assert r["action"] == "skip"
    assert r["reason"] == "uniqueness_conflict:tpn_owned_e164_key"


# ── dry run writes nothing ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_is_the_default_and_writes_nothing(world):
    r = await bf.backfill_tenant(tenant())
    assert r["dry_run"] is True
    assert r["action"] == "propose"
    assert world["inserted"] == []


@pytest.mark.asyncio
async def test_live_mode_requires_an_explicit_flag_and_then_inserts(world):
    r = await bf.backfill_tenant(tenant(), dry_run=False)
    assert r["action"] == "inserted"
    assert r["inserted_id"] == "new-row-id"
    assert len(world["inserted"]) == 1
    assert world["inserted"][0]["provider_sid"] == PN


@pytest.mark.asyncio
async def test_a_skip_never_inserts_even_in_live_mode(world):
    world["country"] = ""
    r = await bf.backfill_tenant(tenant(), dry_run=False)
    assert r["action"] == "skip"
    assert world["inserted"] == []


# ── the whole-fleet summary ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_backfill_all_summarises_and_writes_nothing_in_dry_run(world, monkeypatch):
    """Mirrors the production census: numbered tenants propose, tenants holding a
    sub-account and no number skip."""
    fleet = [tenant(),
             tenant(id="22222222-2222-2222-2222-222222222222",
                    twilio_phone_number=None),
             tenant(id="33333333-3333-3333-3333-333333333333",
                    twilio_phone_number=None)]

    async def fake_tenants():
        return fleet
    monkeypatch.setattr(bf, "list_tenants_for_backfill", fake_tenants)

    summary = await bf.backfill_all()
    assert summary["dry_run"] is True
    assert summary["tenants"] == 3
    assert summary["counts"] == {"propose": 1, "skip": 2}
    assert summary["skip_reasons"] == {"no_number": 2}
    assert world["inserted"] == []


@pytest.mark.asyncio
async def test_the_report_masks_phone_numbers(world):
    r = await bf.plan_tenant(tenant())
    assert r["number"] != NUMBER
    assert "…" in r["number"]
    assert r["number"].startswith(NUMBER[:5])


# ═══════════════════════════════════════════════════════════════════════════
# The provider boundary the backfill depends on. Both helpers must report
# failure rather than raise, because a backfill that crashes on one tenant's
# unreachable sub-account is worse than one that reports and skips.
# ═══════════════════════════════════════════════════════════════════════════
from unittest.mock import patch                                  # noqa: E402

from services import telephony                                   # noqa: E402


class _Numbers:
    def __init__(self, rows):
        self._rows = rows

    def list(self, limit=None):
        return self._rows


class _SubClient:
    def __init__(self, rows):
        self.incoming_phone_numbers = _Numbers(rows)


class _Row:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.mark.asyncio
async def test_fetch_subaccount_numbers_returns_the_fields_the_backfill_needs():
    row = _Row(sid=PN, phone_number=NUMBER, account_sid=SUB, date_created=CREATED,
               status="in-use", origin="twilio")
    with patch("services.telephony._sub_client", return_value=_SubClient([row])):
        out = await telephony.fetch_subaccount_numbers(SUB, "tok")
    assert out.ok and not out.is_empty
    assert out.numbers == ({"sid": PN, "phone_number": NUMBER, "account_sid": SUB,
                            "date_created": CREATED, "status": "in-use",
                            "origin": "twilio"},)


class _Lookups:
    def __init__(self, result):
        self._result = result
        self.v2 = self

    def phone_numbers(self, number):
        self._number = number
        return self

    def fetch(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _MasterClient:
    def __init__(self, result):
        self.lookups = _Lookups(result)


@pytest.mark.asyncio
async def test_lookup_iso_country_returns_the_provider_answer_uppercased():
    with patch("services.telephony._master_client",
               return_value=_MasterClient(_Row(valid=True, country_code="ca"))):
        assert await telephony.lookup_iso_country(NUMBER) == "CA"


@pytest.mark.asyncio
async def test_lookup_iso_country_distinguishes_ca_from_us_on_the_same_prefix():
    """The whole reason Lookup is used rather than a prefix rule."""
    for answer, expected in (("CA", "CA"), ("US", "US")):
        with patch("services.telephony._master_client",
                   return_value=_MasterClient(_Row(valid=True, country_code=answer))):
            assert await telephony.lookup_iso_country("+14160000000") == expected


@pytest.mark.asyncio
async def test_lookup_iso_country_returns_blank_on_an_invalid_number():
    with patch("services.telephony._master_client",
               return_value=_MasterClient(_Row(valid=False, country_code="CA"))):
        assert await telephony.lookup_iso_country(NUMBER) == ""


@pytest.mark.asyncio
async def test_lookup_iso_country_never_raises():
    with patch("services.telephony._master_client",
               return_value=_MasterClient(RuntimeError("lookup 500"))):
        assert await telephony.lookup_iso_country(NUMBER) == ""
    assert await telephony.lookup_iso_country("") == ""
