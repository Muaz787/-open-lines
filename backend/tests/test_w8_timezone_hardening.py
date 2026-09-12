"""W8 — timezone correctness for a multi-location Irish tenant.

WHAT THE AUDIT FOUND
The architecture was already right where it matters. tenant_locations carries
its own `timezone`, _multi_location_availability resolves
`location.timezone -> binding.provider_timezone` and FAILS CLOSED with no tenant
fallback, and both check_availability and book_appointment return from the
multi-location branch before ever reaching their `calendar_timezone or
"America/Toronto"` default -- that default is legacy single-location only.

DANI's bindings genuinely report America/Toronto because the Square TEST merchant
is a Canadian account. That is provider truth and must stay provider truth;
business truth lives in tenant_locations.timezone, which is Europe/Dublin.

THE ONE GAP, which this fixes
_booked_message read `offer["_tz"]` -- a key nothing has ever written -- so the
spoken confirmation silently fell through to tenant.calendar_timezone. For DANI
that is Europe/Dublin and therefore correct by coincidence of configuration, not
by construction: a tenant whose locations span timezones would have been told its
confirmation in the wrong zone while the booking instant was right.

DST is exercised through the timezone library, never hardcoded offsets.
"""
import ast
import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from routers import tools

DUBLIN, TORONTO = "Europe/Dublin", "America/Toronto"
CORK_PID, DUB_PID, LIM_PID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"
WINTER = "2027-01-20"   # Europe/Dublin = UTC+0
SUMMER = "2027-07-14"   # Europe/Dublin = UTC+1


