"""
W4 — per-call location state, the legacy/multi cutover, and assistant context.

The cutover rule these tests pin down is TRANSITIONAL. When
tenants.square_location_id stops being authoritative, is_multi_location() and
everything that branches on it should be deleted, not extended. These tests exist
partly so that removal is a deliberate act rather than something nobody dares
touch — see the module docstring of services/call_location.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import call_location as cl

CORK_ID, DUBLIN_ID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K"


def _loc(slug, name, lid=None, active=True, bookable=True, tz="Europe/Dublin"):
    return {"id": lid or f"loc-{slug}", "slug": slug, "name": name,
            "active": active, "booking_enabled": bookable, "timezone": tz,
            "is_default": False, "aliases": []}


def _binding(loc_id, provider_location_id=CORK_ID, status="ACTIVE", tz="Europe/Dublin"):
    return {"id": f"b-{loc_id}", "tenant_location_id": loc_id, "provider": "square",
            "provider_location_id": provider_location_id, "provider_status": status,
            "provider_timezone": tz}


def _state(**over):
    return {"vapi_call_id": "call-1", "tenant_id": "t-1", "active_location_id": None,
            "initial_location_id": None, "switch_count": 0,
            "location_source": cl.SOURCE_UNKNOWN, **over}


# ── binding health ───────────────────────────────────────────────────────────

def test_binding_health_rules():
    assert cl.binding_is_usable(_binding("l1")) is True
    assert cl.binding_is_usable(None) is False
    assert cl.binding_is_usable(_binding("l1", status="MISSING")) is False
    assert cl.binding_is_usable(_binding("l1", provider_location_id="")) is False
    assert cl.binding_is_usable(_binding("l1", provider_location_id="   ")) is False


# ── the cutover rule ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_location_tenant_is_legacy():
    """Every production tenant today. W4 must be invisible to them."""
    with patch("db.locations.list_locations", new=AsyncMock(return_value=[_loc("main", "Acme")])), \
         patch("db.locations.list_bindings", new=AsyncMock(return_value=[_binding("loc-main")])):
        multi, adopted = await cl.is_multi_location("t-1")
    assert multi is False and len(adopted) == 1


@pytest.mark.asyncio
async def test_two_adopted_locations_is_multi():
    locs = [_loc("cork", "Cork"), _loc("dublin", "Dublin")]
    binds = [_binding("loc-cork", CORK_ID), _binding("loc-dublin", DUBLIN_ID)]
    with patch("db.locations.list_locations", new=AsyncMock(return_value=locs)), \
         patch("db.locations.list_bindings", new=AsyncMock(return_value=binds)):
        multi, adopted = await cl.is_multi_location("t-1")
    assert multi is True and len(adopted) == 2


@pytest.mark.asyncio
async def test_unadopted_locations_do_not_make_a_tenant_multi_location():
    """A discovered-but-unmapped Square location is not a business location, so it
    must not tip a single-location tenant into the new path."""
    locs = [_loc("main", "Acme"), _loc("other", "Other")]
    with patch("db.locations.list_locations", new=AsyncMock(return_value=locs)), \
         patch("db.locations.list_bindings", new=AsyncMock(return_value=[_binding("loc-main")])):
        multi, adopted = await cl.is_multi_location("t-1")
    assert multi is False and len(adopted) == 1


@pytest.mark.asyncio
async def test_a_missing_binding_does_not_count_as_adopted():
    locs = [_loc("cork", "Cork"), _loc("dublin", "Dublin")]
    binds = [_binding("loc-cork", CORK_ID),
             _binding("loc-dublin", DUBLIN_ID, status="MISSING")]
    with patch("db.locations.list_locations", new=AsyncMock(return_value=locs)), \
         patch("db.locations.list_bindings", new=AsyncMock(return_value=binds)):
        multi, adopted = await cl.is_multi_location("t-1")
    assert multi is False


def test_only_bookable_locations_are_eligible():
    """A location the operator has not activated is not offered to a caller — and
    is not a clarification candidate either."""
    adopted = [_loc("cork", "Cork"), _loc("dublin", "Dublin", bookable=False)]
    assert [l["slug"] for l in cl.eligible_for_availability(adopted)] == ["cork"]


def test_cutover_is_documented_as_transitional():
    """Guards against the temporary rule quietly becoming permanent."""
    doc = cl.__doc__ or ""
    assert "RETIREMENT" in doc and "transitional" in doc.lower()


# ── state lifecycle ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_state_is_created_lazily_and_reused():
    created = _state()
    with patch("db.locations.get_call_state", new=AsyncMock(side_effect=[None, created])), \
         patch("db.locations.insert_call_state", new=AsyncMock(return_value=created)) as ins:
        first = await cl.get_or_create("call-1", "t-1")
    assert first["vapi_call_id"] == "call-1"
    ins.assert_awaited_once()

    with patch("db.locations.get_call_state", new=AsyncMock(return_value=created)), \
         patch("db.locations.insert_call_state", new=AsyncMock()) as ins2:
        again = await cl.get_or_create("call-1", "t-1")
    assert again["vapi_call_id"] == "call-1"
    ins2.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_creation_yields_one_row():
    """Two tool calls can land in the same turn. The primary key settles it and the
    loser reads the winner's row rather than erroring."""
    winner = _state()
    with patch("db.locations.get_call_state", new=AsyncMock(side_effect=[None, winner])), \
         patch("db.locations.insert_call_state",
               new=AsyncMock(side_effect=Exception("duplicate key"))):
        out = await cl.get_or_create("call-1", "t-1")
    assert out == winner


