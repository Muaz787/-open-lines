"""W9H-QA.4 — creation ownership for EndUser, SupportingDocument and Bundle.

W9H-QA.3 fixed this for Addresses and W9H.1A found the same shape in three more
places. Twilio deduplicates none of them (measured live), so our claim is the only
thing standing between two concurrent requests and two regulatory identities.
"""
import ast
import inspect
import logging
import uuid

import pytest

from db import regulatory as db_reg
from services import provider_claims as pc
from services import regulatory_engine as engine
from tests.test_w9g_engine import (ADDR_SID, BU_SID, DOC_SID, EU_SID, GOOD_ADDRESS,
                                   authorize, prepared,
                                   GOOD_ATTRS, REQS, SUB, TENANT, FakeTwilio,
                                   ProviderError, tenant, world)  # noqa: F401


def _src(fn):
    """Source without the docstring, so prose cannot satisfy an assertion.

    Dedented, because a test that reads a function the `world` fixture has replaced
    would otherwise see an indented nested def and fail to parse.
    """
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)):
        node.body = node.body[1:]
    return ast.unparse(tree)


def _claims(world, resource=None):
    return [c for c in world["claims"]
            if resource is None or c["resource"] == resource]


async def _address(world):
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert r["ok"], r
    return r["address"]


async def _ready_to_authorize(world, attributes=None):
    """Address + persisted customer answers + a matching authorisation, WITHOUT a
    successful prepare.

    The order matters and is the product's, not a convenience: the authorisation
    fingerprint covers the customer's answers, so there is nothing to authorise
    until they are stored. The first prepare stores them and is refused for want of
    an authorisation; then the customer authorises THOSE facts. Tests that plant
    their own claim rows need exactly this state -- authorised, but with the
    provider work still to do.
    """
    await _address(world)
    first = await engine.prepare_profile(tenant(), attributes=attributes or GOOD_ATTRS)
    assert first["status"] == engine.AUTHORIZATION_NOT_RECORDED, first
    await authorize(world)


# ══════════════════════════════════════════════════════════════════════════
# markers (Stage I)
# ══════════════════════════════════════════════════════════════════════════

def test_every_marker_fits_the_tightest_measured_provider_limit():
    """MARKER_MAX is the tightest measured FriendlyName budget across resources
    (64, the Address list-filter limit). W9H-QA.3 shipped a 65-character marker and
    silently disabled its own reconciliation lookup."""
    for resource in pc.RESOURCE_CODES:
        m = pc.marker(resource, str(uuid.uuid4()))
        assert len(m) <= pc.MARKER_MAX, f"{resource} marker is {len(m)} chars"


def test_a_marker_that_would_overflow_raises_rather_than_truncating():
    """A truncated marker still looks like a marker but matches the wrong thing."""
    with pytest.raises(ValueError):
        pc.marker("bundle", "x" * 200)


def test_each_resource_marker_is_distinguishable():
    claim = str(uuid.uuid4())
    markers = {r: pc.marker(r, claim) for r in pc.RESOURCE_CODES}
    assert len(set(markers.values())) == len(markers), \
        "a lookup for one resource could match another's marker"


def test_markers_carry_no_customer_data():
    m = pc.marker("end_user", "11111111-2222-3333-4444-555555555555")
    for leak in ("DANI", "dani.ie", "Thomas", "Limerick", "V94", "ann@dani.ie",
                 "123456"):
        assert leak.lower() not in m.lower()
    assert m == "ol:eu:11111111-2222-3333-4444-555555555555"


def test_an_unknown_resource_is_refused():
    with pytest.raises(ValueError):
        pc.marker("phone_number", str(uuid.uuid4()))


def test_more_than_one_match_is_returned_not_collapsed():
    """The COUNT is the decision, so matching must not return a first hit."""
    a = type("O", (), {"friendly_name": "ol:eu:x"})()
    b = type("O", (), {"friendly_name": "ol:eu:x"})()
    c = type("O", (), {"friendly_name": "ol:eu:y"})()
    assert len(pc.matching([a, b, c], "ol:eu:x")) == 2


