"""W9G — the compliance country must be confirmed, never inferred.

`tenants.business_country_code` is the only compliance-country authority because
nothing else on the row qualifies: `tenants.country` is a website scrape and is NULL
for several production tenants, the billing country says who pays, Square's country
describes a payment processor, and a phone prefix describes a number we may be about
to replace.
"""
import pytest

from services import business_country as bc

TENANT = "11111111-1111-1111-1111-111111111111"


class FakeResult:
    def __init__(self, data, count=None): self.data, self.count = data, count


class FakeQB:
    def __init__(self, table, state):
        self.table, self.state, self.filters, self.patch = table, state, {}, None
        self.negated = None
    def select(self, *a, **k): return self
    def update(self, patch): self.patch = patch; return self
    def eq(self, col, val): self.filters[col] = val; return self
    def limit(self, *a, **k): return self
    def is_(self, col, val): self.filters[col] = None if val == "null" else val; return self
    @property
    def not_(self):
        self.negated = True
        return self
    def execute(self):
        if self.patch is not None:
            rows = [r for r in self.state[self.table]
                    if all(str(r.get(c)) == str(v) for c, v in self.filters.items())]
            for r in rows:
                r.update(self.patch)
            self.state["writes"].append((self.table, dict(self.patch)))
            return FakeResult(rows)
        rows = list(self.state.get(self.table, []))
        for c, v in self.filters.items():
            if self.negated:
                rows = [r for r in rows if r.get(c) is not None]
            else:
                rows = [r for r in rows if str(r.get(c)) == str(v)]
        return FakeResult(rows, len(rows))


@pytest.fixture
def world(monkeypatch):
    state = {"tenants": [{"id": TENANT, "business_country_code": None,
                          "country": "US"}],
             "tenant_regulatory_profiles": [], "tenant_regulatory_addresses": [],
             "tenant_phone_numbers": [], "writes": []}

    class FakeClient:
        def table(self, name): return FakeQB(name, state)
    monkeypatch.setattr(bc, "get_client", lambda: FakeClient())
    return state


# ── normalization ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("IE", "IE"), ("ie", "IE"), (" ie ", "IE"), ("Ie", "IE"), ("gb", "GB"),
])
def test_two_letter_codes_are_normalized_to_uppercase(raw, expected):
    assert bc.normalize(raw) == expected


@pytest.mark.parametrize("raw", ["IRL", "I", "", "  ", "IE1", "353", None, "ie-IE"])
def test_anything_that_is_not_a_two_letter_code_is_rejected(raw):
    assert bc.normalize(raw) == ""


# ── confirmation ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_explicit_IE_confirmation_is_accepted(world):
    r = await bc.confirm(TENANT, "IE")
    assert r["status"] == bc.OK
    assert r["business_country_code"] == "IE"
    assert world["tenants"][0]["business_country_code"] == "IE"
    assert world["writes"] == [("tenants", {"business_country_code": "IE"})]


@pytest.mark.asyncio
async def test_lowercase_input_is_normalized_before_the_write(world):
    """The DB CHECK requires uppercase; normalising here is what lets a UI accept
    what a person types without relaxing the column's rule."""
    r = await bc.confirm(TENANT, "ie")
    assert r["business_country_code"] == "IE"
    assert world["writes"][0][1]["business_country_code"] == "IE"


@pytest.mark.asyncio
async def test_an_invalid_code_is_rejected_and_writes_nothing(world):
    for bad in ("IRL", "", "353", "Ireland"):
        r = await bc.confirm(TENANT, bad)
        assert r["status"] == bc.INVALID
    assert world["writes"] == []
    assert world["tenants"][0]["business_country_code"] is None


@pytest.mark.asyncio
async def test_confirming_the_same_country_again_is_idempotent(world):
    world["tenants"][0]["business_country_code"] = "IE"
    r = await bc.confirm(TENANT, "IE")
    assert r["status"] == bc.UNCHANGED
    assert world["writes"] == []


@pytest.mark.asyncio
async def test_the_analyzer_country_is_never_read(world):
    """tenants.country says US. Confirming IE must ignore it entirely, and removing
    the column must change nothing."""
    world["tenants"][0]["country"] = "US"
    r = await bc.confirm(TENANT, "IE")
    assert r["business_country_code"] == "IE"
    world["tenants"][0] = {"id": TENANT, "business_country_code": None}
    world["writes"].clear()
    r2 = await bc.confirm(TENANT, "IE")
    assert r2["status"] == bc.OK and r2["business_country_code"] == "IE"


@pytest.mark.asyncio
async def test_an_unknown_tenant_is_not_found(world):
    r = await bc.confirm("99999999-9999-9999-9999-999999999999", "IE")
    assert r["status"] == bc.NOT_FOUND
    assert world["writes"] == []


# ── the change guard ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_changing_country_is_blocked_once_a_profile_exists(world):
    """The country is baked into a filing with a regulator and into provider
    resources in the tenant's sub-account. Changing the column alone would leave the
    filing describing a different country."""
    world["tenants"][0]["business_country_code"] = "IE"
    world["tenant_regulatory_profiles"].append({"id": "p1", "tenant_id": TENANT})
    r = await bc.confirm(TENANT, "GB")
    assert r["status"] == bc.BLOCKED_REGULATORY
    assert r["business_country_code"] == "IE"
    assert world["tenants"][0]["business_country_code"] == "IE"
    assert world["writes"] == []


@pytest.mark.asyncio
async def test_changing_country_is_blocked_once_an_address_exists(world):
    world["tenants"][0]["business_country_code"] = "IE"
    world["tenant_regulatory_addresses"].append({"id": "a1", "tenant_id": TENANT})
    r = await bc.confirm(TENANT, "GB")
    assert r["status"] == bc.BLOCKED_REGULATORY
    assert world["writes"] == []


@pytest.mark.asyncio
async def test_changing_country_is_blocked_once_a_regulated_number_exists(world):
    world["tenants"][0]["business_country_code"] = "IE"
    world["tenant_phone_numbers"].append({"id": "n1", "tenant_id": TENANT,
                                          "regulatory_profile_id": "p1"})
    r = await bc.confirm(TENANT, "GB")
    assert r["status"] == bc.BLOCKED_REGULATED_NUMBER
    assert world["writes"] == []


@pytest.mark.asyncio
async def test_a_FIRST_confirmation_is_never_blocked(world):
    """The guard is about changing a confirmed country, not about setting one."""
    world["tenant_regulatory_profiles"].append({"id": "p1", "tenant_id": TENANT})
    r = await bc.confirm(TENANT, "IE")
    assert r["status"] == bc.OK


@pytest.mark.asyncio
async def test_the_guard_does_not_cascade_anything(world):
    """No cascading country mutation: the refusal changes nothing at all."""
    world["tenants"][0]["business_country_code"] = "IE"
    world["tenant_regulatory_profiles"].append({"id": "p1", "tenant_id": TENANT,
                                               "iso_country": "IE"})
    await bc.confirm(TENANT, "GB")
    assert world["tenant_regulatory_profiles"][0]["iso_country"] == "IE"
    assert world["writes"] == []


@pytest.mark.asyncio
async def test_get_confirmed_returns_none_rather_than_empty_string(world):
    assert await bc.get_confirmed(TENANT) is None
    world["tenants"][0]["business_country_code"] = "IE"
    assert await bc.get_confirmed(TENANT) == "IE"
