"""
W2.5 — explicit adoption of discovered Square locations.

The safety rule under test is that the default location can only ever be the one
tenants.square_location_id names, while that pointer is still what runtime reads.
It is enforced by there being no way to express anything else — so the tests that
matter most are the ones proving the knob does not exist.

Two starting states, both real:
  A. W1-backfilled tenant with an existing default (DANI / main)
  B. tenant created after migration 012 with zero locations — every tenant
     onboarded from now on, since provision_tenant() makes no location row
"""
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from services import location_adoption as la
from services.location_sync import STATUS_MISSING

CORK, DUBLIN, LIMERICK = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"


def _tenant(square_location_id=CORK, business_name="DANI", country=None, **over):
    return {"id": "t-1", "business_name": business_name,
            "square_location_id": square_location_id, "country": country, **over}


def _binding(pid=CORK, name="Dani Cork", adopted=None, status="ACTIVE", tz="Europe/Dublin"):
    return {"id": f"b-{pid[-4:]}", "provider": "square", "provider_location_id": pid,
            "provider_location_name": name, "provider_status": status,
            "provider_timezone": tz, "tenant_location_id": adopted}


DEFAULT_MAIN = {"id": "loc-main", "name": "DANI", "slug": "main",
                "is_default": True, "booking_enabled": True, "active": True}


def _db(binding=None, default_location=None, by_slug=None, by_id=None, created=None):
    return {
        "get_binding": AsyncMock(return_value=binding),
        "get_default_location": AsyncMock(return_value=default_location),
        "get_location_by_slug": AsyncMock(return_value=by_slug),
        "get_location_by_id": AsyncMock(return_value=by_id),
        "insert_location": AsyncMock(return_value=created or {"id": "loc-new"}),
        "update_location": AsyncMock(return_value={}),
        "update_binding": AsyncMock(return_value={}),
        "delete_location": AsyncMock(return_value=None),
        "list_locations": AsyncMock(return_value=[]),
        "list_bindings": AsyncMock(return_value=[]),
    }


def _apply(mocks):
    return patch.multiple("db.locations", **mocks)


# ── the safety rule: the default is derived, never chosen ────────────────────

def test_no_api_exists_for_choosing_which_location_becomes_default():
    """Decision 1 is enforced structurally. If a parameter like into_default or
    make_default ever appears, an operator can point the default somewhere the
    legacy runtime pointer does not agree with."""
    params = set(inspect.signature(la.adopt_location).parameters)
    for forbidden in ("into_default", "make_default", "is_default", "as_default", "default"):
        assert forbidden not in params, f"adopt_location must not accept {forbidden!r}"


@pytest.mark.asyncio
async def test_non_legacy_location_never_becomes_default_even_with_no_default_present():
    """State B plus a non-legacy id: still must not seize the default slot."""
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin"), default_location=None)
    with _apply(mocks):
        out = await la.adopt_location(_tenant(square_location_id=CORK), DUBLIN)

    assert out["status"] == "adopted"
    assert mocks["insert_location"].await_args.args[1]["is_default"] is False


@pytest.mark.asyncio
async def test_adoption_never_writes_to_the_tenants_table():
    mocks = _db(binding=_binding(), default_location=DEFAULT_MAIN, by_id=DEFAULT_MAIN)
    with _apply(mocks), patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        await la.adopt_location(_tenant(), CORK)
    upd.assert_not_awaited()


# ── state A: existing W1 default is reshaped in place ────────────────────────

@pytest.mark.asyncio
async def test_state_a_adopt_into_default_reshapes_the_existing_row():
    mocks = _db(binding=_binding(), default_location=DEFAULT_MAIN)
    with _apply(mocks):
        out = await la.adopt_location(_tenant(), CORK)

    assert out["status"] == "adopted_into_default"
    assert out["tenant_location_id"] == "loc-main"
    mocks["insert_location"].assert_not_awaited()          # reshaped, not duplicated

    _, loc_id, update = mocks["update_location"].await_args.args
    assert loc_id == "loc-main"
    assert update["name"] == "Dani Cork"
    assert update["slug"] == "cork"
    assert update["timezone"] == "Europe/Dublin"
    assert "is_default" not in update                      # never demoted or re-promoted


