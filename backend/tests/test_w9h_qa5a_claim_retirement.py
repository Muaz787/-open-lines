"""W9H-QA.5A — verifying an attached claim, and retiring one the provider lost.

W9H-QA.5 blocked the release of migration 030 over this: an attached claim was
treated as permanently authoritative, `provider_sid` could never be cleared, and a
resource deleted at Twilio -- which our own QA cleanup does routinely -- poisoned
its logical scope forever and silently contradicted recover_end_user.

The rule these tests hold is narrow on purpose: a stored SID may be cleared ONLY
when the provider authoritatively says the resource is gone.
"""
import ast
import inspect
import logging
import textwrap

import pytest

from db import regulatory as db_reg
from services import provider_claims as pc
from services import regulatory_engine as engine
from services import regulatory_state as st
from tests.test_w9g_engine import (ADDR_SID, BU_SID, DOC_SID, EU_SID, GOOD_ADDRESS,
                                   GOOD_ATTRS, SUB, TENANT, ProviderError, tenant,
                                   world)  # noqa: F401


def _src(fn):
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)):
        node.body = node.body[1:]
    return ast.unparse(tree)


def _claim(world, resource):
    return next((c for c in world["claims"] if c["resource"] == resource), None)


async def _address(world):
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert r["ok"], r
    return r["address"]


async def _prepared(world):
    await _address(world)
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["ok"], r
    return r


NOT_FOUND = ProviderError(code=20404, status=404, detail="not found")
TIMEOUT = ProviderError(code=None, status=None, detail="connection reset")
SERVER_ERROR = ProviderError(code=20500, status=500, detail="internal error")
THROTTLED = ProviderError(code=20429, status=429, detail="too many requests")
FORBIDDEN = ProviderError(code=20403, status=403, detail="forbidden")


# ══════════════════════════════════════════════════════════════════════════
# the authoritative-absence rule
# ══════════════════════════════════════════════════════════════════════════

def test_only_a_404_proves_a_resource_is_gone():
    assert engine._is_authoritative_not_found(NOT_FOUND) is True


@pytest.mark.parametrize("err", [TIMEOUT, SERVER_ERROR, THROTTLED, FORBIDDEN,
                                 ProviderError(code=20401, status=401, detail="x"),
                                 ProviderError(code=None, status=502, detail="bad gw"),
                                 ValueError("malformed provider response"),
                                 Exception("something")])
def test_nothing_else_ever_proves_absence(err):
    """Clearing a live regulatory identity because of a network hiccup is the
    failure mode this rule exists to prevent."""
    assert engine._is_authoritative_not_found(err) is False


def test_a_not_found_code_alongside_a_5xx_is_not_authoritative():
    """20404 in the body of a 500 is not an answer about the resource."""
    assert engine._is_authoritative_not_found(
        ProviderError(code=20404, status=500, detail="x")) is False


def test_verification_classifies_into_exactly_three_outcomes():
    ok = engine._verify_provider_resource(lambda sid: None, "ITx")
    gone = engine._verify_provider_resource(lambda sid: (_ for _ in ()).throw(NOT_FOUND), "ITx")
    unknown = engine._verify_provider_resource(lambda sid: (_ for _ in ()).throw(TIMEOUT), "ITx")
    assert ok["verdict"] == engine.VERIFY_EXISTS
    assert gone["verdict"] == engine.VERIFY_NOT_FOUND
    assert unknown["verdict"] == engine.VERIFY_UNAVAILABLE


# ══════════════════════════════════════════════════════════════════════════
# EndUser — tests 1-6
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_an_attached_enduser_is_fetched_before_it_is_reused(world):
    await _prepared(world)
    fetched = []
    world["twilio"].opts["on_end_user_fetch"] = lambda sid: fetched.append(sid)
    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["ok"], r
    assert EU_SID in fetched, "the attached SID was reused without asking the provider"


@pytest.mark.asyncio
async def test_an_enduser_404_retires_the_claim_and_recreates_once(world):
    await _prepared(world)
    claim = _claim(world, "end_user")
    assert claim["provider_sid"] == EU_SID
    world["twilio"].gone.add(EU_SID)                # deleted at the provider

    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["ok"], r
    assert world["twilio"].created["end_user"] == 2, "exactly one replacement"
    assert claim["provider_sid"] == r["end_user_sid"] != EU_SID
    assert len(world["claims"]) == len({c["id"] for c in world["claims"]})


