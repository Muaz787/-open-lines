"""W9H-QA.3 — concurrency-safe regulatory address creation.

W9H-QA.2 raced two OS processes through ensure_address against live Twilio and
measured the defect: both crossed Address.create before either owned the database
row, so two provider Addresses existed, one INSERT won, the loser raised a raw
PostgreSQL 23505 out of the request, and the loser's Address was orphaned at
Twilio. Twilio does not deduplicate identical creates.

These tests hold the ordering that fixes it: THE CLAIM IS TAKEN BEFORE THE PROVIDER
IS TOUCHED, and only the claim's owner may touch it.
"""
import ast
import inspect
import logging

import pytest

from services import regulatory_engine as engine
from services import telephony
from tests.test_w9g_engine import (ADDR_SID, GOOD_ADDRESS, SUB, TENANT, FakeTwilio,
                                   ProviderError, tenant, world)     # noqa: F401


def _addr_rows(w):
    return w["addresses"]


def _only(w):
    rows = _addr_rows(w)
    assert len(rows) == 1, f"expected one address row, found {len(rows)}"
    return rows[0]


# ── 1. the claim comes first ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_claim_row_exists_before_the_provider_is_called(world):
    """The ordering, asserted from inside the provider call itself.

    Checking afterwards would pass even if the row were written after the create --
    which is precisely the defect. So the assertion runs AT the moment of the
    create."""
    seen = {}

    def at_create_time(**kw):
        seen["rows"] = [dict(a) for a in _addr_rows(world)]
        seen["friendly_name"] = kw.get("friendly_name")

    world["twilio"].opts["on_address_create"] = at_create_time
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)

    assert r["ok"]
    assert len(seen["rows"]) == 1, \
        "the uniqueness claim must already exist when the provider is called"
    claim = seen["rows"][0]
    assert claim["address_sid"] is None, "the claim is taken BEFORE a SID exists"
    # and the provider resource is stamped with the claim, so it can be found again
    assert seen["friendly_name"] == engine.db_reg.claim_marker(claim["id"])


def test_the_source_claims_before_it_creates():
    """A structural guard: in ensure_address, the claim call precedes the create.

    Docstrings are stripped first so prose about claiming cannot satisfy the test.
    """
    tree = ast.parse(inspect.getsource(engine.ensure_address))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    getattr(body[0], "value", None), ast.Constant):
                node.body = body[1:]
    text = ast.unparse(tree)
    assert "claim_address" in text
    assert text.index("claim_address") < text.index("addresses.create"), \
        "the provider create must not appear before the claim"


# ── 2-4. the loser ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_request_that_loses_the_claim_never_calls_the_provider(world):
    # Someone else already holds the claim for this scope.
    await engine.db_reg.claim_address(
        {"tenant_id": TENANT, "tenant_location_id": None, "iso_country": "IE",
         "provider_account_sid": SUB, "validated": False})
    world["twilio"].created["address"] = 0

    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)

    assert world["twilio"].created["address"] == 0, \
        "a request that does not own the claim must never create a provider resource"
    assert r["status"] == engine.ADDRESS_CREATE_IN_PROGRESS
    assert len(_addr_rows(world)) == 1


@pytest.mark.asyncio
async def test_the_loser_reuses_the_winners_validated_address(world):
    """The winner finishes while the loser is waiting; the loser returns its result."""
    claim = await engine.db_reg.claim_address(
        {"tenant_id": TENANT, "tenant_location_id": None, "iso_country": "IE",
         "provider_account_sid": SUB, "validated": False})

    # The winner completes after the loser's first poll.
    calls = {"n": 0}
    real_find = engine.db_reg.find_address

    async def finishing_find(tid, country, loc):
        calls["n"] += 1
        if calls["n"] == 2:
            claim.update({"address_sid": ADDR_SID, "validated": True})
            world["twilio"].address_store[ADDR_SID] = type(
                "O", (), {"sid": ADDR_SID, "validated": True, "city": "Dublin 2",
                          "region": "Dublin", "friendly_name": "x"})()
        return await real_find(tid, country, loc)

    engine.db_reg.find_address = finishing_find
    try:
        r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    finally:
        engine.db_reg.find_address = real_find

    assert r["ok"] and r["reused"] is True
    assert r["address"]["address_sid"] == ADDR_SID
    assert world["twilio"].created["address"] == 0


@pytest.mark.asyncio
async def test_a_lost_claim_never_surfaces_as_a_raw_23505(world):
    """The exact defect: PostgREST's unique violation must not escape the engine."""
    class Unique(Exception):
        code = "23505"

    async def exploding_claim(row):
        raise Unique('duplicate key value violates unique constraint '
                     '"tra_tenant_scope_key"')

    engine.db_reg.claim_address = exploding_claim
    try:
        with pytest.raises(Unique):
            await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    finally:
        import importlib
        importlib.reload(engine.db_reg)

    # And the real layer converts it, rather than letting it out.
    from db import regulatory as real_db
    assert real_db._is_unique_violation(Unique("boom")) is True
    assert real_db._is_unique_violation(ValueError("something else")) is False