def test_marker_matching_is_exact_not_a_prefix():
    o = type("O", (), {"friendly_name": "ol:eu:abc-extra"})()
    assert pc.matching([o], "ol:eu:abc") == []


def test_the_scopes_are_the_documented_logical_ones():
    assert pc.end_user_scope("IE", "business") == "IE:business"
    assert pc.supporting_document_scope("a1", "business_address") == "a1:business_address"
    assert pc.bundle_scope("p1") == "p1"


# ══════════════════════════════════════════════════════════════════════════
# EndUser (Stage E) — tests 1-7
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_enduser_claim_exists_before_the_provider_is_called(world):
    seen = {}

    def at_create(**kw):
        seen["claims"] = [dict(c) for c in _claims(world, "end_user")]
        seen["friendly_name"] = kw.get("friendly_name")

    world["twilio"].opts["on_end_user_create"] = at_create
    r = await prepared(world)
    assert r["ok"], r
    assert len(seen["claims"]) == 1, "the claim must exist when the provider is called"
    assert seen["claims"][0]["provider_sid"] is None
    assert seen["friendly_name"] == pc.marker("end_user", seen["claims"][0]["id"])


def test_the_enduser_source_claims_before_it_creates():
    body = _src(engine.resolve_end_user)
    assert "_ensure_provider_resource" in body
    assert "end_users.create" not in body, \
        "the create must go through the claim-guarded helper"


@pytest.mark.asyncio
async def test_sibling_locations_share_one_enduser(world):
    """The scope is (country, end-user type) -- NOT the profile or the address --
    because an EndUser is one business identity shared across a tenant's filings."""
    world["locations"].append({"id": "loc-2", "tenant_id": TENANT})
    first = await prepared(world)
    assert first["ok"], first
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS,
                                tenant_location_id="loc-2")
    # a second premises is a separate authorisation scope by design (W9H.1A)
    await authorize(world, tenant_location_id="loc-2")
    second = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS,
                                          tenant_location_id="loc-2")
    assert second["ok"], second
    assert world["twilio"].created["end_user"] == 1, \
        "a second location must not create a second regulatory identity"
    assert first["end_user_sid"] == second["end_user_sid"]
    assert len(_claims(world, "end_user")) == 1


@pytest.mark.asyncio
async def test_a_request_that_loses_the_enduser_claim_never_creates(world):
    await _ready_to_authorize(world)
    addr = world["addresses"][0]
    await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="end_user",
        scope_key=pc.end_user_scope("IE", "business"), provider_account_sid=SUB)
    world["twilio"].created["end_user"] = 0
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.PROVIDER_CREATE_IN_PROGRESS
    assert world["twilio"].created["end_user"] == 0
    assert len(_claims(world, "end_user")) == 1


@pytest.mark.asyncio
async def test_an_enduser_created_by_a_dead_worker_is_adopted(world):
    """CASE 3: the worker created it, then died before attaching."""
    await _ready_to_authorize(world)
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="end_user",
        scope_key=pc.end_user_scope("IE", "business"), provider_account_sid=SUB)
    marker = pc.marker("end_user", claim["id"])
    world["twilio"].end_user_store["ITorphan"] = type(
        "O", (), {"sid": "ITorphan", "friendly_name": marker, "attributes": {}})()
    world["clock"]["t"] += db_reg.CLAIM_STALE_SECONDS + 1

    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["ok"], r
    assert r["end_user_sid"] == "ITorphan", "the existing EndUser must be adopted"
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_an_unknown_enduser_outcome_is_reconciled_not_recreated(world):
    """CASE 4: Twilio created it; the transport died before we heard."""
    await _ready_to_authorize(world)
    orig = FakeTwilio.end_users.fget

    def patched(self):
        res = orig(self)

        def timing_out(**kw):
            sid = "ITghost"
            self.end_user_store[sid] = type(
                "O", (), {"sid": sid, "friendly_name": kw.get("friendly_name"),
                          "attributes": {}})()
            raise ProviderError(code=None, status=None, detail="connection reset")
        res._create = timing_out
        return res

    FakeTwilio.end_users = property(patched)
    try:
        r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    finally:
        FakeTwilio.end_users = property(orig)
    assert r["ok"], r
    assert r["end_user_sid"] == "ITghost"
    assert len(world["twilio"].end_user_store) == 1, "no blind duplicate create"