@pytest.mark.asyncio
async def test_state_a_binds_the_matching_provider_location():
    mocks = _db(binding=_binding(), default_location=DEFAULT_MAIN)
    with _apply(mocks):
        await la.adopt_location(_tenant(), CORK)
    _, binding_id, update = mocks["update_binding"].await_args.args
    assert binding_id == "b-HD42"
    assert update == {"tenant_location_id": "loc-main"}


@pytest.mark.asyncio
async def test_state_a_warns_when_booking_enabled_flips_true_to_false():
    """W1 backfilled defaults bookable so existing tenants keep working. W2.5 sets
    false. Inert today, but it must be visible — not discovered in W4."""
    mocks = _db(binding=_binding(), default_location=DEFAULT_MAIN)
    with _apply(mocks):
        out = await la.adopt_location(_tenant(), CORK)

    assert "warning" in out and "W4" in out["warning"]
    assert mocks["update_location"].await_args.args[2]["booking_enabled"] is False


@pytest.mark.asyncio
async def test_a_non_legacy_location_cannot_reshape_the_default():
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin"), default_location=DEFAULT_MAIN)
    with _apply(mocks):
        out = await la.adopt_location(_tenant(square_location_id=CORK), DUBLIN)

    assert out["status"] == "adopted"
    mocks["update_location"].assert_not_awaited()          # default untouched
    assert mocks["insert_location"].await_args.args[1]["is_default"] is False


# ── state B: tenant created after migration 012, zero locations ──────────────

@pytest.mark.asyncio
async def test_state_b_first_adoption_of_the_legacy_location_creates_the_default():
    mocks = _db(binding=_binding(), default_location=None)
    with _apply(mocks):
        out = await la.adopt_location(_tenant(), CORK)

    assert out["status"] == "adopted_as_default"
    payload = mocks["insert_location"].await_args.args[1]
    assert payload["is_default"] is True
    assert payload["booking_enabled"] is False
    assert payload["active"] is True
    assert payload["name"] == "Dani Cork" and payload["slug"] == "cork"


@pytest.mark.asyncio
async def test_state_b_subsequent_adoptions_are_not_default():
    mocks = _db(binding=_binding(LIMERICK, "Dani Limerick"),
                default_location={"id": "loc-cork", "is_default": True})
    with _apply(mocks):
        out = await la.adopt_location(_tenant(), LIMERICK)

    assert out["status"] == "adopted"
    payload = mocks["insert_location"].await_args.args[1]
    assert payload["is_default"] is False
    assert payload["booking_enabled"] is False
    assert payload["active"] is True


# ── the DANI shape end to end ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dani_three_locations_produce_three_distinct_slugs():
    slugs = []
    for pid, pname, default in (
        (CORK, "Dani Cork", DEFAULT_MAIN),
        (DUBLIN, "Dani Dublin", DEFAULT_MAIN),
        (LIMERICK, "Dani Limerick", DEFAULT_MAIN),
    ):
        mocks = _db(binding=_binding(pid, pname), default_location=default)
        with _apply(mocks):
            await la.adopt_location(_tenant(square_location_id=CORK), pid)
        call = (mocks["update_location"].await_args or mocks["insert_location"].await_args)
        payload = call.args[2] if mocks["update_location"].await_args else call.args[1]
        slugs.append(payload["slug"])

    assert slugs == ["cork", "dublin", "limerick"]


def test_slug_strips_the_business_name_but_never_returns_empty():
    assert la.derive_slug("Dani Cork", "DANI") == "cork"
    assert la.derive_slug("DANI Cork Showroom", "DANI") == "cork"
    assert la.derive_slug("Dani", "DANI") == "dani"      # nothing left -> keep the name
    assert la.derive_slug("Cork", "") == "cork"


@pytest.mark.asyncio
async def test_operator_overrides_win_over_derivation():
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin"), default_location=DEFAULT_MAIN)
    with _apply(mocks):
        await la.adopt_location(_tenant(), DUBLIN, name="Dublin Showroom",
                                slug="dublin-city", aliases=["grafton street"],
                                timezone="Europe/Dublin")
    payload = mocks["insert_location"].await_args.args[1]
    assert payload["name"] == "Dublin Showroom"
    assert payload["slug"] == "dublin-city"
    assert payload["aliases"] == ["grafton street"]