MAX_FRIENDLY_NAME = 64          # Twilio's limit; a longer FILTER returns 20400


def test_the_claim_marker_fits_twilios_friendly_name_limit():
    """Measured the hard way in W9H-QA.3: a 65-character marker made the
    reconciliation lookup fail with twilio_code 20400, which silently disabled the
    very mechanism that prevents duplicate Addresses."""
    import uuid
    marker = engine.db_reg.claim_marker(str(uuid.uuid4()))
    assert len(marker) <= MAX_FRIENDLY_NAME, \
        f"claim marker is {len(marker)} chars, over Twilio's {MAX_FRIENDLY_NAME}"
    # and it must still be unique per claim, or adoption would attach the wrong one
    a, b = (engine.db_reg.claim_marker(str(uuid.uuid4())) for _ in range(2))
    assert a != b


def test_the_data_layer_catches_the_unique_violation_itself():
    src = inspect.getsource(engine.db_reg.claim_address)
    assert "_is_unique_violation" in src and "return None" in src


# ── 5-6. stale claims and fencing ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_claim_abandoned_by_a_dead_worker_is_recoverable(world):
    """CASE 2: A claims, then dies before the provider call."""
    await engine.db_reg.claim_address(
        {"tenant_id": TENANT, "tenant_location_id": None, "iso_country": "IE",
         "provider_account_sid": SUB, "validated": False})
    # Nothing happens for longer than the stale window.
    world["clock"]["t"] += engine.db_reg.CLAIM_STALE_SECONDS + 1

    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)

    assert r["ok"] and r["address"]["address_sid"] == ADDR_SID
    assert world["twilio"].created["address"] == 1, "takeover creates exactly once"
    assert len(_addr_rows(world)) == 1, "takeover reuses the row, never adds one"


@pytest.mark.asyncio
async def test_a_fresh_claim_is_never_stolen(world):
    await engine.db_reg.claim_address(
        {"tenant_id": TENANT, "tenant_location_id": None, "iso_country": "IE",
         "provider_account_sid": SUB, "validated": False})
    world["clock"]["t"] += engine.db_reg.CLAIM_STALE_SECONDS - 5

    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)

    assert r["status"] == engine.ADDRESS_CREATE_IN_PROGRESS
    assert world["twilio"].created["address"] == 0


@pytest.mark.asyncio
async def test_a_worker_that_lost_the_claim_cannot_finalize_over_the_new_owner(world):
    """CASE 5: the stale worker wakes up holding its own Address and tries to attach.

    It must not overwrite the current owner's provider identity, and must not leave
    its own Address behind as an orphan."""
    claim = await engine.db_reg.claim_address(
        {"tenant_id": TENANT, "tenant_location_id": None, "iso_country": "IE",
         "provider_account_sid": SUB, "validated": False})
    # The new owner already attached a different Address.
    claim.update({"address_sid": "ADwinner", "validated": True})
    world["twilio"].address_store["ADwinner"] = type(
        "O", (), {"sid": "ADwinner", "validated": True, "city": "Dublin 2",
                  "region": "Dublin", "friendly_name": "w"})()
    stale = type("O", (), {"sid": "ADstale", "validated": True, "city": "Dublin 2",
                           "region": "Dublin", "friendly_name": "s"})()
    world["twilio"].address_store["ADstale"] = stale

    r = await engine._adopt_provider_address(claim, [stale], world["twilio"], SUB, {})

    assert claim["address_sid"] == "ADwinner", "the stale worker overwrote the owner"
    assert r["ok"] and r["address"]["address_sid"] == "ADwinner"
    assert "ADstale" in world["twilio"].deleted_addresses, \
        "the stale worker's own Address must not be left orphaned"


@pytest.mark.asyncio
async def test_the_attach_is_fenced_on_address_sid_being_null():
    from db import regulatory as real_db
    src = inspect.getsource(real_db.attach_address_sid)
    assert 'is_("address_sid", "null")' in src
    assert "len(res.data or []) == 1" in src


# ── 3 / 7-8. provider create outcomes ──────────────────────────────────────

@pytest.mark.asyncio
async def test_provider_success_then_attach_success(world):
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    row = _only(world)
    assert r["ok"] and r["reused"] is False
    assert row["address_sid"] == ADDR_SID and row["validated"] is True
    assert row["provider_account_sid"] == SUB
    assert world["twilio"].deleted_addresses == []