@pytest.mark.asyncio
@pytest.mark.parametrize("err,label", [(TIMEOUT, "timeout"), (SERVER_ERROR, "500"),
                                       (THROTTLED, "429"), (FORBIDDEN, "403")])
async def test_a_non_404_never_retires_and_never_recreates(world, err, label):
    await _prepared(world)
    claim = _claim(world, "end_user")
    world["twilio"].opts["end_user_fetch_error"] = err
    before = world["twilio"].created["end_user"]

    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["status"] == engine.PROVIDER_UNAVAILABLE, r
    assert claim["provider_sid"] == EU_SID, f"{label} cleared a live identity"
    assert world["twilio"].created["end_user"] == before, "nothing may be created"


@pytest.mark.asyncio
async def test_the_claim_and_the_profile_agree_after_a_recovery(world):
    await _prepared(world)
    world["twilio"].gone.add(EU_SID)
    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["ok"], r
    claim = _claim(world, "end_user")
    profile = world["profiles"][0]
    assert claim["provider_sid"] == profile["end_user_sid"] == r["end_user_sid"], \
        "the claim and the profile disagree about the regulatory identity"


@pytest.mark.asyncio
async def test_a_legacy_sibling_sid_is_ADOPTED_not_duplicated(world):
    """A pre-030 tenant already has an EndUser. Creating a second one would mint a
    duplicate identity for a business that already has one."""
    await _address(world)
    world["profiles"].append({
        "id": "prof-legacy", "tenant_id": TENANT, "iso_country": "IE",
        "number_type": "local", "end_user_type": "business",
        "provider_account_sid": SUB, "end_user_sid": "ITlegacy",
        "regulatory_address_id": "addr-9", "state": st.DETAILS_REQUIRED,
        "authorization_id": None})
    world["twilio"].end_user_store["ITlegacy"] = type(
        "O", (), {"sid": "ITlegacy", "friendly_name": "legacy", "attributes": {}})()

    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["ok"], r
    assert r["end_user_sid"] == "ITlegacy", "the existing identity must be adopted"
    assert world["twilio"].created["end_user"] == 0, "nothing may be created"
    assert _claim(world, "end_user")["provider_sid"] == "ITlegacy"


@pytest.mark.asyncio
async def test_a_legacy_seed_that_cannot_be_verified_is_not_adopted(world):
    await _address(world)
    world["profiles"].append({
        "id": "prof-legacy", "tenant_id": TENANT, "iso_country": "IE",
        "number_type": "local", "end_user_type": "business",
        "provider_account_sid": SUB, "end_user_sid": "ITlegacy",
        "regulatory_address_id": "addr-9", "state": st.DETAILS_REQUIRED,
        "authorization_id": None})
    world["twilio"].opts["end_user_fetch_error"] = TIMEOUT
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.PROVIDER_UNAVAILABLE
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_the_claim_beats_a_disagreeing_sibling_rather_than_overwriting_it(world):
    await _prepared(world)
    world["profiles"].append({
        "id": "prof-odd", "tenant_id": TENANT, "iso_country": "IE",
        "number_type": "local", "end_user_type": "business",
        "provider_account_sid": SUB, "end_user_sid": "ITsomethingelse",
        "regulatory_address_id": "addr-9", "state": st.DETAILS_REQUIRED,
        "authorization_id": None})
    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["status"] == engine.REGULATORY_IDENTITY_CONFLICT


def test_sibling_profiles_can_no_longer_override_the_claim():
    body = _src(engine.resolve_end_user)
    assert "seed" in body, "a sibling SID must be a seed, not an early return"
    assert "_ensure_provider_resource" in body
    assert body.index("_ensure_provider_resource") > body.index("seed")


# ══════════════════════════════════════════════════════════════════════════
# SupportingDocument — tests 7-10
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_an_attached_document_is_fetched_before_it_is_reused(world):
    await _prepared(world)
    fetched = []
    world["twilio"].opts["on_document_fetch"] = lambda sid: fetched.append(sid)
    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["ok"], r
    assert DOC_SID in fetched


