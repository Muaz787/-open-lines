"""
W2 — discovering and persisting every Square location.

The failure this module exists to prevent is subtle and silent: a tenant quietly
acquiring locations, or a name, that belong to somebody else. The Shahid case is
real production data, not a hypothetical — that tenant's square_location_id points
at a Square location the test merchant calls "Dani Cork" — so it gets its own
regression block at the bottom.

The db layer is patched throughout; these tests are about decisions, not Supabase.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import location_sync as ls

CORK = "L0Q8GTAZCHD42"
DUBLIN = "L9SA1AQ7XBM6K"
LIMERICK = "L9TTF8T2FBQE5"


def _loc(lid, name, status="ACTIVE", tz="America/Toronto", currency="CAD", **over):
    return {"id": lid, "name": name, "status": status, "timezone": tz,
            "currency": currency, "type": "PHYSICAL",
            "capabilities": ["CREDIT_CARD_PROCESSING"],
            "address": {"address_line_1": "123 Placeholder St"}, **over}


DANI = [_loc(CORK, "Dani Cork"), _loc(DUBLIN, "Dani Dublin"), _loc(LIMERICK, "Dani Limerick")]


def _tenant(square_location_id=CORK, **over):
    return {"id": "t-1", "business_name": "Acme", "square_location_id": square_location_id, **over}


def _db(default_location=None, bindings=None):
    return {
        "get_default_location": AsyncMock(return_value=default_location),
        "list_bindings": AsyncMock(return_value=list(bindings or [])),
        "insert_binding": AsyncMock(return_value={"id": "new"}),
        "update_binding": AsyncMock(return_value={"id": "upd"}),
    }


def _apply(mocks):
    return patch.multiple("db.locations", **mocks)


def _inserted(mocks):
    return [c.args[1] for c in mocks["insert_binding"].await_args_list]


def _updated(mocks):
    return [(c.args[1], c.args[2]) for c in mocks["update_binding"].await_args_list]


DEFAULT_LOC = {"id": "loc-1", "name": "Acme", "is_default": True}


# ── 1. three locations, three bindings ───────────────────────────────────────

@pytest.mark.asyncio
async def test_three_square_locations_produce_three_distinct_bindings():
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), DANI)

    assert out["returned"] == 3
    assert len(out["created"]) == 3
    ids = [p["provider_location_id"] for p in _inserted(mocks)]
    assert sorted(ids) == sorted([CORK, DUBLIN, LIMERICK])
    assert all(p["provider"] == "square" for p in _inserted(mocks))


@pytest.mark.asyncio
async def test_provider_metadata_is_captured():
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks):
        await ls.sync_square_locations(_tenant(), DANI)

    cork = next(p for p in _inserted(mocks) if p["provider_location_id"] == CORK)
    assert cork["provider_location_name"] == "Dani Cork"
    assert cork["provider_status"] == "ACTIVE"
    assert cork["provider_timezone"] == "America/Toronto"
    assert cork["provider_currency"] == "CAD"
    assert cork["capabilities"] == ["CREDIT_CARD_PROCESSING"]
    assert cork["raw"]["id"] == CORK
    assert cork["last_seen_at"]


# ── 2 & 11. identity is the id, never the name, never list order ─────────────

@pytest.mark.asyncio
async def test_identity_is_the_square_id_not_the_name():
    """Two locations sharing a name must still be two bindings."""
    same_name = [_loc(CORK, "Showroom"), _loc(DUBLIN, "Showroom")]
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), same_name)

    assert len(out["created"]) == 2
    assert {p["provider_location_id"] for p in _inserted(mocks)} == {CORK, DUBLIN}


@pytest.mark.asyncio
async def test_renaming_in_square_does_not_change_identity():
    prior = [{"id": "b-1", "provider_location_id": CORK, "tenant_location_id": "loc-1",
              "provider_location_name": "Dani Cork"}]
    mocks = _db(default_location=DEFAULT_LOC, bindings=prior)
    with _apply(mocks):
        out = await ls.sync_square_locations(
            _tenant(), [_loc(CORK, "DANI Cork Showroom")])

    assert out["created"] == []          # no new row
    assert out["updated"] == [CORK]
    binding_id, update = _updated(mocks)[0]
    assert binding_id == "b-1"           # same OpenLines binding
    assert update["provider_location_name"] == "DANI Cork Showroom"


@pytest.mark.asyncio
async def test_no_locations_zero_assumption_result_is_order_independent():
    """The strongest available proof that no locations[0] logic survives: shuffle
    the list and the outcome must be identical."""
    outcomes = []
    for ordering in ([CORK, DUBLIN, LIMERICK], [LIMERICK, DUBLIN, CORK], [DUBLIN, CORK, LIMERICK]):
        locs = [next(l for l in DANI if l["id"] == lid) for lid in ordering]
        mocks = _db(default_location=DEFAULT_LOC)
        with _apply(mocks):
            out = await ls.sync_square_locations(_tenant(square_location_id=CORK), locs)
        outcomes.append((out["attached_to_default"], sorted(out["unmapped"])))

    assert all(o == outcomes[0] for o in outcomes)
    assert outcomes[0][0] == CORK                      # the stored pointer wins
    assert outcomes[0][1] == sorted([DUBLIN, LIMERICK])


def test_source_has_no_positional_location_indexing():
    """A structural guard so the assumption cannot creep back during a later edit.

    Checks executable code only — docstrings and comments discuss locations[0] by
    name precisely because it is the thing being avoided, and an earlier version of
    this test failed on its own prose.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ls))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            target = ast.unparse(node.value)
            if node.slice.value == 0 and "location" in target.lower():
                offenders.append(ast.unparse(node))
    assert not offenders, f"positional indexing into a location list: {offenders}"