def _executable_source(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def location(lid, name, tz=DUBLIN, pid=CORK_PID, provider_tz=TORONTO):
    return {"id": lid, "name": name, "timezone": tz, "active": True,
            "booking_enabled": True,
            "_binding": {"provider_location_id": pid, "provider_timezone": provider_tz}}


DANI_ADOPTED = [location("loc-cork", "Cork", pid=CORK_PID),
                location("loc-dublin", "Dublin", pid=DUB_PID),
                location("loc-limerick", "Limerick", pid=LIM_PID)]

DANI_TENANT = {"id": "t-dani", "business_name": "DANI", "calendar_timezone": DUBLIN}


def offer(loc_id, start_utc, *, service="Dress Fitting"):
    return {"tenant_location_id": loc_id, "start_at_utc": start_utc,
            "service_name": service, "provider_location_id": CORK_PID}


# ═══════════════════════════════════════════════════════════════════════════
# The resolver's precedence — business truth beats provider truth
# ═══════════════════════════════════════════════════════════════════════════

def test_the_locations_own_timezone_wins_over_the_providers():
    """DANI's Square bindings really do say America/Toronto — the test merchant
    is Canadian. That is provider truth, and it must not decide what an Irish
    caller is told."""
    tz = tools._offer_timezone(offer("loc-cork", "2027-07-14T13:00:00Z"),
                               DANI_TENANT, DANI_ADOPTED)
    assert tz == DUBLIN, f"an Irish caller would have been answered in {tz}"


def test_the_provider_timezone_is_used_only_when_the_location_has_none():
    adopted = [location("loc-x", "X", tz=None, provider_tz=TORONTO)]
    assert tools._offer_timezone(offer("loc-x", "2027-07-14T13:00:00Z"),
                                 {"calendar_timezone": DUBLIN}, adopted) == TORONTO


def test_the_tenant_timezone_is_only_the_legacy_fallback():
    """No adopted location on the offer -> single-location legacy semantics."""
    assert tools._offer_timezone(offer("", "2027-07-14T13:00:00Z"),
                                 {"calendar_timezone": TORONTO}, []) == TORONTO
    assert tools._offer_timezone(offer("", "2027-07-14T13:00:00Z"), {}, None) == "UTC"


def test_an_unknown_location_id_does_not_silently_pick_another_location():
    tz = tools._offer_timezone(offer("loc-nonexistent", "2027-07-14T13:00:00Z"),
                               DANI_TENANT, DANI_ADOPTED)
    assert tz == DUBLIN, "fell back to the tenant value, not to a random location"


def test_provider_LIST_ORDER_cannot_influence_the_timezone():
    import itertools
    answers = {tools._offer_timezone(offer("loc-dublin", "2027-07-14T13:00:00Z"),
                                     DANI_TENANT, list(order))
               for order in itertools.permutations(DANI_ADOPTED)}
    assert answers == {DUBLIN}


# ═══════════════════════════════════════════════════════════════════════════
# DST — via the library, never hardcoded offsets
# ═══════════════════════════════════════════════════════════════════════════

def test_A_B_dublin_local_2pm_maps_to_the_right_UTC_in_both_seasons():
    winter = datetime(2027, 1, 20, 14, 0, tzinfo=ZoneInfo(DUBLIN))
    summer = datetime(2027, 7, 14, 14, 0, tzinfo=ZoneInfo(DUBLIN))
    assert winter.utcoffset().total_seconds() == 0, "Dublin is UTC+0 in January"
    assert summer.utcoffset().total_seconds() == 3600, "Dublin is UTC+1 in July"
    assert winter.astimezone(ZoneInfo("UTC")).hour == 14
    assert summer.astimezone(ZoneInfo("UTC")).hour == 13


def test_C_D_a_provider_UTC_slot_displays_correctly_in_both_seasons():
    for utc, expected_hour, season in (("2027-01-20T14:00:00Z", 14, "winter"),
                                       ("2027-07-14T13:00:00Z", 14, "summer")):
        tz = tools._offer_timezone(offer("loc-cork", utc), DANI_TENANT, DANI_ADOPTED)
        local = datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(ZoneInfo(tz))
        assert local.hour == expected_hour, f"{season}: {utc} displayed as {local}"


def test_E_the_same_UTC_instant_never_moves():
    """Slot identity is the UTC instant. Reading it in another zone changes the
    wall clock, never the instant."""
    utc = "2027-07-14T13:00:00Z"
    instant = datetime.fromisoformat(utc.replace("Z", "+00:00"))
    for tz in (DUBLIN, TORONTO, "UTC", "Australia/Sydney"):
        assert instant.astimezone(ZoneInfo(tz)) == instant


def test_F_switching_Cork_to_Dublin_does_not_reinterpret_under_Toronto():
    utc = "2027-07-14T13:00:00Z"
    cork = tools._offer_timezone(offer("loc-cork", utc), DANI_TENANT, DANI_ADOPTED)
    dub = tools._offer_timezone(offer("loc-dublin", utc), DANI_TENANT, DANI_ADOPTED)
    assert cork == dub == DUBLIN
    a = datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(ZoneInfo(cork))
    b = datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(ZoneInfo(dub))
    assert a == b and a.hour == 14


def test_G_the_ambiguous_fall_back_hour_is_explicit_not_accidental():
    """Europe/Dublin repeats 01:00-02:00 on 2027-10-31. Python resolves it with
    fold=0/1; both map to real, DIFFERENT instants an hour apart. We never rely
    on a local wall clock as identity, which is why this is safe."""
    early = datetime(2027, 10, 31, 1, 30, tzinfo=ZoneInfo(DUBLIN), fold=0)
    late = datetime(2027, 10, 31, 1, 30, tzinfo=ZoneInfo(DUBLIN), fold=1)
    assert early.utcoffset() != late.utcoffset()
    assert (late.astimezone(ZoneInfo("UTC")) - early.astimezone(ZoneInfo("UTC"))).seconds == 3600


def test_H_a_nonexistent_spring_forward_time_is_never_silently_a_real_slot():
    """01:00-02:00 does not exist on 2027-03-28. The system never constructs a
    slot from a local wall clock -- every offered slot is a UTC instant Square
    returned -- so a nonexistent local time cannot become a bookable one."""
    ghost = datetime(2027, 3, 28, 1, 30, tzinfo=ZoneInfo(DUBLIN))
    assert ghost.astimezone(ZoneInfo("UTC")).hour in (0, 1)
    src = _executable_source(tools._multi_location_book)
    assert "start_at_utc" in src
    assert "datetime(" not in src, "the booking path must not build a local wall clock"


# ═══════════════════════════════════════════════════════════════════════════
# Toronto regression — existing Canadian tenants
# ═══════════════════════════════════════════════════════════════════════════

def test_toronto_tenant_behaviour_is_unchanged_in_both_seasons():
    adopted = [location("loc-to", "Toronto", tz=TORONTO, provider_tz=TORONTO)]
    tenant = {"id": "t-ca", "calendar_timezone": TORONTO}
    for utc, expected in (("2027-01-20T15:00:00Z", 10), ("2027-07-14T14:00:00Z", 10)):
        tz = tools._offer_timezone(offer("loc-to", utc), tenant, adopted)
        assert tz == TORONTO
        local = datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(ZoneInfo(tz))
        assert local.hour == expected, f"{utc} -> {local}"


def test_when_provider_and_business_timezones_AGREE_nothing_changes():
    adopted = [location("loc-to", "Toronto", tz=TORONTO, provider_tz=TORONTO)]
    assert tools._offer_timezone(offer("loc-to", "2027-01-20T15:00:00Z"),
                                 {"calendar_timezone": TORONTO}, adopted) == TORONTO


def test_a_legacy_single_location_tenant_still_uses_its_tenant_timezone():
    assert tools._offer_timezone({"start_at_utc": "2027-01-20T15:00:00Z"},
                                 {"calendar_timezone": TORONTO}, None) == TORONTO


# ═══════════════════════════════════════════════════════════════════════════
# Static invariants
# ═══════════════════════════════════════════════════════════════════════════

def test_the_multi_location_availability_path_has_NO_toronto_fallback():
    src = _executable_source(tools._multi_location_availability)
    assert "America/Toronto" not in src
    assert "calendar_timezone" not in src, "availability must not fall back to the tenant"
    assert "location.get('timezone')" in src.replace('"', "'")


def test_availability_and_booking_return_before_the_legacy_toronto_default():
    """The `calendar_timezone or "America/Toronto"` lines are legacy
    single-location only, and a multi-location tenant returns before them."""
    for fn, delegate in ((tools.check_availability, "_multi_location_availability"),
                         (tools.book_appointment, "_multi_location_book")):
        src = _executable_source(fn)
        assert delegate in src
        assert src.index(delegate) < src.index("America/Toronto"), \
            f"{fn.__name__} can reach the Toronto default before delegating"


def test_the_booking_confirmation_no_longer_reads_a_key_nothing_writes():
    src = _executable_source(tools._booked_message)
    assert "_offer_timezone(" in src
    assert 'offer.get("_tz") or tenant.get("calendar_timezone")' not in src


def test_the_LLM_cannot_supply_a_timezone():
    """No tool argument is ever read as an IANA zone."""
    for fn in (tools.check_availability, tools.book_appointment,
               tools._multi_location_availability, tools._multi_location_book):
        src = _executable_source(fn)
        assert 'args.get("timezone")' not in src and "args.get('timezone')" not in src
        assert 'args.get("tz")' not in src and "args.get('tz')" not in src


def test_timezone_conversion_is_not_scattered_through_the_booking_path():
    """The booked confirmation converts in exactly one place."""
    src = _executable_source(tools._booked_message)
    assert src.count("astimezone") == 1


def test_no_provider_mutation_or_credential_path_was_touched():
    src = _executable_source(tools._offer_timezone)
    for forbidden in ("create_booking", "cancel_booking", "update_tenant",
                      "square_access_token", "encrypt"):
        assert forbidden not in src


def test_W7_family_untouched():
    from services import square_catalog_routing as w7e
    from services import square_webhook_identity as ident
    from db import supabase_transport
    assert ".limit(1)" not in _executable_source(w7e)
    assert "load_location_candidates" in _executable_source(ident)
    assert "http2" in inspect.getsource(supabase_transport.http2_enabled)


def test_the_deposit_and_credential_guards_are_intact():
    from routers import square_connect as sc
    assert "observed_merchant_id" in _executable_source(sc.callback)
    assert "_resolve_square_deposit_location" in _executable_source(tools._create_and_send_deposit)


# ═══════════════════════════════════════════════════════════════════════════
# The real confirmation message — where the gap actually was
# ═══════════════════════════════════════════════════════════════════════════

MULTI_TZ = [{"id": "l-dub", "name": "Dublin", "timezone": DUBLIN, "_binding": {}},
            {"id": "l-nyc", "name": "New York", "timezone": "America/New_York", "_binding": {}}]


def test_the_spoken_confirmation_uses_the_LOCATIONS_timezone():
    """A genuinely multi-timezone tenant. Before the fix both confirmations were
    spoken in the tenant's zone, so the New York caller was told 6 PM for a 1 PM
    appointment while the booking instant itself was correct."""
    utc = "2027-07-14T17:00:00Z"
    tenant = {"calendar_timezone": DUBLIN}
    dub = tools._booked_message({"tenant_location_id": "l-dub", "start_at_utc": utc,
                                 "service_name": "Fitting"}, tenant,
                                pending=False, adopted=MULTI_TZ)
    nyc = tools._booked_message({"tenant_location_id": "l-nyc", "start_at_utc": utc,
                                 "service_name": "Fitting"}, tenant,
                                pending=False, adopted=MULTI_TZ)
    assert "6:00 PM" in dub or "6:00 pm" in dub.lower(), dub
    assert "1:00 PM" in nyc or "1:00 pm" in nyc.lower(), nyc
    assert dub != nyc, "both locations were spoken in the same timezone"


def test_the_DANI_confirmation_is_spoken_in_Irish_time_in_both_seasons():
    for utc, expected in (("2027-01-20T14:00:00Z", "2:00"), ("2027-07-14T13:00:00Z", "2:00")):
        msg = tools._booked_message(offer("loc-cork", utc), DANI_TENANT,
                                    pending=False, adopted=DANI_ADOPTED)
        assert expected in msg, f"{utc} produced {msg!r}"


def test_a_legacy_single_location_confirmation_is_unchanged():
    msg = tools._booked_message({"start_at_utc": "2027-01-20T15:00:00Z",
                                 "service_name": "Cut"},
                                {"calendar_timezone": TORONTO}, pending=False)
    assert "10:00" in msg, msg