@pytest.mark.asyncio
async def test_country_comes_from_the_tenant_never_the_provider_address():
    """The test fixtures carry Canadian placeholder addresses on locations named
    Cork. Deriving country from an address would stamp CA on an Irish showroom."""
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin"), default_location=DEFAULT_MAIN)
    with _apply(mocks):
        await la.adopt_location(_tenant(country="IE"), DUBLIN)
    assert mocks["insert_location"].await_args.args[1]["country"] == "IE"


# ── identity, idempotency, refusals ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_adopting_twice_is_a_no_op():
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin", adopted="loc-dub"),
                default_location=DEFAULT_MAIN, by_id={"id": "loc-dub", "name": "Dublin"})
    with _apply(mocks):
        out = await la.adopt_location(_tenant(), DUBLIN)

    assert out["status"] == "already_adopted"
    mocks["insert_location"].assert_not_awaited()
    mocks["update_location"].assert_not_awaited()


@pytest.mark.asyncio
async def test_identity_is_the_provider_id_not_the_name():
    """Two Square locations with the same name adopt to two locations."""
    for pid in (CORK, DUBLIN):
        mocks = _db(binding=_binding(pid, "Showroom"), default_location=DEFAULT_MAIN)
        with _apply(mocks):
            await la.adopt_location(_tenant(square_location_id="other"), pid)
        assert mocks["get_binding"].await_args.args[2] == pid


@pytest.mark.asyncio
async def test_undiscovered_location_cannot_be_adopted():
    mocks = _db(binding=None, default_location=DEFAULT_MAIN)
    with _apply(mocks), pytest.raises(la.AdoptionError) as e:
        await la.adopt_location(_tenant(), "L-UNKNOWN")
    assert e.value.code == "binding_not_found"


@pytest.mark.asyncio
async def test_missing_provider_location_cannot_be_adopted():
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin", status=STATUS_MISSING),
                default_location=DEFAULT_MAIN)
    with _apply(mocks), pytest.raises(la.AdoptionError) as e:
        await la.adopt_location(_tenant(), DUBLIN)
    assert e.value.code == "provider_location_missing"
    mocks["insert_location"].assert_not_awaited()


@pytest.mark.asyncio
async def test_inactive_provider_location_may_be_adopted_but_stays_non_bookable():
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin", status="INACTIVE"),
                default_location=DEFAULT_MAIN)
    with _apply(mocks):
        out = await la.adopt_location(_tenant(), DUBLIN)
    assert out["status"] == "adopted"
    assert mocks["insert_location"].await_args.args[1]["booking_enabled"] is False


@pytest.mark.asyncio
async def test_slug_conflict_is_refused_with_no_partial_write():
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin"), default_location=DEFAULT_MAIN,
                by_slug={"id": "loc-other", "slug": "dublin"})
    with _apply(mocks), pytest.raises(la.AdoptionError) as e:
        await la.adopt_location(_tenant(), DUBLIN)

    assert e.value.code == "slug_conflict"
    mocks["insert_location"].assert_not_awaited()
    mocks["update_binding"].assert_not_awaited()


@pytest.mark.asyncio
async def test_reshaping_the_default_ignores_its_own_slug_as_a_conflict():
    mocks = _db(binding=_binding(), default_location=DEFAULT_MAIN,
                by_slug={"id": "loc-main", "slug": "cork"})
    with _apply(mocks):
        out = await la.adopt_location(_tenant(), CORK)
    assert out["status"] == "adopted_into_default"


# ── compensating rollback ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failed_binding_update_rolls_the_new_location_back():
    """Two writes, no transaction. A crash between them would leave a location that
    looks adoptable but is bound to nothing."""
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin"), default_location=DEFAULT_MAIN)
    mocks["update_binding"] = AsyncMock(side_effect=RuntimeError("network"))
    with _apply(mocks), pytest.raises(la.AdoptionError) as e:
        await la.adopt_location(_tenant(), DUBLIN)

    assert e.value.code == "binding_update_failed"
    mocks["delete_location"].assert_awaited_once()
    assert mocks["delete_location"].await_args.args[1] == "loc-new"


@pytest.mark.asyncio
async def test_failed_rollback_is_reported_not_swallowed():
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin"), default_location=DEFAULT_MAIN)
    mocks["update_binding"] = AsyncMock(side_effect=RuntimeError("network"))
    mocks["delete_location"] = AsyncMock(side_effect=RuntimeError("also down"))
    with _apply(mocks), pytest.raises(la.AdoptionError) as e:
        await la.adopt_location(_tenant(), DUBLIN)
    assert e.value.code == "rollback_failed"