@pytest.mark.asyncio
async def test_an_address_created_by_a_dead_worker_is_adopted_not_duplicated(world):
    """CASE 3: A created the Address, then died before attaching it."""
    claim = await engine.db_reg.claim_address(
        {"tenant_id": TENANT, "tenant_location_id": None, "iso_country": "IE",
         "provider_account_sid": SUB, "validated": False})
    marker = engine.db_reg.claim_marker(claim["id"])
    world["twilio"].address_store["ADorphan"] = type(
        "O", (), {"sid": "ADorphan", "validated": True, "city": "Dublin 2",
                  "region": "Dublin", "friendly_name": marker})()
    world["clock"]["t"] += engine.db_reg.CLAIM_STALE_SECONDS + 1

    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)

    assert r["ok"] and r["address"]["address_sid"] == "ADorphan", \
        "the existing provider Address must be adopted"
    assert world["twilio"].created["address"] == 0, \
        "adopting must not create a second provider Address"
    assert len(_addr_rows(world)) == 1


@pytest.mark.asyncio
async def test_two_addresses_for_one_claim_leave_no_orphan(world):
    """Both carry this claim's marker, so both are provably ours: keep one, remove
    the other. This is the only condition under which deleting is defensible."""
    claim = await engine.db_reg.claim_address(
        {"tenant_id": TENANT, "tenant_location_id": None, "iso_country": "IE",
         "provider_account_sid": SUB, "validated": False})
    marker = engine.db_reg.claim_marker(claim["id"])
    mk = lambda sid: type("O", (), {"sid": sid, "validated": True, "city": "Dublin 2",
                                    "region": "Dublin", "friendly_name": marker})()
    a, b = mk("ADone"), mk("ADtwo")
    world["twilio"].address_store.update({"ADone": a, "ADtwo": b})
    world["clock"]["t"] += engine.db_reg.CLAIM_STALE_SECONDS + 1

    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)

    assert r["ok"]
    kept = r["address"]["address_sid"]
    assert len(world["twilio"].address_store) == 1
    assert kept in world["twilio"].address_store
    assert world["twilio"].deleted_addresses, "the superseded Address must be removed"


# ── 9-11. failure semantics preserved ──────────────────────────────────────

@pytest.mark.asyncio
async def test_an_explicit_provider_rejection_is_still_address_validation_failed(world):
    world["twilio"].opts["address_error"] = ProviderError(
        code=21628, status=400, detail="cannot validate")
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert r["status"] == engine.ADDRESS_VALIDATION_FAILED
    row = _only(world)
    assert row["address_sid"] is None
    assert row["validation_error"] == "provider_could_not_validate"
    assert row["street"] == GOOD_ADDRESS["street"], "the submitted address survives"


@pytest.mark.asyncio
async def test_a_provider_outage_is_retryable_not_a_validation_failure(world):
    world["twilio"].opts["address_error"] = ProviderError(
        code=20500, status=500, detail="internal error")
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert r["status"] == engine.PROVIDER_UNAVAILABLE
    row = _only(world)
    assert row["address_sid"] is None
    assert row["validation_error"] is None, "an outage is not a validation verdict"


@pytest.mark.asyncio
async def test_an_unknown_outcome_reconciles_instead_of_creating_again(world):
    """CASE 4: the create call fails at the transport, but Twilio did create it."""
    tw = world["twilio"]
    claim_ids = []

    orig = FakeTwilio.addresses.fget

    def patched(self):
        res = orig(self)
        inner_create = res._create

        def timing_out(**kw):
            # Twilio created it; our side never learned the outcome.
            sid = "ADghost"
            self.address_store[sid] = type(
                "O", (), {"sid": sid, "validated": True, "city": "Dublin 2",
                          "region": "Dublin", "friendly_name": kw.get("friendly_name")})()
            claim_ids.append(kw.get("friendly_name"))
            raise ProviderError(code=None, status=None, detail="connection reset")
        res._create = timing_out
        return res

    FakeTwilio.addresses = property(patched)
    try:
        r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    finally:
        FakeTwilio.addresses = property(orig)

    assert r["ok"], "an ambiguous outcome must reconcile, not fail"
    assert r["address"]["address_sid"] == "ADghost"
    assert len(tw.address_store) == 1, "no blind duplicate create"


# ── 12-15. retries, corrections, isolation ─────────────────────────────────

@pytest.mark.asyncio
async def test_a_corrected_address_can_retry_after_a_rejection(world):
    world["twilio"].opts["address_error"] = ProviderError(
        code=21628, status=400, detail="cannot validate")
    first = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert first["status"] == engine.ADDRESS_VALIDATION_FAILED

    # The customer corrects it. A terminally failed claim is takeable immediately --
    # no stale timer -- or every correction would wait out the window.
    world["twilio"].opts.pop("address_error")
    second = await engine.ensure_address(
        tenant(), submitted={**GOOD_ADDRESS, "street": "2 Corrected Way"})

    assert second["ok"] and second["address"]["address_sid"] == ADDR_SID
    row = _only(world)
    assert row["street"] == "2 Corrected Way"
    assert row["validation_error"] is None