# ── 3 & 4. idempotency ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resync_does_not_duplicate_bindings():
    prior = [{"id": f"b-{i}", "provider_location_id": lid, "tenant_location_id": None}
             for i, lid in enumerate([CORK, DUBLIN, LIMERICK])]
    mocks = _db(default_location=DEFAULT_LOC, bindings=prior)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), DANI)

    assert out["created"] == []
    assert sorted(out["updated"]) == sorted([CORK, DUBLIN, LIMERICK])
    mocks["insert_binding"].assert_not_awaited()


@pytest.mark.asyncio
async def test_resync_refreshes_metadata_and_last_seen():
    prior = [{"id": "b-1", "provider_location_id": CORK, "tenant_location_id": "loc-1",
              "provider_status": "ACTIVE", "last_seen_at": "2020-01-01T00:00:00Z"}]
    mocks = _db(default_location=DEFAULT_LOC, bindings=prior)
    with _apply(mocks):
        await ls.sync_square_locations(_tenant(), [_loc(CORK, "Dani Cork", status="INACTIVE")])

    _, update = _updated(mocks)[0]
    assert update["provider_status"] == "INACTIVE"
    assert update["last_seen_at"] > "2020-01-01T00:00:00Z"


# ── 5 & 6. discovered locations are inert ────────────────────────────────────

@pytest.mark.asyncio
async def test_discovered_locations_are_left_unmapped():
    """No tenant_location is invented for a location Square merely returned."""
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(square_location_id=CORK), DANI)

    assert sorted(out["unmapped"]) == sorted([DUBLIN, LIMERICK])
    for payload in _inserted(mocks):
        if payload["provider_location_id"] != CORK:
            assert payload["tenant_location_id"] is None


@pytest.mark.asyncio
async def test_sync_never_creates_a_tenant_location():
    """booking_enabled=false for new locations is guaranteed structurally: W2
    creates no tenant_location at all, so there is nothing to be bookable."""
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks), \
         patch("db.locations.insert_location", new=AsyncMock()) as insert_location:
        await ls.sync_square_locations(_tenant(), DANI)
    insert_location.assert_not_awaited()


# ── 7 & 8. the legacy link ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_existing_w1_binding_is_enriched_not_duplicated():
    prior = [{"id": "b-1", "provider_location_id": CORK, "tenant_location_id": "loc-1",
              "provider_location_name": None, "provider_status": None}]
    mocks = _db(default_location=DEFAULT_LOC, bindings=prior)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), DANI)

    assert CORK not in out["created"]
    assert CORK in out["updated"]
    binding_id, update = next(u for u in _updated(mocks) if u[0] == "b-1")
    assert update["provider_location_name"] == "Dani Cork"   # enriched
    assert update["provider_status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_attachment_follows_the_stored_pointer_not_the_first_location():
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(square_location_id=LIMERICK), DANI)

    assert out["attached_to_default"] == LIMERICK
    attached = [p for p in _inserted(mocks) if p["tenant_location_id"] == "loc-1"]
    assert [p["provider_location_id"] for p in attached] == [LIMERICK]