@pytest.mark.asyncio
async def test_no_call_id_creates_no_anonymous_state():
    with patch("db.locations.insert_call_state", new=AsyncMock()) as ins:
        assert await cl.get_or_create("", "t-1") is None
        assert await cl.get_or_create("call-1", "") is None
    ins.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_call_belonging_to_another_tenant_is_refused():
    """Cross-tenant isolation: a call id is owned by exactly one tenant."""
    with patch("db.locations.get_call_state",
               new=AsyncMock(return_value=_state(tenant_id="t-OTHER"))):
        assert await cl.get_or_create("call-1", "t-1") is None


@pytest.mark.asyncio
async def test_end_of_call_cleanup_never_raises():
    with patch("db.locations.delete_call_state",
               new=AsyncMock(side_effect=RuntimeError("db down"))):
        await cl.clear("call-1")          # must not raise


@pytest.mark.asyncio
async def test_ttl_purge_is_safe_and_reports_zero_on_failure():
    with patch("db.locations.purge_expired_call_state", new=AsyncMock(return_value=4)):
        assert await cl.purge_expired() == 4
    with patch("db.locations.purge_expired_call_state",
               new=AsyncMock(side_effect=RuntimeError("boom"))):
        assert await cl.purge_expired() == 0


@pytest.mark.asyncio
async def test_ttl_purge_is_wired_into_the_existing_retention_sweep():
    """Reuses the daily cron rather than adding a scheduler."""
    from services import retention
    import inspect
    src = inspect.getsource(retention.run_retention)
    assert "call_location" in src and "purge_expired" in src


# ── switching ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_switch_count_moves_only_on_a_real_change():
    cork, dublin = _loc("cork", "Cork"), _loc("dublin", "Dublin")
    with patch("db.locations.update_call_state", new=AsyncMock()) as upd:
        s = await cl.set_active_location(_state(), cork, cl.SOURCE_CALLER)
        assert s["active_location_id"] == "loc-cork"
        assert "switch_count" not in upd.await_args.args[2]     # first selection
        assert upd.await_args.args[2]["initial_location_id"] == "loc-cork"

        s2 = await cl.set_active_location(s, dublin, cl.SOURCE_CALLER)
        assert s2["active_location_id"] == "loc-dublin"
        assert upd.await_args.args[2]["switch_count"] == 1

        before = upd.await_count
        s3 = await cl.set_active_location(s2, dublin, cl.SOURCE_CALLER)
        assert s3["active_location_id"] == "loc-dublin"
        assert upd.await_count == before                        # no-op re-selection


@pytest.mark.asyncio
async def test_initial_location_is_recorded_once():
    cork, dublin = _loc("cork", "Cork"), _loc("dublin", "Dublin")
    with patch("db.locations.update_call_state", new=AsyncMock()) as upd:
        s = await cl.set_active_location(_state(), cork, cl.SOURCE_CALLER)
        await cl.set_active_location(s, dublin, cl.SOURCE_CALLER)
    assert "initial_location_id" not in upd.await_args.args[2]  # not overwritten


# ── precedence ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_explicit_argument_wins_and_switches():
    cork, dublin = _loc("cork", "Cork"), _loc("dublin", "Dublin")
    state = _state(active_location_id="loc-cork")
    with patch("db.locations.update_call_state", new=AsyncMock()):
        loc, res, _ = await cl.resolve_active_location(state, "Dublin", [cork, dublin], "DANI")
    assert loc["slug"] == "dublin"