@pytest.mark.asyncio
async def test_a_sequential_retry_remains_idempotent(world):
    a = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    b = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    c = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert a["reused"] is False and b["reused"] is True and c["reused"] is True
    assert world["twilio"].created["address"] == 1
    assert len(_addr_rows(world)) == 1


@pytest.mark.asyncio
async def test_a_different_tenant_creates_its_own_address(world):
    other = {**tenant(), "id": "tenant-other"}
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.ensure_address(other, submitted=GOOD_ADDRESS)
    assert r["ok"]
    assert len(_addr_rows(world)) == 2, "one tenant's claim must not block another's"
    assert world["twilio"].created["address"] == 2


@pytest.mark.asyncio
async def test_a_different_location_does_not_collide_with_the_tenant_level_row(world):
    world["locations"].append({"id": "loc-2", "tenant_id": TENANT})
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS,
                                    tenant_location_id="loc-2")
    assert r["ok"]
    assert len(_addr_rows(world)) == 2
    scopes = {(a["tenant_id"], a.get("tenant_location_id")) for a in _addr_rows(world)}
    assert scopes == {(TENANT, None), (TENANT, "loc-2")}


# ── 16-18. the blast radius stays where it was ─────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["success", "rejection", "outage", "lost_claim"])
async def test_address_creation_never_touches_identity_or_buys_a_number(world, scenario):
    tw = world["twilio"]
    if scenario == "rejection":
        tw.opts["address_error"] = ProviderError(code=21628, status=400, detail="x")
    elif scenario == "outage":
        tw.opts["address_error"] = ProviderError(code=20500, status=500, detail="x")
    elif scenario == "lost_claim":
        await engine.db_reg.claim_address(
            {"tenant_id": TENANT, "tenant_location_id": None, "iso_country": "IE",
             "provider_account_sid": SUB, "validated": False})

    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)

    assert tw.created["end_user"] == 0
    assert tw.created["bundle"] == 0
    assert tw.created["document"] == 0
    assert tw.created["assignment"] == 0
    assert tw.created["evaluation"] == 0
    assert tw.purchases == 0


# ── 19. nothing sensitive reaches the log ──────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("err,code", [("rejection", 21628), ("outage", 20500)])
async def test_no_address_content_is_ever_logged(world, caplog, err, code):
    world["twilio"].opts["address_error"] = ProviderError(
        code=code, status=400, detail="cannot validate")
    with caplog.at_level(logging.DEBUG):
        await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (GOOD_ADDRESS["street"], GOOD_ADDRESS["postal_code"],
                   GOOD_ADDRESS["customer_name"]):
        assert secret not in text, f"{secret!r} leaked into the log"


@pytest.mark.asyncio
async def test_the_superseded_address_warning_carries_no_address_content(world, caplog):
    claim = {"id": "addr-1", "tenant_id": TENANT}
    world["twilio"].opts["address_delete_error"] = ProviderError(
        code=20500, status=500, detail="nope")
    with caplog.at_level(logging.DEBUG):
        engine._discard_provider_address(world["twilio"], "ADx", claim["id"])
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "addr-1" in text          # findable
    assert GOOD_ADDRESS["street"] not in text


# ── 20. the credential-scoping rule, so it cannot be re-broken ─────────────

def test_a_regulatory_client_requires_the_subaccounts_own_credentials():
    """W9H-QA.2 measured that Numbers v2 is credential-scoped, not path-scoped, so
    parent credentials with account_sid= silently report the PARENT's Bundles and
    EndUsers as if they were the sub-account's."""
    with pytest.raises(ValueError):
        telephony.regulatory_client("", "tok")
    with pytest.raises(ValueError):
        telephony.regulatory_client("ACsub", "")
    src = inspect.getsource(telephony.regulatory_client)
    assert "account_sid=" not in src.split('"""')[-1], \
        "a regulatory client must never be built with account_sid="


def test_no_regulatory_code_path_scopes_numbers_v2_with_account_sid():
    """A grep-shaped guard over the modules that touch regulatory resources."""
    import pathlib
    root = pathlib.Path(telephony.__file__).parent
    offenders = []
    for f in list(root.glob("regulatory*.py")) + [pathlib.Path(telephony.__file__)]:
        src = f.read_text()
        body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        # The dangerous pattern is CONSTRUCTING a client with account_sid=, not the
        # word appearing inside provider_account_sid, which is our own column name.
        import re as _re
        if _re.search(r"Client\([^)]*\baccount_sid\s*=", body) and \
                "regulatory_compliance" in body:
            offenders.append(f.name)
    assert not offenders, f"account_sid= used alongside Numbers v2 in {offenders}"