@pytest.mark.asyncio
async def test_a_stale_enduser_worker_cannot_overwrite_the_new_owner(world):
    """CASE 5: it lost the claim and then woke up holding its own EndUser."""
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="end_user",
        scope_key=pc.end_user_scope("IE", "business"), provider_account_sid=SUB)
    await db_reg.attach_provider_sid(claim["id"], "ITwinner", SUB)
    stale = type("O", (), {"sid": "ITstale", "friendly_name": "x", "attributes": {}})()
    world["twilio"].end_user_store["ITstale"] = stale
    eu = world["twilio"].numbers.v2.regulatory_compliance.end_users

    out = await engine._adopt_provider_resource(
        claim, [stale], SUB, "end_user", lambda sid: eu(sid).delete())

    assert claim["provider_sid"] == "ITwinner", "the stale worker overwrote the owner"
    assert out["ok"] and out["provider_sid"] == "ITwinner"
    assert "ITstale" in world["twilio"].deleted_end_users, \
        "the stale worker must withdraw its own EndUser"


@pytest.mark.asyncio
async def test_two_endusers_for_one_claim_FAIL_CLOSED(world):
    """CASE 6. An EndUser is a regulatory IDENTITY -- unlike a duplicate Address,
    picking one arbitrarily would file an identity nobody chose."""
    await _ready_to_authorize(world)
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="end_user",
        scope_key=pc.end_user_scope("IE", "business"), provider_account_sid=SUB)
    marker = pc.marker("end_user", claim["id"])
    for sid in ("ITone", "ITtwo"):
        world["twilio"].end_user_store[sid] = type(
            "O", (), {"sid": sid, "friendly_name": marker, "attributes": {}})()
    world["clock"]["t"] += db_reg.CLAIM_STALE_SECONDS + 1

    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.PROVIDER_IDENTITY_CONFLICT
    assert r["count"] == 2
    assert claim["provider_sid"] is None, "nothing may be attached on a conflict"
    assert world["twilio"].deleted_end_users == [], \
        "a conflict must not delete either candidate"


def test_an_enduser_claim_race_never_raises_a_uniqueness_error():
    """Deliberately takes no `world`: it must read the REAL data layer, not the
    fixture's fake, or a mutation in db/regulatory.py would go unnoticed."""
    class Unique(Exception):
        code = "23505"
    assert db_reg._is_unique_violation(Unique("dupe")) is True
    assert db_reg._is_unique_violation(ValueError("other")) is False
    body = _src(db_reg.claim_provider_resource)
    assert "_is_unique_violation" in body and "return None" in body


# ══════════════════════════════════════════════════════════════════════════
# SupportingDocument (Stage F) — tests 8-13
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_document_claim_exists_before_the_provider_is_called(world):
    seen = {}

    def at_create(**kw):
        seen["claims"] = [dict(c) for c in _claims(world, "supporting_document")]
        seen["friendly_name"] = kw.get("friendly_name")

    world["twilio"].opts["on_document_create"] = at_create
    r = await prepared(world)
    assert r["ok"], r
    assert len(seen["claims"]) == 1
    assert seen["claims"][0]["provider_sid"] is None
    assert seen["friendly_name"] == pc.marker("supporting_document",
                                              seen["claims"][0]["id"])


def test_the_document_source_claims_before_it_creates():
    body = _src(engine.ensure_supporting_document)
    assert "_ensure_provider_resource" in body
    assert "supporting_documents.create" not in body


@pytest.mark.asyncio
async def test_exactly_one_document_per_logical_address(world):
    assert (await prepared(world))["ok"]
    for _ in range(3):
        r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
        assert r["ok"], r
    assert world["twilio"].created["document"] == 1
    assert len(_claims(world, "supporting_document")) == 1


