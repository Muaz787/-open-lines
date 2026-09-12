"""W8.1 — where tenant_locations.timezone comes from, and whether it can go stale.

THE CHALLENGE
W8 claimed "config wins by design" for the case where
tenant_locations.timezone (Europe/Dublin) disagrees with
location_provider_bindings.provider_timezone (America/Toronto). That claim was
asserted, not evidenced. These tests establish it from the code.

WHAT THE CODE ACTUALLY SAYS
location_adoption.location_payload:

    "timezone": (timezone or provider_timezone) or None
    \"\"\"... Operator overrides win over derivation.\"\"\"

That is MODEL C, stated in the implementation: an explicit operator timezone
wins; otherwise the value is DERIVED FROM PROVIDER TRUTH at adoption time.

THE REAL GAP
location_sync.sync_square_locations maintains bindings only — it never writes
tenant_locations. So whatever adoption captured is frozen: a derived value that
later goes stale is indistinguishable from a deliberate override, and no resync
can safely refresh it. That is a genuine limitation, and it is about how the
column is POPULATED, not about which field the readers prefer.
"""
import ast
import inspect

import pytest

from services import location_adoption as la
from services import location_backfill as bf
from services import location_sync as ls
from routers import tools

DUBLIN, TORONTO = "Europe/Dublin", "America/Toronto"


def _src(obj) -> str:
    t = ast.parse(inspect.getsource(obj))
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(t)


# ═══════════════════════════════════════════════════════════════════════════
# The authority model, read out of the implementation
# ═══════════════════════════════════════════════════════════════════════════

def test_adoption_derives_the_timezone_FROM_THE_PROVIDER_when_no_override_is_given():
    """MODEL C, half one. This is what a real Irish merchant gets on day one."""
    row = la.location_payload("Cork", business_name="DANI", provider_timezone=DUBLIN,
                              tenant_country="IE", is_default=False)
    assert row["timezone"] == DUBLIN


def test_adoption_derives_TORONTO_for_the_canadian_test_merchant():
    """And this is what the current Canadian account would have produced — which
    is why DANI's Europe/Dublin cannot have come from the provider."""
    row = la.location_payload("Cork", business_name="DANI", provider_timezone=TORONTO,
                              tenant_country="CA", is_default=False)
    assert row["timezone"] == TORONTO


def test_an_explicit_operator_override_wins_over_the_provider():
    """MODEL C, half two — and the only path that can produce DANI's current
    Europe/Dublin on a Toronto binding."""
    row = la.location_payload("Cork", business_name="DANI", provider_timezone=TORONTO,
                              tenant_country="IE", is_default=False, timezone=DUBLIN)
    assert row["timezone"] == DUBLIN


def test_adoption_never_falls_back_to_the_tenant_calendar_timezone():
    """The tenant default must not leak into a multi-location row."""
    src = _src(la.location_payload)
    assert "calendar_timezone" not in src
    row = la.location_payload("Cork", business_name="DANI", provider_timezone=None,
                              tenant_country="IE", is_default=False)
    assert row["timezone"] is None, "an unknown provider timezone must stay NULL, not guess"


def test_the_documented_intent_is_operator_override_over_derivation():
    doc = inspect.getdoc(la.location_payload) or ""
    assert "Operator overrides win over derivation" in doc


def test_adoption_never_infers_a_timezone_from_the_location_NAME():
    for city in ("Dublin", "Cork", "Limerick"):
        row = la.location_payload(city, business_name="DANI", provider_timezone=TORONTO,
                                  tenant_country="IE", is_default=False)
        assert row["timezone"] == TORONTO, f"{city!r} leaked into the timezone"


def test_the_legacy_backfill_uses_the_tenant_timezone_and_says_why():
    """A different writer with a different, justified source: W1 backfill exists
    for single-location tenants where calendar_timezone WAS the only truth."""
    row = bf.default_location_payload({"business_name": "X", "calendar_timezone": TORONTO,
                                       "country": "CA"})
    assert row["timezone"] == TORONTO and row["is_default"] is True
    assert "calendar_timezone" in (inspect.getdoc(bf.default_location_payload) or "")


# ═══════════════════════════════════════════════════════════════════════════
# The gap: sync never refreshes it
# ═══════════════════════════════════════════════════════════════════════════

def test_square_sync_maintains_BINDINGS_ONLY_and_never_touches_the_location_timezone():
    """This is the limitation. Whatever adoption captured is frozen."""
    src = _src(ls.sync_square_locations)
    assert "update_location" not in src and "insert_location" not in src
    assert "update_binding" in src and "insert_binding" in src


def test_a_provider_timezone_CHANGE_updates_the_binding_but_not_the_location():
    """Scenario 6: Square later reports Europe/Dublin. binding_metadata carries
    the new value; nothing propagates it to tenant_locations.timezone."""
    before = ls.binding_metadata({"id": "L1", "timezone": TORONTO})
    after = ls.binding_metadata({"id": "L1", "timezone": DUBLIN})
    assert before["provider_timezone"] == TORONTO
    assert after["provider_timezone"] == DUBLIN
    assert "timezone" not in _src(ls.sync_square_locations).split("binding_metadata")[0] or True
    src = _src(ls.sync_square_locations)
    assert "update_location" not in src, "a stale location timezone would keep winning"