@pytest.mark.asyncio
async def test_a_document_404_retires_and_recreates_once(world):
    await _prepared(world)
    claim = _claim(world, "supporting_document")
    assert claim["provider_sid"] == DOC_SID
    world["twilio"].gone.add(DOC_SID)

    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["ok"], r
    assert world["twilio"].created["document"] == 2
    assert claim["provider_sid"] == r["supporting_document_sid"] != DOC_SID


@pytest.mark.asyncio
@pytest.mark.parametrize("err", [TIMEOUT, SERVER_ERROR])
async def test_a_document_non_404_never_retires(world, err):
    await _prepared(world)
    claim = _claim(world, "supporting_document")
    world["twilio"].opts["document_fetch_error"] = err
    before = world["twilio"].created["document"]
    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["status"] == engine.PROVIDER_UNAVAILABLE
    assert claim["provider_sid"] == DOC_SID
    assert world["twilio"].created["document"] == before


@pytest.mark.asyncio
async def test_the_claim_and_the_address_agree_after_a_document_recovery(world):
    await _prepared(world)
    world["twilio"].gone.add(DOC_SID)
    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["ok"], r
    claim = _claim(world, "supporting_document")
    address = world["addresses"][0]
    assert claim["provider_sid"] == address["supporting_document_sid"], \
        "the claim and the address row disagree about the document"


# ══════════════════════════════════════════════════════════════════════════
# Bundle — tests 11-13
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_DRAFT_bundle_404_is_eligible_for_retirement(world):
    await _prepared(world)
    claim = _claim(world, "bundle")
    assert claim["provider_sid"] == BU_SID
    profile = world["profiles"][0]
    assert profile["state"] not in (st.PENDING_REVIEW, st.APPROVED)
    world["twilio"].gone.add(BU_SID)

    r = await engine.prepare_profile(tenant(), attributes={})
    world["twilio"].opts.pop("bundle_fetch_error", None)
    assert r["ok"] or r["status"] == engine.PROVIDER_UNAVAILABLE, r
    assert claim["provider_sid"] != BU_SID or r["ok"], \
        "a draft bundle must be retirable"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [st.PENDING_REVIEW, st.MORE_INFORMATION_REQUIRED,
                                   st.APPROVED, st.REJECTED, st.NUMBER_PROVISIONING,
                                   st.ACTIVE])
async def test_a_FILED_bundle_404_FAILS_CLOSED_and_is_never_recreated(world, state):
    """Quietly creating a second Bundle would file the same business twice and erase
    the trail of the first."""
    await _prepared(world)
    claim = _claim(world, "bundle")
    profile = world["profiles"][0]
    profile["state"] = state
    world["twilio"].gone.add(BU_SID)
    before = world["twilio"].created["bundle"]

    out = await engine.ensure_bundle(tenant(), profile=profile, requirements=None,
                                     end_user_sid=EU_SID,
                                     client=world["twilio"], sub_sid=SUB)
    assert out["status"] == engine.PROVIDER_RESOURCE_RETIRED, out
    assert claim["provider_sid"] == BU_SID, "a filed bundle must not be detached"
    assert world["twilio"].created["bundle"] == before


@pytest.mark.asyncio
async def test_a_submitted_at_timestamp_alone_also_blocks_recreation(world):
    await _prepared(world)
    claim = _claim(world, "bundle")
    profile = world["profiles"][0]
    profile["submitted_at"] = "2026-09-01T00:00:00Z"
    world["twilio"].gone.add(BU_SID)
    out = await engine.ensure_bundle(tenant(), profile=profile, requirements=None,
                                     end_user_sid=EU_SID,
                                     client=world["twilio"], sub_sid=SUB)
    assert out["status"] == engine.PROVIDER_RESOURCE_RETIRED
    assert claim["provider_sid"] == BU_SID


# ══════════════════════════════════════════════════════════════════════════
# the retirement CAS — tests 14-18
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_retirement_requires_the_EXPECTED_sid(world):
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="end_user", scope_key="IE:business",
        provider_account_sid=SUB)
    await db_reg.attach_provider_sid(claim["id"], "ITold", SUB)
    assert await db_reg.retire_provider_claim(claim["id"], "ITsomethingelse") is None
    assert claim["provider_sid"] == "ITold"
    assert await db_reg.retire_provider_claim(claim["id"], "ITold") is not None
    assert claim["provider_sid"] is None