@pytest.mark.asyncio
async def test_a_request_that_loses_the_document_claim_never_creates(world):
    await _ready_to_authorize(world)
    addr = world["addresses"][0]
    await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="supporting_document",
        scope_key=pc.supporting_document_scope(addr["id"], "business_address"),
        provider_account_sid=SUB)
    world["twilio"].created["document"] = 0
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.PROVIDER_CREATE_IN_PROGRESS
    assert world["twilio"].created["document"] == 0


@pytest.mark.asyncio
async def test_the_document_attachment_is_fenced(world):
    addr = await _address(world)
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="supporting_document",
        scope_key=pc.supporting_document_scope(addr["id"], "business_address"),
        provider_account_sid=SUB)
    assert await db_reg.attach_provider_sid(claim["id"], "RDfirst", SUB) is not None
    assert await db_reg.attach_provider_sid(claim["id"], "RDsecond", SUB) is None, \
        "the fence let a second SID overwrite the first"
    assert claim["provider_sid"] == "RDfirst"


@pytest.mark.asyncio
async def test_an_unknown_document_outcome_is_reconciled(world):
    await _ready_to_authorize(world)
    orig = FakeTwilio.supporting_documents.fget

    def patched(self):
        res = orig(self)

        def timing_out(**kw):
            self.document_store["RDghost"] = type(
                "O", (), {"sid": "RDghost", "status": "draft",
                          "friendly_name": kw.get("friendly_name")})()
            raise ProviderError(code=None, status=None, detail="reset")
        res._create = timing_out
        return res

    FakeTwilio.supporting_documents = property(patched)
    try:
        r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    finally:
        FakeTwilio.supporting_documents = property(orig)
    assert r["ok"], r
    assert r["supporting_document_sid"] == "RDghost"
    assert len(world["twilio"].document_store) == 1


@pytest.mark.asyncio
async def test_a_stale_document_worker_withdraws_its_own_document(world):
    addr = await _address(world)
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="supporting_document",
        scope_key=pc.supporting_document_scope(addr["id"], "business_address"),
        provider_account_sid=SUB)
    await db_reg.attach_provider_sid(claim["id"], "RDwinner", SUB)
    stale = type("O", (), {"sid": "RDstale", "status": "draft",
                           "friendly_name": "x"})()
    world["twilio"].document_store["RDstale"] = stale
    sd = world["twilio"].numbers.v2.regulatory_compliance.supporting_documents

    out = await engine._adopt_provider_resource(
        claim, [stale], SUB, "supporting_document", lambda sid: sd(sid).delete())
    assert out["ok"] and out["provider_sid"] == "RDwinner"
    assert "RDstale" in world["twilio"].deleted_documents


@pytest.mark.asyncio
async def test_a_failed_document_cleanup_leaves_an_observable_orphan(world, caplog):
    """CASE 7. The claim is already correct, so this must not fail the request --
    but the leak has to stay findable, with no customer content in the line."""
    sd = world["twilio"].numbers.v2.regulatory_compliance.supporting_documents
    world["twilio"].opts["document_delete_error"] = ProviderError(
        code=20500, status=500, detail="nope")
    with caplog.at_level(logging.DEBUG):
        engine._withdraw_provider_resource(lambda sid: sd(sid).delete(),
                                           "RDleak", "claim-9",
                                           "supporting_document")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "claim-9" in text
    for leak in (GOOD_ADDRESS["street"], GOOD_ADDRESS["postal_code"],
                 GOOD_ADDRESS["customer_name"]):
        assert leak not in text