@pytest.mark.asyncio
async def test_existing_state_is_used_when_no_argument_given():
    cork, dublin = _loc("cork", "Cork"), _loc("dublin", "Dublin")
    loc, res, _ = await cl.resolve_active_location(
        _state(active_location_id="loc-cork"), "", [cork, dublin], "DANI")
    assert loc["slug"] == "cork" and res is None


@pytest.mark.asyncio
async def test_unresolved_when_nothing_established():
    cork, dublin = _loc("cork", "Cork"), _loc("dublin", "Dublin")
    loc, res, _ = await cl.resolve_active_location(_state(), "", [cork, dublin], "DANI")
    assert loc is None
    assert sorted(res.candidate_names()) == ["Cork", "Dublin"]


@pytest.mark.asyncio
async def test_an_invalid_explicit_location_does_not_destroy_good_state():
    """The caller mumbled. They did not un-choose Cork."""
    cork, dublin = _loc("cork", "Cork"), _loc("dublin", "Dublin")
    state = _state(active_location_id="loc-cork")
    with patch("db.locations.update_call_state", new=AsyncMock()) as upd:
        loc, res, out = await cl.resolve_active_location(state, "Galway", [cork, dublin], "DANI")
    assert loc is None                                   # no Square call this turn
    assert not res.ok
    assert out["active_location_id"] == "loc-cork"       # preserved
    upd.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_explicit_location_preserves_state_too():
    a, b = _loc("cork-city", "Cork City"), _loc("cork-park", "Cork Retail Park")
    state = _state(active_location_id="loc-cork-city")
    with patch("db.locations.update_call_state", new=AsyncMock()):
        loc, res, out = await cl.resolve_active_location(state, "Cork", [a, b], "DANI")
    assert loc is None and res.status == "ambiguous"
    assert out["active_location_id"] == "loc-cork-city"


@pytest.mark.asyncio
async def test_a_location_disabled_mid_call_fails_closed():
    """Was eligible when chosen, disabled since. Serving stale state would send a
    caller to somewhere the operator just switched off."""
    dublin = _loc("dublin", "Dublin")
    loc, res, _ = await cl.resolve_active_location(
        _state(active_location_id="loc-cork"), "", [dublin], "DANI")
    assert loc is None and not res.ok


@pytest.mark.asyncio
async def test_is_default_is_never_used_to_pick_a_location():
    """A multi-location tenant has no safe default — picking one is guessing which
    city the caller meant."""
    cork = _loc("cork", "Cork"); cork["is_default"] = True
    dublin = _loc("dublin", "Dublin")
    loc, res, _ = await cl.resolve_active_location(_state(), "", [cork, dublin], "DANI")
    assert loc is None


# ── assistant context ────────────────────────────────────────────────────────

def test_prompt_block_lists_names_and_no_identifiers():
    block = cl.build_location_prompt_block(["Cork", "Dublin", "Limerick"])
    assert "Cork" in block and "Dublin" in block and "Limerick" in block
    assert "Cork, Dublin or Limerick" in block
    for leaked in (CORK_ID, DUBLIN_ID, "loc-cork", "tenant_location", "provider_location_id",
                   "binding", "uuid"):
        assert leaked not in block, f"assistant context leaked {leaked!r}"


def test_prompt_block_forbids_guessing_and_allows_general_questions():
    block = cl.build_location_prompt_block(["Cork", "Dublin"])
    assert "NEVER guess" in block
    assert "do NOT require asking which" in block


def test_no_prompt_block_for_single_location_tenants():
    """Their prompt must be byte-identical to before W4."""
    assert cl.build_location_prompt_block(["Cork"]) == ""
    assert cl.build_location_prompt_block([]) == ""


@pytest.mark.asyncio
async def test_prompt_block_only_advertises_bookable_locations():
    locs = [_loc("cork", "Cork"), _loc("dublin", "Dublin"),
            _loc("limerick", "Limerick", bookable=False)]
    binds = [_binding("loc-cork", CORK_ID), _binding("loc-dublin", DUBLIN_ID),
             _binding("loc-limerick", "L9TTF8T2FBQE5")]
    with patch("db.locations.list_locations", new=AsyncMock(return_value=locs)), \
         patch("db.locations.list_bindings", new=AsyncMock(return_value=binds)):
        block = await cl.location_prompt_block_for({"id": "t-1", "business_name": "DANI"})
    assert "Cork" in block and "Dublin" in block
    assert "Limerick" not in block


@pytest.mark.asyncio
async def test_prompt_block_failure_never_breaks_prompt_building():
    with patch("db.locations.list_locations", new=AsyncMock(side_effect=RuntimeError("db"))):
        assert await cl.location_prompt_block_for({"id": "t-1"}) == ""