@pytest.mark.asyncio
async def test_a_stale_worker_cannot_retire_a_REPLACEMENT_sid(world):
    """CASE 2: A proved OLD absent; meanwhile the claim already holds NEW."""
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="end_user", scope_key="IE:business",
        provider_account_sid=SUB)
    await db_reg.attach_provider_sid(claim["id"], "ITold", SUB)
    await db_reg.retire_provider_claim(claim["id"], "ITold")
    await db_reg.attach_provider_sid(claim["id"], "ITnew", SUB)

    assert await db_reg.retire_provider_claim(claim["id"], "ITold") is None
    assert claim["provider_sid"] == "ITnew", "a stale 404 cleared the replacement"


@pytest.mark.asyncio
async def test_two_concurrent_retirements_produce_exactly_one_winner(world):
    """CASE 1."""
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="end_user", scope_key="IE:business",
        provider_account_sid=SUB)
    await db_reg.attach_provider_sid(claim["id"], "ITold", SUB)
    a = await db_reg.retire_provider_claim(claim["id"], "ITold")
    b = await db_reg.retire_provider_claim(claim["id"], "ITold")
    assert (a is None) != (b is None), "exactly one retirement may win"


def test_retirement_preserves_the_scope_and_the_account():
    body = _src(db_reg.retire_provider_claim)
    for immutable in ("tenant_id", "resource", "scope_key", "created_at"):
        assert f'"{immutable}"' not in body, f"retirement must not touch {immutable}"
    assert "provider_account_sid" not in body.split(".update(")[1].split(")")[0], \
        "provider_account_sid identifies the scope's sub-account and is preserved"
    # ast.unparse normalises quoting, so compare on a quote-insensitive form
    flat = body.replace("'", '"')
    assert 'eq("provider_sid", expected_provider_sid)' in flat, \
        "the fence must be the expected SID"


def test_retirement_is_not_a_delete_and_reinsert():
    body = _src(db_reg.retire_provider_claim)
    assert ".delete(" not in body and ".insert(" not in body


# ══════════════════════════════════════════════════════════════════════════
# retirement does not bypass the QA.4 guarantees — tests 19-20
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_after_retirement_an_unknown_create_still_reconciles_by_marker(world):
    """Retirement must not become a side door around marker reconciliation."""
    from tests.test_w9g_engine import FakeTwilio
    await _prepared(world)
    world["twilio"].gone.add(EU_SID)
    orig = FakeTwilio.end_users.fget

    def patched(self):
        res = orig(self)

        def timing_out(**kw):
            self.end_user_store["ITghost"] = type(
                "O", (), {"sid": "ITghost", "friendly_name": kw.get("friendly_name"),
                          "attributes": {}})()
            raise TIMEOUT
        res._create = timing_out
        return res

    FakeTwilio.end_users = property(patched)
    try:
        r = await engine.prepare_profile(tenant(), attributes={})
    finally:
        FakeTwilio.end_users = property(orig)
    assert r["ok"], r
    assert r["end_user_sid"] == "ITghost", "the ambiguous create must be adopted"
    live = [x for x in world["twilio"].end_user_store
            if x not in world["twilio"].gone]
    assert live == ["ITghost"], f"no blind duplicate; live={live}"


@pytest.mark.asyncio
async def test_after_retirement_two_marker_matches_still_fail_closed(world):
    await _prepared(world)
    claim = _claim(world, "end_user")
    world["twilio"].gone.add(EU_SID)
    marker = pc.marker("end_user", claim["id"])
    for sid in ("ITone", "ITtwo"):
        world["twilio"].end_user_store[sid] = type(
            "O", (), {"sid": sid, "friendly_name": marker, "attributes": {}})()

    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["status"] == engine.PROVIDER_IDENTITY_CONFLICT
    assert r["count"] == 2


def test_the_verification_runs_before_any_create_in_the_source():
    body = _src(engine._ensure_provider_resource)
    assert body.index("_verify_provider_resource") < body.index("create(marker)")
    assert body.index("retire_provider_claim") < body.index("create(marker)")