# ══════════════════════════════════════════════════════════════════════════
# Bundle (Stage G) — tests 14-20
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_profile_exists_before_the_bundle_is_created(world):
    seen = {}

    def at_create(**kw):
        seen["profiles"] = [dict(p) for p in world["profiles"]]
        seen["claims"] = [dict(c) for c in _claims(world, "bundle")]
        seen["friendly_name"] = kw.get("friendly_name")

    world["twilio"].opts["on_bundle_create"] = at_create
    r = await prepared(world)
    assert r["ok"], r
    assert len(seen["profiles"]) == 1, "the profile must exist first"
    assert len(seen["claims"]) == 1
    assert seen["claims"][0]["scope_key"] == pc.bundle_scope(seen["profiles"][0]["id"])
    assert seen["friendly_name"] == pc.marker("bundle", seen["claims"][0]["id"])


def test_the_bundle_source_claims_before_it_creates():
    body = _src(engine.ensure_bundle)
    assert "_ensure_provider_resource" in body
    assert "bundles.create" not in body


@pytest.mark.asyncio
async def test_a_concurrent_profile_insert_reuses_instead_of_raising(world):
    """Stage H. The loser re-reads the canonical profile; both proceed on one row."""
    await _ready_to_authorize(world)
    # The authorisation gate refuses the FIRST prepare, and that refusal path
    # creates a draft profile -- so without clearing it the insert below is never
    # reached and this test would silently stop exercising the loser path.
    world["profiles"].clear()
    calls = {"n": 0}
    real_insert = engine.db_reg.insert_profile

    async def losing_insert(row):
        calls["n"] += 1
        if calls["n"] == 1:
            # Another request won: model migration 027's partial unique index.
            await real_insert(row)
            return None
        return await real_insert(row)

    engine.db_reg.insert_profile = losing_insert
    try:
        r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    finally:
        engine.db_reg.insert_profile = real_insert

    assert r["ok"], r
    assert len(world["profiles"]) == 1, "both requests must share one profile"
    assert world["twilio"].created["bundle"] == 1


def test_the_profile_insert_catches_the_uniqueness_violation_itself():
    body = _src(db_reg.insert_profile)
    assert "_is_unique_violation" in body and "return None" in body, \
        "a raw 23505 must never reach the API"


@pytest.mark.asyncio
async def test_exactly_one_bundle_is_created_across_repeated_attempts(world):
    assert (await prepared(world))["ok"]
    for _ in range(3):
        r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
        assert r["ok"], r
    assert world["twilio"].created["bundle"] == 1
    assert len(_claims(world, "bundle")) == 1


@pytest.mark.asyncio
async def test_the_bundle_attachment_is_fenced(world):
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="bundle", scope_key="prof-1",
        provider_account_sid=SUB)
    assert await db_reg.attach_provider_sid(claim["id"], "BUfirst", SUB) is not None
    assert await db_reg.attach_provider_sid(claim["id"], "BUsecond", SUB) is None
    assert claim["provider_sid"] == "BUfirst"


@pytest.mark.asyncio
async def test_an_unknown_bundle_outcome_is_reconciled(world):
    await _ready_to_authorize(world)
    orig = FakeTwilio.bundles.fget

    def patched(self):
        res = orig(self)

        def timing_out(**kw):
            self.bundle_store["BUghost"] = type(
                "O", (), {"sid": "BUghost", "status": "draft",
                          "friendly_name": kw.get("friendly_name")})()
            raise ProviderError(code=None, status=None, detail="reset")
        res._create = timing_out
        return res

    FakeTwilio.bundles = property(patched)
    try:
        r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    finally:
        FakeTwilio.bundles = property(orig)
    assert r["ok"], r
    assert r["bundle_sid"] == "BUghost"
    assert len(world["twilio"].bundle_store) == 1


@pytest.mark.asyncio
async def test_two_bundles_for_one_claim_FAIL_CLOSED(world):
    await _ready_to_authorize(world)
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="bundle", scope_key="prof-1",
        provider_account_sid=SUB)
    marker = pc.marker("bundle", claim["id"])
    mk = lambda sid: type("O", (), {"sid": sid, "status": "draft",
                                    "friendly_name": marker})()
    out = await engine._adopt_provider_resource(
        claim, [mk("BUone"), mk("BUtwo")], SUB, "bundle", None)
    assert out["status"] == engine.PROVIDER_IDENTITY_CONFLICT
    assert claim["provider_sid"] is None


