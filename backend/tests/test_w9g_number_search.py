"""W9G — Irish number DISCOVERY is candidate discovery, and nothing more.

W9C proved two things that shape this:
  * `area_code=1` / `21` / `61` return ZERO results for Ireland -- Twilio's area_code
    filter does not work outside NANP. `in_locality` does.
  * the search result's `locality` is NOT the locality an address must satisfy. A
    number labelled "Dublin" demanded an address in Celbridge/Leixlip/Lucan/Maynooth
    (21615), and the purchase also needs an approved BundleSid (21649).

So nothing here may be described as compliance-validated, and nothing here buys.
"""
import pytest

from services import telephony

SUB = "ACsub00000000000000000000000000001"


class _Row:
    def __init__(self, number, locality=None, region=None,
                 address_requirements="local"):
        self.phone_number = number
        self.locality = locality
        self.region = region
        self.address_requirements = address_requirements
        self.capabilities = {"voice": True, "SMS": False}
        self.beta = False


class FakeLocal:
    def __init__(self, by_locality=None, national=None, error=None):
        self.by_locality = by_locality or {}
        self.national = national if national is not None else [
            _Row("+353909700001", "Portumna", "Connaught")]
        self.error = error
        self.calls = []

    def list(self, limit=None, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        if "area_code" in kw:
            # Mirrors real Irish behaviour: the filter simply does not work.
            return []
        loc = kw.get("in_locality")
        if loc is not None:
            return self.by_locality.get(loc, [])
        return self.national


class FakeClient:
    def __init__(self, local):
        self._local = local
    def available_phone_numbers(self, country):
        self.country = country
        return type("N", (), {"local": self._local})()


@pytest.fixture
def local(monkeypatch):
    fake = FakeLocal(by_locality={
        "Dublin": [_Row("+353191200001", "Dublin", None),
                   _Row("+353191200002", "Dublin", None)],
        "Cork": [_Row("+353216000001", "Cork", "Munster")],
        "Limerick": [],           # W9C measured zero Limerick inventory
    })
    monkeypatch.setattr(telephony, "_sub_client", lambda s, t: FakeClient(fake))
    return fake


# ── in_locality, never area_code ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_ireland_searches_by_locality_and_never_by_area_code(local):
    r = await telephony.search_candidate_numbers(SUB, "tok", iso_country="IE",
                                                locality="Dublin")
    assert r.ok and len(r.candidates) == 2
    assert r.strategy == "in_locality=Dublin"
    assert all("area_code" not in c for c in local.calls), \
        "area_code returns zero results for Ireland"
    assert local.calls == [{"in_locality": "Dublin"}]


@pytest.mark.asyncio
async def test_a_locality_with_no_inventory_falls_back_and_SAYS_SO(local):
    """W9C measured zero Limerick inventory. A caller must be able to tell it is being
    offered an out-of-locality number rather than find out at purchase time."""
    r = await telephony.search_candidate_numbers(SUB, "tok", iso_country="IE",
                                                locality="Limerick")
    assert r.ok
    assert r.strategy == "national_fallback_locality_not_available"
    assert local.calls == [{"in_locality": "Limerick"}, {}]


@pytest.mark.asyncio
async def test_no_locality_means_a_plain_national_search(local):
    r = await telephony.search_candidate_numbers(SUB, "tok", iso_country="IE")
    assert r.strategy == "national"
    assert local.calls == [{}]


@pytest.mark.asyncio
async def test_the_country_is_uppercased(local, monkeypatch):
    captured = {}
    class C(FakeClient):
        def available_phone_numbers(self, country):
            captured["country"] = country
            return super().available_phone_numbers(country)
    monkeypatch.setattr(telephony, "_sub_client", lambda s, t: C(local))
    await telephony.search_candidate_numbers(SUB, "tok", iso_country="ie")
    assert captured["country"] == "IE"


# ── candidate only ─────────────────────────────────────────────────────────

def test_a_result_is_never_compliance_validated():
    """Named so no caller can mistake it. Acceptance is established only by the
    purchase itself, with a real AddressSid and BundleSid."""
    assert telephony.NumberCandidates(status="success").compliance_validated is False


@pytest.mark.asyncio
async def test_the_providers_address_requirement_is_carried_through(local):
    r = await telephony.search_candidate_numbers(SUB, "tok", iso_country="IE",
                                                locality="Cork")
    assert r.candidates[0]["address_requirements"] == "local"


@pytest.mark.asyncio
async def test_the_search_locality_is_reported_as_provider_metadata_only(local):
    r = await telephony.search_candidate_numbers(SUB, "tok", iso_country="IE",
                                                locality="Dublin")
    c = r.candidates[0]
    assert c["locality"] == "Dublin"
    # There is no field claiming the address will be accepted, because the search
    # cannot know that.
    assert not any("valid" in k or "accept" in k for k in c)


# ── error handling, three-state as ever ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_provider_error_is_distinguished_from_no_inventory(local):
    class Boom(Exception):
        status = 500
        code = 20500
    local.error = Boom("down")
    r = await telephony.search_candidate_numbers(SUB, "tok", iso_country="IE",
                                                locality="Dublin")
    assert r.ok is False and r.is_empty is False
    assert "http=500" in r.error_detail and "down" not in r.error_detail


@pytest.mark.asyncio
async def test_an_empty_national_pool_is_authoritatively_empty(local):
    local.national = []
    local.by_locality = {}
    r = await telephony.search_candidate_numbers(SUB, "tok", iso_country="IE")
    assert r.ok is True and r.is_empty is True


@pytest.mark.asyncio
async def test_missing_parameters_are_an_error_not_an_empty_result():
    for kw in ({"subaccount_sid": ""}, {"subaccount_token": ""},
               {"iso_country": ""}):
        args = {"subaccount_sid": SUB, "subaccount_token": "tok", "iso_country": "IE"}
        args.update(kw)
        r = await telephony.search_candidate_numbers(
            args["subaccount_sid"], args["subaccount_token"],
            iso_country=args["iso_country"])
        assert r.ok is False and r.is_empty is False


# ── and absolutely no purchasing ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_searching_never_touches_incoming_phone_numbers(local, monkeypatch):
    touched = []
    class C(FakeClient):
        @property
        def incoming_phone_numbers(self):
            touched.append(True)
            raise AssertionError("W9G MUST NOT PURCHASE")
    monkeypatch.setattr(telephony, "_sub_client", lambda s, t: C(local))
    await telephony.search_candidate_numbers(SUB, "tok", iso_country="IE",
                                             locality="Dublin")
    assert touched == []


def test_the_search_function_source_contains_no_purchase_call():
    import inspect
    src = inspect.getsource(telephony.search_candidate_numbers)
    assert "incoming_phone_numbers" not in src
    assert ".create(" not in src
