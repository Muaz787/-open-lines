"""
W3 — location scope on the Square service and staff caches.

The subtle part is that Square carries presence on BOTH the catalog item and the
variation, so a variation is bookable only where both are present. Getting that
intersection wrong in either direction is a silent failure: too wide offers a
Dublin-only fitting to a Cork caller, too narrow makes a real service invisible.

Everything here is pure — no HTTP, no database. The helpers are written for W4 and
are deliberately not wired into the booking path yet; the last block asserts that.
"""
import inspect

import pytest

from services import location_scope as scope

CORK, DUBLIN, LIMERICK = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"


def _item(all_locations=True, present=None, absent=None):
    o = {"id": "ITEM1", "present_at_all_locations": all_locations}
    if present is not None:
        o["present_at_location_ids"] = present
    if absent is not None:
        o["absent_at_location_ids"] = absent
    return o


def _variation(all_locations=True, present=None, absent=None):
    v = {"id": "VAR1", "present_at_all_locations": all_locations}
    if present is not None:
        v["present_at_location_ids"] = present
    if absent is not None:
        v["absent_at_location_ids"] = absent
    return v


def _member(assignment_type="ALL_CURRENT_AND_FUTURE_LOCATIONS", ids=None):
    m = {"id": "TM1", "given_name": "Aoife"}
    if assignment_type:
        m["assigned_locations"] = {"assignment_type": assignment_type}
        if ids is not None:
            m["assigned_locations"]["location_ids"] = ids
    return m


# ── 1. present at all locations ──────────────────────────────────────────────

def test_service_present_everywhere():
    out = scope.resolve_service_scope(_item(), _variation())
    assert out == {"present_at_all_locations": True,
                   "location_ids": [], "absent_location_ids": []}


def test_all_locations_honours_exclusions_from_either_level():
    """'Everywhere except Dublin' must not become 'everywhere'. Dropping the
    exclusion would offer a service the merchant deliberately removed."""
    out = scope.resolve_service_scope(
        _item(True, absent=[DUBLIN]), _variation(True, absent=[LIMERICK]))
    assert out["present_at_all_locations"] is True
    assert out["absent_location_ids"] == sorted([DUBLIN, LIMERICK])


# ── 2 & 3. restricted services ───────────────────────────────────────────────

def test_service_restricted_to_cork_stores_only_cork():
    out = scope.resolve_service_scope(_item(False, present=[CORK]), _variation())
    assert out["present_at_all_locations"] is False
    assert out["location_ids"] == [CORK]


def test_service_available_cork_and_dublin_stores_both():
    out = scope.resolve_service_scope(
        _item(False, present=[CORK, DUBLIN]), _variation())
    assert sorted(out["location_ids"]) == sorted([CORK, DUBLIN])


def test_variation_narrows_an_all_locations_item():
    out = scope.resolve_service_scope(_item(True), _variation(False, present=[CORK]))
    assert out["location_ids"] == [CORK]


def test_effective_scope_is_the_intersection_not_the_union():
    """Item at Cork+Dublin, variation at Dublin+Limerick -> only Dublin."""
    out = scope.resolve_service_scope(
        _item(False, present=[CORK, DUBLIN]),
        _variation(False, present=[DUBLIN, LIMERICK]))
    assert out["location_ids"] == [DUBLIN]


def test_item_exclusion_removes_a_variation_location():
    out = scope.resolve_service_scope(
        _item(True, absent=[CORK]), _variation(False, present=[CORK, DUBLIN]))
    assert out["location_ids"] == [DUBLIN]


def test_disjoint_scopes_yield_no_locations():
    out = scope.resolve_service_scope(
        _item(False, present=[CORK]), _variation(False, present=[DUBLIN]))
    assert out["location_ids"] == []
    assert out["present_at_all_locations"] is False


def test_missing_presence_fields_default_to_everywhere():
    """An absent field must not be read as 'nowhere' — that would make real
    services vanish from every roster."""
    out = scope.resolve_service_scope({"id": "I"}, {"id": "V"})
    assert out["present_at_all_locations"] is True


def test_variation_without_presence_inherits_the_items_restriction():
    out = scope.resolve_service_scope(_item(False, present=[CORK]), {"id": "V"})
    assert out["location_ids"] == [CORK]


# ── 6 & 7. staff scope ───────────────────────────────────────────────────────

def test_staff_assigned_all_locations_is_a_flag_not_a_materialised_list():
    """Freezing today's ids would silently exclude a location opened next month."""
    out = scope.resolve_staff_scope(_member())
    assert out == {"assigned_all_locations": True, "location_ids": []}


def test_staff_restricted_to_one_location_stores_the_exact_id():
    out = scope.resolve_staff_scope(_member("EXPLICIT_LOCATIONS", [CORK]))
    assert out == {"assigned_all_locations": False, "location_ids": [CORK]}


def test_staff_assigned_to_several_locations():
    out = scope.resolve_staff_scope(_member("EXPLICIT_LOCATIONS", [CORK, DUBLIN]))
    assert out["assigned_all_locations"] is False
    assert out["location_ids"] == sorted([CORK, DUBLIN])


def test_staff_without_assignment_block_defaults_to_everywhere():
    out = scope.resolve_staff_scope({"id": "TM1"})
    assert out["assigned_all_locations"] is True


