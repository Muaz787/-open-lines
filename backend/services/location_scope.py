"""
W3 — which Square services and team members exist at which Square locations.

Pure functions. No HTTP, no database, no side effects: everything here maps a
Square payload to a scope triple, or answers a yes/no question about a cached row.

DARK IN W3. `service_is_available_at_location` and `staff_is_available_at_location`
are written for W4 and are deliberately NOT wired into the availability or booking
paths yet — those still see a tenant-flat cache and behave exactly as before.

SQUARE'S PRESENCE MODEL
-----------------------
Every CatalogObject carries:
    present_at_all_locations = true   -> present everywhere EXCEPT absent_at_location_ids
    present_at_all_locations = false  -> present ONLY at present_at_location_ids

The catch is that an appointment service has this on BOTH levels: the ITEM and the
ITEM_VARIATION. A variation is bookable at a location only where both are present,
so the effective scope is the intersection of two such rules. Resolving that once,
at sync time, is what stops every future consumer from having to get it right.

Identity is always the Square id. Names and addresses are never consulted here.
"""
from __future__ import annotations

# Square's own constant for "wherever this merchant trades, now and later".
ALL_CURRENT_AND_FUTURE = "ALL_CURRENT_AND_FUTURE_LOCATIONS"


def _presence(obj: dict, default_all: bool = True) -> tuple[bool, set[str], set[str]]:
    """(present_at_all, present_ids, absent_ids) for one CatalogObject.

    Defaults to all-locations when the field is absent, which matches both Square's
    own default for a new object and the behaviour every existing cached row has
    today.
    """
    present_all = obj.get("present_at_all_locations")
    if present_all is None:
        present_all = default_all
    return (
        bool(present_all),
        {str(i) for i in (obj.get("present_at_location_ids") or [])},
        {str(i) for i in (obj.get("absent_at_location_ids") or [])},
    )


def resolve_service_scope(item: dict, variation: dict) -> dict:
    """Intersect the item's presence with the variation's.

    Returns the triple stored on square_services:
        {present_at_all_locations, location_ids, absent_location_ids}

    The four cases:
      both all-locations      -> all-locations, exclusions merged
      item all, variation set -> the variation's ids, minus anything the item excludes
      item set, variation all -> the item's ids, minus anything the variation excludes
      both explicit           -> the intersection of the two id sets
    """
    i_all, i_present, i_absent = _presence(item)
    v_all, v_present, v_absent = _presence(variation)

    if i_all and v_all:
        return {"present_at_all_locations": True,
                "location_ids": [],
                "absent_location_ids": sorted(i_absent | v_absent)}
    if i_all and not v_all:
        return {"present_at_all_locations": False,
                "location_ids": sorted(v_present - i_absent),
                "absent_location_ids": []}
    if v_all and not i_all:
        return {"present_at_all_locations": False,
                "location_ids": sorted(i_present - v_absent),
                "absent_location_ids": []}
    return {"present_at_all_locations": False,
            "location_ids": sorted(i_present & v_present),
            "absent_location_ids": []}


def resolve_staff_scope(team_member: dict) -> dict:
    """Where a team member may be booked.

    ALL_CURRENT_AND_FUTURE_LOCATIONS is kept as a flag rather than expanded into
    today's location ids: the merchant said "wherever we trade", and materialising
    that would silently exclude a location they open next month.
    """
    assigned = team_member.get("assigned_locations") or {}
    assignment_type = assigned.get("assignment_type")
    if assignment_type == ALL_CURRENT_AND_FUTURE:
        return {"assigned_all_locations": True, "location_ids": []}
    if assignment_type:                       # EXPLICIT_LOCATIONS (or anything new)
        return {"assigned_all_locations": False,
                "location_ids": sorted({str(i) for i in (assigned.get("location_ids") or [])})}
    # No assignment block at all — treat as everywhere, matching how every cached
    # row behaves today. Narrowing on missing data would remove staff from rosters.
    return {"assigned_all_locations": True, "location_ids": []}


# ---------------------------------------------------------------------------
# W4 helpers — tested now, wired in later.
# ---------------------------------------------------------------------------

def service_is_available_at_location(service: dict, provider_location_id: str) -> bool:
    """Is this cached square_services row bookable at this Square location?"""
    if not provider_location_id:
        return False
    if service.get("present_at_all_locations", True):
        return provider_location_id not in (service.get("absent_location_ids") or [])
    return provider_location_id in (service.get("location_ids") or [])


def staff_is_available_at_location(staff: dict, provider_location_id: str) -> bool:
    """Is this cached square_staff row bookable at this Square location?"""
    if not provider_location_id:
        return False
    if staff.get("assigned_all_locations", True):
        return True
    return provider_location_id in (staff.get("location_ids") or [])


def services_at_location(services: list[dict], provider_location_id: str) -> list[dict]:
    return [s for s in services if service_is_available_at_location(s, provider_location_id)]


def staff_at_location(staff: list[dict], provider_location_id: str) -> list[dict]:
    return [s for s in staff if staff_is_available_at_location(s, provider_location_id)]