# ── dry run ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_writes_nothing_in_either_state():
    for default in (DEFAULT_MAIN, None):
        mocks = _db(binding=_binding(), default_location=default)
        with _apply(mocks):
            out = await la.adopt_location(_tenant(), CORK, dry_run=True)
        assert out["dry_run"] is True
        mocks["insert_location"].assert_not_awaited()
        mocks["update_location"].assert_not_awaited()
        mocks["update_binding"].assert_not_awaited()


# ── detach ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detach_unbinds_and_deactivates_but_never_deletes():
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin", adopted="loc-dub"),
                by_id={"id": "loc-dub", "is_default": False})
    with _apply(mocks):
        out = await la.detach_location(_tenant(), DUBLIN)

    assert out["status"] == "detached"
    assert mocks["update_binding"].await_args.args[2] == {"tenant_location_id": None}
    assert mocks["update_location"].await_args.args[2] == {"active": False}
    mocks["delete_location"].assert_not_awaited()


@pytest.mark.asyncio
async def test_default_location_cannot_be_detached():
    mocks = _db(binding=_binding(CORK, "Dani Cork", adopted="loc-main"),
                by_id={"id": "loc-main", "is_default": True})
    with _apply(mocks), pytest.raises(la.AdoptionError) as e:
        await la.detach_location(_tenant(), CORK)

    assert e.value.code == "cannot_detach_default"
    mocks["update_binding"].assert_not_awaited()


@pytest.mark.asyncio
async def test_detaching_an_unadopted_binding_is_a_no_op():
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin", adopted=None))
    with _apply(mocks):
        out = await la.detach_location(_tenant(), DUBLIN)
    assert out["status"] == "not_adopted"
    mocks["update_binding"].assert_not_awaited()


# ── review ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_review_marks_the_legacy_pointer_and_what_is_adoptable():
    mocks = _db()
    mocks["list_locations"] = AsyncMock(return_value=[DEFAULT_MAIN])
    mocks["list_bindings"] = AsyncMock(return_value=[
        _binding(CORK, "Dani Cork", adopted="loc-main"),
        _binding(DUBLIN, "Dani Dublin"),
        _binding(LIMERICK, "Dani Limerick", status=STATUS_MISSING),
    ])
    with _apply(mocks):
        out = await la.review(_tenant(square_location_id=CORK))

    by_pid = {d["provider_location_id"]: d for d in out["discovered"]}
    assert out["legacy_square_location_id"] == CORK
    assert out["has_default_location"] is True
    assert by_pid[CORK]["is_legacy_pointer"] is True and by_pid[CORK]["adopted"] is True
    assert by_pid[DUBLIN]["adoptable"] is True
    assert by_pid[LIMERICK]["adoptable"] is False       # MISSING


# ── Shahid regression ────────────────────────────────────────────────────────

SHAHID = {"id": "a85ba5cf-5c79-4044-8f39-06eaf9d158ff",
          "business_name": "Shahid Real Estate", "square_location_id": CORK}
SHAHID_LOC = {"id": "11dd04f8-8c83-4b39-acfe-8b718d9b7b24", "name": "Shahid Real Estate",
              "slug": "main", "is_default": True, "booking_enabled": True}


@pytest.mark.asyncio
async def test_shahid_adopting_dublin_does_not_touch_its_default_or_pointer():
    before = dict(SHAHID)
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin"), default_location=SHAHID_LOC)
    with _apply(mocks), patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        out = await la.adopt_location(SHAHID, DUBLIN)

    assert out["status"] == "adopted"
    mocks["update_location"].assert_not_awaited()      # "Shahid Real Estate" survives
    upd.assert_not_awaited()
    assert SHAHID == before


@pytest.mark.asyncio
async def test_shahid_is_never_adopted_implicitly():
    """Adoption only ever happens for the exact provider id an operator names."""
    mocks = _db(binding=_binding(DUBLIN, "Dani Dublin"), default_location=SHAHID_LOC)
    with _apply(mocks):
        await la.adopt_location(SHAHID, DUBLIN)
    assert mocks["insert_location"].await_count == 1