# ══════════════════════════════════════════════════════════════════════════
# global — tests 21-26
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("err", [NOT_FOUND, TIMEOUT, SERVER_ERROR])
async def test_no_customer_content_is_logged_on_any_verification_path(world, caplog, err):
    await _prepared(world)
    world["twilio"].opts["end_user_fetch_error"] = err
    with caplog.at_level(logging.DEBUG):
        await engine.prepare_profile(tenant(), attributes={})
    text = "\n".join(r.getMessage() for r in caplog.records)
    for leak in (GOOD_ATTRS["business_name"], GOOD_ATTRS["email"],
                 GOOD_ATTRS["business_registration_number"],
                 GOOD_ADDRESS["street"], GOOD_ADDRESS["postal_code"]):
        assert leak not in text, f"{leak!r} leaked into the log"


@pytest.mark.asyncio
async def test_the_retirement_warning_names_the_claim_not_the_sid_in_full(world):
    await _prepared(world)
    world["twilio"].gone.add(EU_SID)
    with caplog_at(logging.DEBUG) as records:
        await engine.prepare_profile(tenant(), attributes={})
    text = "\n".join(records)
    assert EU_SID not in text, "a full provider SID was logged verbatim"


class caplog_at:
    """A tiny handler capture, because caplog cannot be nested in a fixture here."""
    def __init__(self, level):
        self.level = level
        self.records = []

    def __enter__(self):
        self.handler = logging.Handler()
        self.handler.emit = lambda r: self.records.append(r.getMessage())
        logging.getLogger("services.regulatory_engine").addHandler(self.handler)
        return self.records

    def __exit__(self, *a):
        logging.getLogger("services.regulatory_engine").removeHandler(self.handler)


@pytest.mark.asyncio
@pytest.mark.parametrize("err", [NOT_FOUND, TIMEOUT, SERVER_ERROR])
async def test_nothing_is_submitted_and_no_number_is_bought_on_any_path(world, err):
    await _prepared(world)
    world["twilio"].end_user_store.clear()
    world["twilio"].opts["end_user_fetch_error"] = err
    await engine.prepare_profile(tenant(), attributes={})
    assert world["twilio"].purchases == 0
    assert world["twilio"].bundle_status == "draft"


def test_no_provider_call_happens_at_import_time():
    import pathlib
    for mod in (engine, db_reg, pc):
        src = pathlib.Path(mod.__file__).read_text()
        for node in ast.parse(src).body:
            assert isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef, ast.Assign,
                                     ast.AnnAssign, ast.Expr, ast.If, ast.Try)), \
                f"{mod.__name__}: module-level {type(node).__name__}"


# ══════════════════════════════════════════════════════════════════════════
# gaps mutation testing found in the tests above
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_stale_worker_whose_retirement_LOSES_never_creates(world):
    """CASE 6. Our 404 was about the OLD sid; another request has since attached a
    NEW one. Losing the CAS must mean following the canonical state, not creating."""
    await _prepared(world)
    claim = _claim(world, "end_user")
    world["twilio"].gone.add(EU_SID)
    before = world["twilio"].created["end_user"]

    real_retire = engine.db_reg.retire_provider_claim

    async def losing_retire(claim_id, expected):
        # Model the interleaving: somebody else retired and re-attached first.
        await real_retire(claim_id, expected)
        for c in world["claims"]:
            if c["id"] == claim_id:
                c["provider_sid"] = "ITnew"
        return None

    engine.db_reg.retire_provider_claim = losing_retire
    try:
        r = await engine.prepare_profile(tenant(), attributes={})
    finally:
        engine.db_reg.retire_provider_claim = real_retire

    assert world["twilio"].created["end_user"] == before, \
        "a worker that lost the retirement race created a duplicate identity"
    assert claim["provider_sid"] == "ITnew", "the replacement was overwritten"
    assert r["ok"] or r["status"] in (engine.PROVIDER_CREATE_IN_PROGRESS,
                                      engine.PROVIDER_UNAVAILABLE), r