def test_unknown_assignment_type_is_treated_as_explicit_not_everywhere():
    """Fail closed on a value Square adds later: narrower is recoverable, wider
    silently offers staff at locations they were never assigned to."""
    out = scope.resolve_staff_scope(_member("SOME_FUTURE_TYPE", [CORK]))
    assert out["assigned_all_locations"] is False
    assert out["location_ids"] == [CORK]


# ── 9. identity ──────────────────────────────────────────────────────────────

def test_scope_never_reads_a_name_or_address():
    """Identity is the Square id. A payload whose names and addresses all differ
    must resolve identically to one where they match."""
    plain = scope.resolve_service_scope(_item(False, present=[CORK]), _variation())
    noisy_item = {**_item(False, present=[CORK]), "item_data": {"name": "Cork Only"},
                  "address": {"address_line_1": "1 Placeholder St", "country": "CA"}}
    noisy_var = {**_variation(), "item_variation_data": {"name": "Regular"}}
    assert scope.resolve_service_scope(noisy_item, noisy_var) == plain


def test_source_never_references_name_or_address():
    src = inspect.getsource(scope)
    body = src.split('"""', 2)[-1]
    for forbidden in ('"name"', "'name'", '"address"', "'address'"):
        assert forbidden not in body, f"location scope must not read {forbidden}"


# ── W4 helpers (tested now, wired later) ─────────────────────────────────────

@pytest.mark.parametrize("service, location, expected", [
    ({"present_at_all_locations": True, "absent_location_ids": []}, CORK, True),
    ({"present_at_all_locations": True, "absent_location_ids": [CORK]}, CORK, False),
    ({"present_at_all_locations": False, "location_ids": [CORK]}, CORK, True),
    ({"present_at_all_locations": False, "location_ids": [DUBLIN]}, CORK, False),
    ({"present_at_all_locations": False, "location_ids": []}, CORK, False),
    ({}, CORK, True),                                  # legacy row: everywhere
    ({"present_at_all_locations": True}, "", False),   # no location -> never true
])
def test_service_is_available_at_location(service, location, expected):
    assert scope.service_is_available_at_location(service, location) is expected


@pytest.mark.parametrize("staff, location, expected", [
    ({"assigned_all_locations": True, "location_ids": []}, CORK, True),
    ({"assigned_all_locations": False, "location_ids": [CORK]}, CORK, True),
    ({"assigned_all_locations": False, "location_ids": [DUBLIN]}, CORK, False),
    ({}, CORK, True),                                  # legacy row: everywhere
    ({"assigned_all_locations": True}, "", False),
])
def test_staff_is_available_at_location(staff, location, expected):
    assert scope.staff_is_available_at_location(staff, location) is expected


def test_filters_split_a_dani_style_roster_correctly():
    services = [
        {"name": "Debs Fitting", "present_at_all_locations": True, "absent_location_ids": []},
        {"name": "Cork Alterations", "present_at_all_locations": False, "location_ids": [CORK]},
        {"name": "Dublin VIP", "present_at_all_locations": False, "location_ids": [DUBLIN]},
    ]
    cork = [s["name"] for s in scope.services_at_location(services, CORK)]
    dublin = [s["name"] for s in scope.services_at_location(services, DUBLIN)]
    limerick = [s["name"] for s in scope.services_at_location(services, LIMERICK)]

    assert cork == ["Debs Fitting", "Cork Alterations"]
    assert dublin == ["Debs Fitting", "Dublin VIP"]
    assert limerick == ["Debs Fitting"]


def test_staff_filter_keeps_multi_location_members_in_both_rosters():
    staff = [
        {"display_name": "Aoife", "assigned_all_locations": False,
         "location_ids": [CORK, DUBLIN]},
        {"display_name": "Niamh", "assigned_all_locations": False, "location_ids": [CORK]},
    ]
    assert [s["display_name"] for s in scope.staff_at_location(staff, CORK)] == ["Aoife", "Niamh"]
    assert [s["display_name"] for s in scope.staff_at_location(staff, DUBLIN)] == ["Aoife"]


# ── 11, 12, 13. nothing existing changes ─────────────────────────────────────

def test_legacy_cached_rows_without_the_new_columns_behave_as_before():
    """Every row that existed before migration 013 has no scope keys at all. They
    must read as available everywhere, which is exactly today's behaviour."""
    legacy_service = {"square_variation_id": "V1", "name": "Haircut"}
    legacy_staff = {"square_team_member_id": "TM1", "display_name": "Sam"}
    for loc in (CORK, DUBLIN, LIMERICK):
        assert scope.service_is_available_at_location(legacy_service, loc) is True
        assert scope.staff_is_available_at_location(legacy_staff, loc) is True


def test_scope_module_is_pure_no_db_or_http():
    """W3 is metadata only. If this module ever imports db or httpx it has stopped
    being a resolver and started being a side effect."""
    src = inspect.getsource(scope)
    for forbidden in ("import httpx", "from db import", "import db",
                      "async def", "await "):
        assert forbidden not in src, f"location_scope must stay pure: found {forbidden!r}"


def test_helpers_are_not_wired_into_the_booking_path():
    """W3 must not change runtime behaviour. The availability and booking code is
    allowed to know nothing about location scope yet."""
    from routers import tools
    src = inspect.getsource(tools)
    assert "location_scope" not in src
    assert "service_is_available_at_location" not in src
    assert "staff_is_available_at_location" not in src