@pytest.mark.asyncio
async def test_a_stale_bundle_worker_cannot_overwrite_the_winner(world):
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="bundle", scope_key="prof-1",
        provider_account_sid=SUB)
    await db_reg.attach_provider_sid(claim["id"], "BUwinner", SUB)
    stale = type("O", (), {"sid": "BUstale", "status": "draft",
                           "friendly_name": "x"})()
    world["twilio"].bundle_store["BUstale"] = stale
    bu = world["twilio"].numbers.v2.regulatory_compliance.bundles
    out = await engine._adopt_provider_resource(
        claim, [stale], SUB, "bundle", lambda sid: bu(sid).delete())
    assert out["ok"] and out["provider_sid"] == "BUwinner"
    assert "BUstale" in world["twilio"].deleted_bundles


# ══════════════════════════════════════════════════════════════════════════
# lease behaviour
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_fresh_claim_is_never_stolen(world):
    await _ready_to_authorize(world)
    await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="end_user",
        scope_key=pc.end_user_scope("IE", "business"), provider_account_sid=SUB)
    world["clock"]["t"] += db_reg.CLAIM_STALE_SECONDS - 5
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.PROVIDER_CREATE_IN_PROGRESS
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_an_outage_releases_the_lease_so_a_retry_is_not_blocked(world):
    """My own first design held the lease after an outage, so a two-second blip
    cost the customer the whole stale window."""
    await _ready_to_authorize(world)
    world["twilio"].opts["end_user_error"] = ProviderError(code=20500, status=500)
    first = await engine.prepare_profile(tenant(), attributes={})
    assert first["status"] == engine.PROVIDER_UNAVAILABLE, first

    world["twilio"].opts.pop("end_user_error")
    second = await engine.prepare_profile(tenant(), attributes={})
    assert second["ok"], second           # no waiting out the stale window
    assert world["twilio"].created["end_user"] == 1


def test_the_release_is_fenced_on_the_sid_being_null():
    for fn in (db_reg.release_provider_claim, db_reg.release_address_claim):
        body = _src(fn).replace('"', "'")
        assert "'provider_sid', 'null'" in body or "'address_sid', 'null'" in body, \
            f"{fn.__name__} must not release a claim that already succeeded"


# ══════════════════════════════════════════════════════════════════════════
# global (Stage P 21-28)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["ok", "eu_outage", "doc_outage", "bundle_outage",
                                      "lost_eu_claim"])
async def test_no_number_is_ever_purchased_and_nothing_is_submitted(world, scenario):
    await _address(world)
    tw = world["twilio"]
    if scenario == "eu_outage":
        tw.opts["end_user_error"] = ProviderError(code=20500, status=500)
    elif scenario == "doc_outage":
        tw.opts["document_error"] = ProviderError(code=20500, status=500)
    elif scenario == "bundle_outage":
        tw.opts["bundle_error"] = ProviderError(code=20500, status=500)
    elif scenario == "lost_eu_claim":
        await db_reg.claim_provider_resource(
            tenant_id=TENANT, resource="end_user",
            scope_key=pc.end_user_scope("IE", "business"), provider_account_sid=SUB)

    await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert tw.purchases == 0
    assert tw.bundle_status in ("draft", "twilio-approved"), \
        "nothing may be submitted for review by preparation"


@pytest.mark.asyncio
@pytest.mark.parametrize("err", ["end_user_error", "document_error", "bundle_error"])
async def test_no_customer_content_is_logged_on_any_provider_failure(world, caplog, err):
    await _address(world)
    world["twilio"].opts[err] = ProviderError(code=20500, status=500,
                                              detail="internal error")
    with caplog.at_level(logging.DEBUG):
        await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    text = "\n".join(r.getMessage() for r in caplog.records)
    for leak in (GOOD_ATTRS["business_name"], GOOD_ATTRS["email"],
                 GOOD_ATTRS["business_registration_number"],
                 GOOD_ATTRS["first_name"], GOOD_ATTRS["last_name"],
                 GOOD_ADDRESS["street"], GOOD_ADDRESS["postal_code"]):
        assert leak not in text, f"{leak!r} leaked into the log"