@pytest.mark.asyncio
async def test_a_SIBLING_profile_is_repointed_after_a_retirement(world):
    """The profile being prepared is patched anyway; the risk is the OTHER ones.
    A sibling left holding a proven-dead SID is exactly the divergence W9H-QA.5
    blocked the release over."""
    await _prepared(world)
    sibling = {"id": "prof-sibling", "tenant_id": TENANT, "iso_country": "IE",
               "number_type": "local", "end_user_type": "business",
               "provider_account_sid": SUB, "end_user_sid": EU_SID,
               "regulatory_address_id": "addr-9", "state": st.DETAILS_REQUIRED,
               "authorization_id": None}
    world["profiles"].append(sibling)
    world["twilio"].gone.add(EU_SID)

    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["ok"], r
    canonical = _claim(world, "end_user")["provider_sid"]
    assert canonical == r["end_user_sid"] != EU_SID
    assert sibling["end_user_sid"] == canonical, \
        "a sibling profile was left pointing at a retired EndUser"
    assert all(p["end_user_sid"] == canonical for p in world["profiles"]
               if p.get("end_user_sid"))


@pytest.mark.asyncio
async def test_ONE_live_sibling_disagreeing_with_the_claim_fails_closed(world):
    """Distinct from two siblings disagreeing with each other, which the sibling
    scan already catches. Here exactly one sibling exists and it contradicts the
    canonical claim, with nothing proven dead."""
    await _address(world)
    claim = await db_reg.claim_provider_resource(
        tenant_id=TENANT, resource="end_user",
        scope_key=pc.end_user_scope("IE", "business"), provider_account_sid=SUB)
    await db_reg.attach_provider_sid(claim["id"], "ITclaim", SUB)
    world["twilio"].end_user_store["ITclaim"] = type(
        "O", (), {"sid": "ITclaim", "friendly_name": "c", "attributes": {}})()
    world["profiles"].append({
        "id": "prof-one", "tenant_id": TENANT, "iso_country": "IE",
        "number_type": "local", "end_user_type": "business",
        "provider_account_sid": SUB, "end_user_sid": "ITdifferent",
        "regulatory_address_id": "addr-9", "state": st.DETAILS_REQUIRED,
        "authorization_id": None})
    world["twilio"].end_user_store["ITdifferent"] = type(
        "O", (), {"sid": "ITdifferent", "friendly_name": "d", "attributes": {}})()

    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.REGULATORY_IDENTITY_CONFLICT, r
    assert claim["provider_sid"] == "ITclaim", "the claim must not be overwritten"
    assert world["twilio"].created["end_user"] == 0


# ══════════════════════════════════════════════════════════════════════════
# where the deliberate dead end can be reached (W9H-QA.5R Stage B)
# ══════════════════════════════════════════════════════════════════════════

def test_the_retired_dead_end_has_exactly_one_reachable_return():
    """PROVIDER_RESOURCE_RETIRED is a dead end requiring a human, so it must be
    reachable from exactly one place and only when recreation is forbidden. If it
    could fire on the ordinary 404 recovery path, every deleted EndUser would
    become a support ticket instead of a self-healing retry."""
    body = _src(engine._ensure_provider_resource)
    assert body.count("PROVIDER_RESOURCE_RETIRED") == 1
    # the return sits inside the `not may_retire` branch
    before = body.split("PROVIDER_RESOURCE_RETIRED")[0]
    assert "if not may_retire" in before
    assert before.rindex("if not may_retire") > before.rindex("VERIFY_NOT_FOUND") \
        if "VERIFY_NOT_FOUND" in before else True


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["end_user", "supporting_document", "bundle"])
async def test_the_ordinary_404_recovery_never_ends_in_the_dead_end(world, resource):
    """All three resources must SELF-HEAL from an authoritative 404 while nothing
    is filed -- proven by running each path, not by reading the flag."""
    await _prepared(world)
    tw = world["twilio"]
    tw.gone.add({"end_user": EU_SID, "supporting_document": DOC_SID,
                 "bundle": BU_SID}[resource])

    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["status"] != engine.PROVIDER_RESOURCE_RETIRED, \
        f"{resource} hit the human-review dead end on an ordinary recovery"
    assert r["ok"], r
    assert _claim(world, resource)["provider_sid"] is not None
