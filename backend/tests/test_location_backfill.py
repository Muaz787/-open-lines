"""
W1 backfill: one default location per tenant, one Square binding for tenants that
already have a Square location, and nothing fabricated for tenants that don't.

The property that matters is idempotency. This backfill will be run by hand against
production, probably more than once, possibly interleaved with a partial failure —
so every test that asserts "twice == once" is guarding a real operational path, not
a hypothetical one.

The db layer is patched throughout: these tests exercise the backfill's decisions,
not Supabase.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import location_backfill as bf


def _tenant(**over):
    """A plain tenant with no Square connection."""
    return {
        "id": "t-1",
        "business_name": "Acme Barbers",
        "country": "CA",
        "calendar_timezone": "America/Toronto",
        "square_location_id": None,
        "square_location_timezone": None,
        "square_currency": None,
        **over,
    }


def _square_tenant(**over):
    return _tenant(
        square_location_id="L0Q8GTAZCHD42",
        square_location_timezone="America/Toronto",
        square_currency="cad",
        **over,
    )


def _patch_db(default_location=None, binding=None, inserted_location=None):
    """Patch the whole db layer. Returns the patcher dict of AsyncMocks."""
    return {
        "get_default_location": AsyncMock(return_value=default_location),
        "get_binding": AsyncMock(return_value=binding),
        "insert_location": AsyncMock(return_value=inserted_location or {"id": "loc-1"}),
        "insert_binding": AsyncMock(return_value={"id": "bind-1"}),
    }


def _apply(mocks):
    return patch.multiple("db.locations", **mocks)


# ── 1. every tenant ends with exactly one default location ───────────────────

@pytest.mark.asyncio
async def test_tenant_without_location_gets_exactly_one_default():
    mocks = _patch_db()
    with _apply(mocks):
        out = await bf.backfill_tenant(_tenant(), dry_run=False)

    assert out["location"] == "created"
    mocks["insert_location"].assert_awaited_once()
    payload = mocks["insert_location"].await_args.args[1]
    assert payload["is_default"] is True
    assert payload["active"] is True
    assert payload["slug"] == bf.DEFAULT_SLUG


@pytest.mark.asyncio
async def test_default_location_is_bookable():
    """booking_enabled must be True. The backfilled location IS the tenant's current
    working setup; a False here would make W4's fail-closed rule silently break every
    existing tenant on the day it ships."""
    mocks = _patch_db()
    with _apply(mocks):
        await bf.backfill_tenant(_tenant(), dry_run=False)
    assert mocks["insert_location"].await_args.args[1]["booking_enabled"] is True


# ── 2. running twice leaves exactly one default ──────────────────────────────

@pytest.mark.asyncio
async def test_second_run_creates_no_second_location():
    existing = {"id": "loc-1", "is_default": True, "slug": "main"}
    mocks = _patch_db(default_location=existing)
    with _apply(mocks):
        out = await bf.backfill_tenant(_tenant(), dry_run=False)

    assert out["location"] == "exists"
    mocks["insert_location"].assert_not_awaited()


@pytest.mark.asyncio
async def test_backfill_is_idempotent_across_repeated_runs():
    """Simulate the real sequence: first run creates, every later run finds."""
    state = {"location": None}

    async def _get_default(_tenant_id):
        return state["location"]

    async def _insert(_tenant_id, payload):
        assert state["location"] is None, "attempted to create a second default"
        state["location"] = {"id": "loc-1", **payload}
        return state["location"]

    with patch.multiple("db.locations",
                        get_default_location=AsyncMock(side_effect=_get_default),
                        insert_location=AsyncMock(side_effect=_insert),
                        get_binding=AsyncMock(return_value=None),
                        insert_binding=AsyncMock(return_value={"id": "b"})):
        results = [await bf.backfill_tenant(_tenant(), dry_run=False) for _ in range(5)]

    assert results[0]["location"] == "created"
    assert all(r["location"] == "exists" for r in results[1:])


# ── 3 & 4. Square binding: created once, never twice ─────────────────────────

@pytest.mark.asyncio
async def test_square_tenant_gets_one_binding_pointing_at_its_own_location():
    mocks = _patch_db()
    with _apply(mocks):
        out = await bf.backfill_tenant(_square_tenant(), dry_run=False)

    assert out["binding"] == "created"
    mocks["insert_binding"].assert_awaited_once()
    payload = mocks["insert_binding"].await_args.args[1]
    assert payload["provider"] == "square"
    assert payload["provider_location_id"] == "L0Q8GTAZCHD42"
    assert payload["tenant_location_id"] == "loc-1"


@pytest.mark.asyncio
async def test_second_run_creates_no_second_binding():
    mocks = _patch_db(default_location={"id": "loc-1"},
                      binding={"id": "bind-1", "provider": "square"})
    with _apply(mocks):
        out = await bf.backfill_tenant(_square_tenant(), dry_run=False)

    assert out["binding"] == "exists"
    mocks["insert_binding"].assert_not_awaited()


@pytest.mark.asyncio
async def test_binding_lookup_uses_the_provider_natural_key():
    """Idempotency has to key on (tenant, provider, provider_location_id) — the
    provider's own immutable id — not on our row id, which we don't know yet."""
    mocks = _patch_db()
    with _apply(mocks):
        await bf.backfill_tenant(_square_tenant(), dry_run=False)

    args = mocks["get_binding"].await_args.args
    assert args == ("t-1", "square", "L0Q8GTAZCHD42")


# ── 5. nothing is fabricated ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_without_square_gets_no_binding():
    mocks = _patch_db()
    with _apply(mocks):
        out = await bf.backfill_tenant(_tenant(), dry_run=False)

    assert out["binding"] == "skipped_no_square"
    mocks["insert_binding"].assert_not_awaited()


@pytest.mark.asyncio
async def test_blank_square_location_id_is_not_a_binding():
    for blank in ("", "   ", None):
        mocks = _patch_db()
        with _apply(mocks):
            out = await bf.backfill_tenant(_tenant(square_location_id=blank), dry_run=False)
        assert out["binding"] == "skipped_no_square"
        mocks["insert_binding"].assert_not_awaited()


@pytest.mark.asyncio
async def test_unknowable_provider_fields_are_null_not_guessed():
    """Name and status cannot be known without calling Square, and the backfill is
    forbidden from calling Square. They must be NULL rather than filled with a
    plausible-looking value such as the business name."""
    mocks = _patch_db()
    with _apply(mocks):
        await bf.backfill_tenant(_square_tenant(), dry_run=False)

    payload = mocks["insert_binding"].await_args.args[1]
    assert payload["provider_location_name"] is None
    assert payload["provider_status"] is None
    assert payload["last_seen_at"] is None
    # …but values we already hold ARE carried, because they are facts, not guesses.
    assert payload["provider_timezone"] == "America/Toronto"
    assert payload["provider_currency"] == "cad"


@pytest.mark.asyncio
async def test_location_payload_invents_no_address_or_hours():
    mocks = _patch_db()
    with _apply(mocks):
        await bf.backfill_tenant(_tenant(), dry_run=False)

    payload = mocks["insert_location"].await_args.args[1]
    for field in ("address_line1", "address_city", "address_postal", "business_hours"):
        assert field not in payload, f"{field} must be left unset, not invented"


@pytest.mark.asyncio
async def test_existing_metadata_is_carried_but_missing_metadata_is_null():
    mocks = _patch_db()
    with _apply(mocks):
        await bf.backfill_tenant(
            _tenant(country=None, calendar_timezone=None), dry_run=False)

    payload = mocks["insert_location"].await_args.args[1]
    assert payload["country"] is None
    assert payload["timezone"] is None
    assert payload["name"] == "Acme Barbers"


@pytest.mark.asyncio
async def test_nameless_tenant_gets_a_placeholder_not_an_empty_name():
    mocks = _patch_db()
    with _apply(mocks):
        await bf.backfill_tenant(_tenant(business_name=""), dry_run=False)
    assert mocks["insert_location"].await_args.args[1]["name"] == "Main location"


# ── 6. tenants.square_location_id is never touched ───────────────────────────

@pytest.mark.asyncio
async def test_backfill_never_writes_to_the_tenants_table():
    """The whole safety story of W1: tenants.square_location_id stays authoritative
    and stays exactly where it was pointing."""
    mocks = _patch_db()
    with _apply(mocks), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as update_tenant:
        await bf.backfill_tenant(_square_tenant(), dry_run=False)

    update_tenant.assert_not_awaited()


@pytest.mark.asyncio
async def test_backfill_records_the_stored_square_id_and_does_not_repoint_it():
    """Regression guard for the live production tenant whose square_location_id
    points at the Dani Cork test location: the backfill must record that value
    verbatim, not correct it, replace it, or pick a different one."""
    tenant = _square_tenant(id="a85ba5cf-5c79-4044-8f39-06eaf9d158ff",
                            business_name="Shahid Real Estate")
    before = tenant["square_location_id"]

    mocks = _patch_db()
    with _apply(mocks):
        await bf.backfill_tenant(tenant, dry_run=False)

    assert tenant["square_location_id"] == before          # input not mutated
    assert mocks["insert_binding"].await_args.args[1]["provider_location_id"] == before


# ── dry run ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_writes_nothing():
    mocks = _patch_db()
    with _apply(mocks):
        out = await bf.backfill_tenant(_square_tenant(), dry_run=True)

    assert out["location"] == "would_create"
    assert out["binding"] == "would_create"
    mocks["insert_location"].assert_not_awaited()
    mocks["insert_binding"].assert_not_awaited()


@pytest.mark.asyncio
async def test_dry_run_predicts_exactly_what_apply_would_do():
    """A dry run that disagrees with --apply is worse than no dry run. Whitespace in
    square_location_id is the case where a sloppy truthiness check would diverge."""
    for square_id in ("", "   ", None, "L0Q8GTAZCHD42"):
        tenant = _tenant(square_location_id=square_id)

        dry_mocks = _patch_db()
        with _apply(dry_mocks):
            predicted = await bf.backfill_tenant(tenant, dry_run=True)

        real_mocks = _patch_db()
        with _apply(real_mocks):
            actual = await bf.backfill_tenant(tenant, dry_run=False)

        assert predicted["binding"].replace("would_create", "created") == actual["binding"], (
            f"dry run disagreed with apply for square_location_id={square_id!r}")


@pytest.mark.asyncio
async def test_backfill_all_defaults_to_dry_run():
    with patch("db.locations.list_all_tenants_for_backfill",
               new=AsyncMock(return_value=[_tenant(), _square_tenant(id="t-2")])), \
         patch("db.locations.get_default_location", new=AsyncMock(return_value=None)), \
         patch("db.locations.get_binding", new=AsyncMock(return_value=None)), \
         patch("db.locations.insert_location", new=AsyncMock()) as ins_loc, \
         patch("db.locations.insert_binding", new=AsyncMock()) as ins_bind:
        summary = await bf.backfill_all()

    assert summary["dry_run"] is True
    assert summary["tenants"] == 2
    assert summary["locations_would_create"] == 2
    ins_loc.assert_not_awaited()
    ins_bind.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_failing_tenant_does_not_abort_the_run():
    async def _get_default(tenant_id):
        if tenant_id == "t-bad":
            raise RuntimeError("transient")
        return None

    with patch("db.locations.list_all_tenants_for_backfill",
               new=AsyncMock(return_value=[_tenant(id="t-bad"), _tenant(id="t-good")])), \
         patch("db.locations.get_default_location", new=AsyncMock(side_effect=_get_default)), \
         patch("db.locations.get_binding", new=AsyncMock(return_value=None)), \
         patch("db.locations.insert_location", new=AsyncMock(return_value={"id": "loc"})), \
         patch("db.locations.insert_binding", new=AsyncMock()):
        summary = await bf.backfill_all(dry_run=False)

    assert summary["errors"] == 1
    assert summary["locations_created"] == 1


@pytest.mark.asyncio
async def test_tenant_without_id_is_skipped_not_crashed():
    mocks = _patch_db()
    with _apply(mocks):
        out = await bf.backfill_tenant({"business_name": "No id"}, dry_run=False)
    assert out["location"] == "skipped_no_id"
    mocks["insert_location"].assert_not_awaited()