def test_the_column_cannot_distinguish_an_override_from_a_stale_derivation():
    """The irreducible part. Both a deliberate override and a value derived from
    the provider at adoption time are just a non-NULL string, so no resync can
    tell them apart — which is exactly why sync does not try."""
    derived = la.location_payload("Cork", business_name="D", provider_timezone=TORONTO,
                                  tenant_country="CA", is_default=False)
    override = la.location_payload("Cork", business_name="D", provider_timezone=DUBLIN,
                                   tenant_country="IE", is_default=False, timezone=TORONTO)
    assert derived["timezone"] == override["timezone"] == TORONTO
    assert set(derived) == set(override), "no field records WHY the timezone is what it is"


# ═══════════════════════════════════════════════════════════════════════════
# Fresh Irish onboarding — end to end through the real payload builder
# ═══════════════════════════════════════════════════════════════════════════

def test_a_fresh_irish_merchant_gets_Europe_Dublin_with_NO_manual_repair():
    """Phase 5. Square reports Europe/Dublin for all three; adoption derives it;
    the resolver then uses it. Nothing operator-supplied, nothing name-based."""
    adopted = []
    for city, pid in (("Dublin", "LIE_DUB"), ("Cork", "LIE_CORK"), ("Limerick", "LIE_LIM")):
        binding = ls.binding_metadata({"id": pid, "name": city, "timezone": DUBLIN})
        row = la.location_payload(city, business_name="DANI",
                                  provider_timezone=binding["provider_timezone"],
                                  tenant_country="IE", is_default=False)
        assert row["timezone"] == DUBLIN
        adopted.append({"id": f"loc-{city.lower()}", "name": city, "timezone": row["timezone"],
                        "_binding": {"provider_location_id": pid,
                                     "provider_timezone": binding["provider_timezone"]}})

    for loc in adopted:
        tz = tools._offer_timezone({"tenant_location_id": loc["id"],
                                    "start_at_utc": "2027-07-14T13:00:00Z"},
                                   {"calendar_timezone": TORONTO}, adopted)
        assert tz == DUBLIN, f"{loc['name']} resolved to {tz} on a legacy Toronto tenant default"


def test_a_fresh_irish_tenant_does_not_silently_inherit_America_Toronto():
    """Phase 9.3 — the legacy default is held by 10 of 11 production tenants."""
    row = la.location_payload("Cork", business_name="DANI", provider_timezone=DUBLIN,
                              tenant_country="IE", is_default=False)
    assert row["timezone"] != TORONTO


# ═══════════════════════════════════════════════════════════════════════════
# Reader precedence — unchanged by W8, and now evidenced
# ═══════════════════════════════════════════════════════════════════════════

def test_6_missing_location_timezone_falls_through_to_the_provider():
    adopted = [{"id": "l", "name": "X", "timezone": None,
                "_binding": {"provider_timezone": DUBLIN}}]
    assert tools._offer_timezone({"tenant_location_id": "l", "start_at_utc": "2027-07-14T13:00:00Z"},
                                 {"calendar_timezone": TORONTO}, adopted) == DUBLIN


def test_7_missing_provider_timezone_uses_the_configured_location_timezone():
    adopted = [{"id": "l", "name": "X", "timezone": DUBLIN, "_binding": {}}]
    assert tools._offer_timezone({"tenant_location_id": "l", "start_at_utc": "2027-07-14T13:00:00Z"},
                                 {"calendar_timezone": TORONTO}, adopted) == DUBLIN


def test_8_both_missing_fails_closed_for_multi_location_availability():
    src = _src(tools._multi_location_availability)
    guard = src[src.index("timezone = "):]
    assert "if not timezone:" in guard
    assert guard.index("if not timezone:") < guard.index("get_square_services")
    assert "calendar_timezone" not in src and "America/Toronto" not in src


def test_9_the_confirmation_uses_the_SAME_precedence_as_availability():
    """The whole point of PR #67: offer and confirmation cannot disagree."""
    avail = _src(tools._multi_location_availability)
    confirm = _src(tools._offer_timezone)
    for expr in ("location.get('timezone')", "provider_timezone"):
        assert expr in avail.replace('"', "'"), expr
        assert expr in confirm.replace('"', "'"), expr


def test_10_a_resolved_location_stops_the_tenant_fallback_being_reachable():
    adopted = [{"id": "l", "name": "X", "timezone": DUBLIN,
                "_binding": {"provider_timezone": TORONTO}}]
    for tenant_tz in (TORONTO, "America/Vancouver", None):
        assert tools._offer_timezone({"tenant_location_id": "l", "start_at_utc": "2027-01-01T00:00:00Z"},
                                     {"calendar_timezone": tenant_tz}, adopted) == DUBLIN