def test_no_provider_call_happens_at_import_time():
    import pathlib
    src = pathlib.Path(pc.__file__).read_text()
    for node in ast.parse(src).body:
        assert isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef, ast.Assign,
                                 ast.AnnAssign, ast.Expr)), \
            f"module-level side effect: {type(node).__name__}"


def test_the_claim_scope_key_never_carries_customer_data():
    """scope_key is stored, so it must hold ids and enums only."""
    keys = [pc.end_user_scope("IE", "business"),
            pc.supporting_document_scope("addr-1", "business_address"),
            pc.bundle_scope("prof-1")]
    for k in keys:
        for leak in ("DANI", "dani.ie", "Thomas", "Limerick", "V94", "ann@"):
            assert leak.lower() not in k.lower()


# ══════════════════════════════════════════════════════════════════════════
# Stage O — ItemAssignment stays as it is
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_item_assignment_pre_reads_and_treats_22214_as_already_assigned(world):
    """Reconfirming the W9H.1A verdict rather than refactoring for consistency:
    Twilio itself rejects a duplicate assignment, and no application identity is
    lost, so this path needs no claim."""
    tw = world["twilio"]
    tw.assignments = ["ITexisting"]
    r = await engine.ensure_item_assignments(
        bundle_sid=BU_SID, object_sids=["ITexisting", "RDnew"], client=tw)
    assert r["ok"]
    assert "ITexisting" in r["already_assigned"], "it must pre-read, not re-create"
    assert r["assigned"] == ["RDnew"]
    assert tw.created["assignment"] == 1


@pytest.mark.asyncio
async def test_a_duplicate_assignment_error_is_not_a_failure(world):
    tw = world["twilio"]
    tw.opts["assignment_error"] = ProviderError(code=22214, status=400,
                                                detail="already exists on bundle")
    r = await engine.ensure_item_assignments(bundle_sid=BU_SID,
                                            object_sids=["ITx"], client=tw)
    assert r["ok"] and r["already_assigned"] == ["ITx"]


def test_item_assignment_was_deliberately_left_alone():
    body = _src(engine.ensure_item_assignments)
    assert "_ensure_provider_resource" not in body, \
        "ItemAssignment was assessed SAFE; it must not have been refactored"
    assert "22214" in body


# ══════════════════════════════════════════════════════════════════════════
# the REAL data layer
# ══════════════════════════════════════════════════════════════════════════
# The fence tests above run against the `world` fixture's fake, which has a fence
# of its own -- so removing the real one went unnoticed by the whole suite until
# mutation testing said so. These bind the real predicates. None of them takes
# `world`, deliberately.

def test_the_real_attach_is_fenced_on_provider_sid_being_null():
    body = _src(db_reg.attach_provider_sid).replace('"', "'")
    assert "'provider_sid', 'null'" in body, \
        "a taken-over worker could overwrite the new owner's provider SID"
    assert "len(res.data or []) == 1" in body, \
        "exactly one updated row is what proves we won"


def test_the_real_takeover_is_guarded_on_provider_sid_being_null():
    body = _src(db_reg.take_over_provider_claim).replace('"', "'")
    assert "'provider_sid', 'null'" in body, \
        "a claim that already reached the provider must never be up for grabs"
    assert "claimed_at" in body, "winning must renew the lease in the same statement"
    assert "CLAIM_STALE_SECONDS" in body


def test_the_real_failure_record_is_fenced():
    body = _src(db_reg.record_provider_claim_failure).replace('"', "'")
    assert "'provider_sid', 'null'" in body, \
        "a stale worker's failure must not overwrite a live owner's state"


def test_the_real_claim_insert_writes_the_scope_and_the_lease():
    body = _src(db_reg.claim_provider_resource)
    for field in ("tenant_id", "resource", "scope_key", "claimed_at",
                  "provider_account_sid"):
        assert field in body, f"the claim must record {field}"