@pytest.mark.asyncio
async def test_an_existing_mapping_is_never_repointed():
    prior = [{"id": "b-1", "provider_location_id": DUBLIN, "tenant_location_id": "loc-1"}]
    mocks = _db(default_location=DEFAULT_LOC, bindings=prior)
    with _apply(mocks):
        await ls.sync_square_locations(_tenant(square_location_id=CORK), DANI)

    _, dublin_update = next(u for u in _updated(mocks) if u[0] == "b-1")
    assert "tenant_location_id" not in dublin_update


@pytest.mark.asyncio
async def test_sync_never_writes_to_the_tenants_table():
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks), patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        await ls.sync_square_locations(_tenant(), DANI)
    upd.assert_not_awaited()


# ── 9 & 10. inactive and missing ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inactive_square_location_is_retained_and_marked():
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks):
        await ls.sync_square_locations(
            _tenant(), [_loc(CORK, "Dani Cork"), _loc(DUBLIN, "Dani Dublin", status="INACTIVE")])

    dublin = next(p for p in _inserted(mocks) if p["provider_location_id"] == DUBLIN)
    assert dublin["provider_status"] == "INACTIVE"
    assert dublin["tenant_location_id"] is None       # never becomes bookable


@pytest.mark.asyncio
async def test_disappeared_location_is_marked_missing_not_deleted():
    prior = [{"id": "b-1", "provider_location_id": CORK, "tenant_location_id": "loc-1"},
             {"id": "b-2", "provider_location_id": DUBLIN, "tenant_location_id": None}]
    mocks = _db(default_location=DEFAULT_LOC, bindings=prior)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), [_loc(CORK, "Dani Cork")])

    assert out["missing"] == [DUBLIN]
    binding_id, update = next(u for u in _updated(mocks) if u[0] == "b-2")
    assert update == {"provider_status": ls.STATUS_MISSING}
    # last_seen_at deliberately untouched: it should keep saying when we last saw it
    assert "last_seen_at" not in update


@pytest.mark.asyncio
async def test_already_missing_location_is_not_rewritten_every_sync():
    prior = [{"id": "b-2", "provider_location_id": DUBLIN,
              "provider_status": ls.STATUS_MISSING, "tenant_location_id": None}]
    mocks = _db(default_location=DEFAULT_LOC, bindings=prior)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), [])

    assert out["missing"] == [DUBLIN]
    mocks["update_binding"].assert_not_awaited()


@pytest.mark.asyncio
async def test_a_returning_location_is_revived_from_missing():
    prior = [{"id": "b-2", "provider_location_id": DUBLIN,
              "provider_status": ls.STATUS_MISSING, "tenant_location_id": None}]
    mocks = _db(default_location=DEFAULT_LOC, bindings=prior)
    with _apply(mocks):
        await ls.sync_square_locations(_tenant(), [_loc(DUBLIN, "Dani Dublin")])

    _, update = _updated(mocks)[0]
    assert update["provider_status"] == "ACTIVE"


# ── 12 & 13. existing tenants are unaffected ─────────────────────────────────

@pytest.mark.asyncio
async def test_single_location_square_tenant_is_unchanged():
    prior = [{"id": "b-1", "provider_location_id": CORK, "tenant_location_id": "loc-1"}]
    mocks = _db(default_location=DEFAULT_LOC, bindings=prior)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), [_loc(CORK, "Acme")])

    assert out["created"] == [] and out["unmapped"] == [] and out["missing"] == []
    assert out["updated"] == [CORK]


@pytest.mark.asyncio
async def test_tenant_with_no_square_pointer_gets_bindings_but_no_attachment():
    """A non-Square tenant never reaches this code, but if a merchant is connected
    with no pointer set, nothing may be attached by guesswork."""
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(square_location_id=None), DANI)

    assert out["attached_to_default"] is None
    assert sorted(out["unmapped"]) == sorted([CORK, DUBLIN, LIMERICK])
    assert all(p["tenant_location_id"] is None for p in _inserted(mocks))


@pytest.mark.asyncio
async def test_tenant_with_no_default_location_attaches_nothing():
    mocks = _db(default_location=None)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), DANI)
    assert out["attached_to_default"] is None
    assert all(p["tenant_location_id"] is None for p in _inserted(mocks))


@pytest.mark.asyncio
async def test_location_without_an_id_is_skipped_not_guessed():
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), [{"name": "Broken"}, _loc(CORK, "Dani Cork")])

    assert "location_without_id" in out["errors"]
    assert [p["provider_location_id"] for p in _inserted(mocks)] == [CORK]


@pytest.mark.asyncio
async def test_dry_run_writes_nothing():
    mocks = _db(default_location=DEFAULT_LOC)
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), DANI, dry_run=True)

    assert len(out["created"]) == 3
    mocks["insert_binding"].assert_not_awaited()
    mocks["update_binding"].assert_not_awaited()


# ── 14. Shahid regression ────────────────────────────────────────────────────

SHAHID = {"id": "a85ba5cf-5c79-4044-8f39-06eaf9d158ff",
          "business_name": "Shahid Real Estate", "square_location_id": CORK}
SHAHID_LOC = {"id": "11dd04f8-8c83-4b39-acfe-8b718d9b7b24",
              "name": "Shahid Real Estate", "is_default": True}


@pytest.mark.asyncio
async def test_shahid_keeps_its_own_name_when_square_calls_the_location_dani_cork():
    """Production edge case. Shahid's square_location_id points at a Square location
    the shared test merchant labels "Dani Cork". The tenant-facing name must survive
    untouched — a real-estate business must not acquire a dress showroom's name."""
    mocks = _db(default_location=SHAHID_LOC)
    with _apply(mocks), \
         patch("db.locations.update_location", new=AsyncMock()) as update_location:
        out = await ls.sync_square_locations(SHAHID, DANI)

    update_location.assert_not_awaited()
    assert out["name_mismatch"] == {
        "tenant_location_id": SHAHID_LOC["id"],
        "openlines_name": "Shahid Real Estate",
        "square_name": "Dani Cork",
    }


@pytest.mark.asyncio
async def test_shahid_drift_is_reported_when_w1_already_attached_the_binding():
    """Regression for a bug this suite originally missed: the first version only
    reported drift when THIS run performed the attachment. In production W1 had
    already attached Cork, so the real Shahid case silently reported no mismatch.
    Models the true production state — a prior binding already mapped."""
    prior = [{"id": "b-1", "provider_location_id": CORK,
              "tenant_location_id": SHAHID_LOC["id"],
              "provider_location_name": None}]
    mocks = _db(default_location=SHAHID_LOC, bindings=prior)
    with _apply(mocks):
        out = await ls.sync_square_locations(SHAHID, DANI)

    assert out["attached_to_default"] is None      # nothing newly attached, correctly
    assert out["bound_to_default"] == CORK         # but we know what IS bound
    assert out["name_mismatch"] == {
        "tenant_location_id": SHAHID_LOC["id"],
        "openlines_name": "Shahid Real Estate",
        "square_name": "Dani Cork",
    }


@pytest.mark.asyncio
async def test_shahid_does_not_acquire_dublin_and_limerick_as_business_locations():
    mocks = _db(default_location=SHAHID_LOC)
    with _apply(mocks), \
         patch("db.locations.insert_location", new=AsyncMock()) as insert_location:
        out = await ls.sync_square_locations(SHAHID, DANI)

    insert_location.assert_not_awaited()
    assert sorted(out["unmapped"]) == sorted([DUBLIN, LIMERICK])
    for payload in _inserted(mocks):
        if payload["provider_location_id"] in (DUBLIN, LIMERICK):
            assert payload["tenant_location_id"] is None


@pytest.mark.asyncio
async def test_shahid_square_pointer_is_untouched():
    before = SHAHID["square_location_id"]
    mocks = _db(default_location=SHAHID_LOC)
    with _apply(mocks), patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        await ls.sync_square_locations(SHAHID, DANI)

    upd.assert_not_awaited()
    assert SHAHID["square_location_id"] == before


@pytest.mark.asyncio
async def test_matching_names_report_no_mismatch():
    mocks = _db(default_location={"id": "loc-1", "name": "Dani Cork", "is_default": True})
    with _apply(mocks):
        out = await ls.sync_square_locations(_tenant(), DANI)
    assert out["name_mismatch"] is None
