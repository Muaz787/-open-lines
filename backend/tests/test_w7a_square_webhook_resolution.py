"""
W7A — routing a Square webhook to ONE tenant location, or to none.

THE BUG THIS EXISTS TO END
get_tenant_by_square_merchant_id() selects with `.limit(1)` and no ORDER BY, and
its two callers then mutate whatever tenant came back. On a merchant mapping to
more than one tenant that is a coin toss with side effects: a catalog event
overwrites an unrelated tenant's service cache, a booking event writes an
appointment onto the wrong business.

So the tests that matter most here are the ones where NOTHING is returned. An
ambiguous location must produce a refusal, not a winner, and no amount of
reordering the inputs may turn a refusal into a choice.

Production already contains the ambiguity: one Square location carries two
bindings owned by two tenants. It is survivable today only because one of those
tenants has appointments switched off. Both of those situations are pinned below
as synthetic fixtures -- the production rows are never touched.
"""
import itertools
import random

import pytest

from services import square_webhook_resolution as r

MERCHANT = "ML66K1YVCD1P0"
CORK_PID, DUBLIN_PID, LIMERICK_PID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"
DANI, SHAHID, THIRD = "tenant-dani", "tenant-shahid", "tenant-third"


def tenant(tid, *, appts=True, merchant=MERCHANT):
    return {"id": tid, "business_name": tid, "square_appointments_enabled": appts,
            "square_merchant_id": merchant}


def location(lid, tid, *, active=True, bookable=True, name="Cork"):
    return {"id": lid, "tenant_id": tid, "name": name,
            "active": active, "booking_enabled": bookable}


def binding(bid, tid, lid, pid, *, status="ACTIVE", provider="square"):
    return {"id": bid, "tenant_id": tid, "tenant_location_id": lid,
            "provider": provider, "provider_location_id": pid,
            "provider_status": status}


def candidate(*, bid="b1", tid=DANI, lid="loc-cork", pid=CORK_PID, status="ACTIVE",
              provider="square", appts=True, active=True, bookable=True,
              merchant=MERCHANT, drop_location=False, drop_tenant=False,
              binding_tenant=None):
    return {
        "binding": binding(bid, binding_tenant or tid, lid, pid,
                           status=status, provider=provider),
        "location": None if drop_location else location(lid, tid, active=active,
                                                        bookable=bookable),
        "tenant": None if drop_tenant else tenant(tid, appts=appts, merchant=merchant),
    }


def resolve(**kw):
    kw.setdefault("merchant_id", MERCHANT)
    kw.setdefault("merchant_candidates", [tenant(DANI)])
    kw.setdefault("provider_location_id", CORK_PID)
    kw.setdefault("location_bindings", [candidate()])
    return r.resolve_square_tenant_location(**kw)


# ═══════════════════════════════════════════════════════════════════════════
# The happy path, and what it is allowed to say
# ═══════════════════════════════════════════════════════════════════════════

def test_one_merchant_one_tenant_one_location_resolves():
    res = resolve()
    assert res.outcome == r.RESOLVED
    assert res.ok and res.may_mutate
    assert res.tenant_id == DANI
    assert res.tenant_location_id == "loc-cork"
    assert res.provider_location_id == CORK_PID
    assert res.binding_id == "b1"
    assert res.eligible_count == 1


def test_one_merchant_one_tenant_three_locations_resolves_the_named_one():
    """Only the bindings for the event's location are ever passed in; the other
    two exist but are a different query. Routing must be by location, not by
    'this tenant has locations'."""
    for pid, lid, nm in ((CORK_PID, "loc-cork", "Cork"),
                         (DUBLIN_PID, "loc-dublin", "Dublin"),
                         (LIMERICK_PID, "loc-limerick", "Limerick")):
        res = resolve(provider_location_id=pid,
                      location_bindings=[candidate(bid=f"b-{nm}", lid=lid, pid=pid)])
        assert res.outcome == r.RESOLVED
        assert res.tenant_location_id == lid
        assert res.provider_location_id == pid


def test_two_tenants_distinct_locations_each_resolve_independently():
    dani = resolve(provider_location_id=CORK_PID,
                   merchant_candidates=[tenant(DANI), tenant(SHAHID)],
                   location_bindings=[candidate(tid=DANI, lid="loc-cork", pid=CORK_PID)])
    shahid = resolve(provider_location_id=DUBLIN_PID,
                     merchant_candidates=[tenant(DANI), tenant(SHAHID)],
                     location_bindings=[candidate(bid="b2", tid=SHAHID,
                                                  lid="loc-sh", pid=DUBLIN_PID)])
    assert (dani.outcome, dani.tenant_id) == (r.RESOLVED, DANI)
    assert (shahid.outcome, shahid.tenant_id) == (r.RESOLVED, SHAHID)


# ═══════════════════════════════════════════════════════════════════════════
# §7 — the production topology, synthetically
# ═══════════════════════════════════════════════════════════════════════════

def test_production_topology_today_only_dani_is_eligible():
    """Shahid + DANI both bind L0Q8GTAZCHD42. Shahid has appointments OFF and a
    NULL provider_status, so exactly one binding survives eligibility."""
    res = resolve(
        merchant_candidates=[tenant(SHAHID)],       # only Shahid records the merchant
        location_bindings=[
            candidate(bid="b-shahid", tid=SHAHID, lid="loc-shahid", pid=CORK_PID,
                      status=None, appts=False),
            candidate(bid="b-dani", tid=DANI, lid="loc-cork", pid=CORK_PID,
                      status="ACTIVE", appts=True, merchant=None),
        ])
    # DANI is the only eligible binding, but it does not claim the merchant that
    # DOES have local mappings -> the cross-check must fire.
    assert res.outcome == r.IDENTITY_CONFLICT
    assert res.eligible_count == 1


def test_production_topology_resolves_once_dani_records_the_merchant():
    res = resolve(
        merchant_candidates=[tenant(SHAHID), tenant(DANI)],
        location_bindings=[
            candidate(bid="b-shahid", tid=SHAHID, lid="loc-shahid", pid=CORK_PID,
                      status=None, appts=False),
            candidate(bid="b-dani", tid=DANI, lid="loc-cork", pid=CORK_PID),
        ])
    assert res.outcome == r.RESOLVED
    assert res.tenant_id == DANI


def test_if_both_bindings_were_eligible_it_is_ambiguous_not_a_choice():
    """The moment Shahid's binding is repaired (ACTIVE + appointments on) without
    the duplicate being cleaned, routing must refuse outright."""
    res = resolve(
        merchant_candidates=[tenant(SHAHID), tenant(DANI)],
        location_bindings=[
            candidate(bid="b-shahid", tid=SHAHID, lid="loc-shahid", pid=CORK_PID),
            candidate(bid="b-dani", tid=DANI, lid="loc-cork", pid=CORK_PID),
        ])
    assert res.outcome == r.AMBIGUOUS_BINDING
    assert res.eligible_count == 2
    assert not res.tenant_id and not res.tenant_location_id
    assert not res.may_mutate


# ═══════════════════════════════════════════════════════════════════════════
# §8 — strict provider status
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("status,eligible", [
    ("ACTIVE", True), ("active", True),
    ("INACTIVE", False), (None, False), ("", False),
    ("MISSING", False), ("PENDING", False), ("UNKNOWN", False),
])
def test_provider_status_is_strict(status, eligible):
    ok, why = r.binding_is_routing_eligible(candidate(status=status))
    assert ok is eligible, why


def test_w7_is_stricter_than_w6a2_and_does_not_change_it():
    """W6A2's binding_is_usable() accepts a NULL provider_status. W7 must not, and
    must not alter the shared helper to get there."""
    from services import call_location
    lax = {"provider_status": None, "provider_location_id": CORK_PID}
    assert call_location.binding_is_usable(lax) is True          # unchanged
    assert r.binding_is_routing_eligible(candidate(status=None))[0] is False


# ═══════════════════════════════════════════════════════════════════════════
# §9 — the eligibility matrix, table-driven
# ═══════════════════════════════════════════════════════════════════════════

ELIGIBILITY_CASES = [
    ("all good",                    dict(),                          True),
    ("provider_status NULL",        dict(status=None),               False),
    ("provider_status INACTIVE",    dict(status="INACTIVE"),         False),
    ("wrong provider",              dict(provider="google"),         False),
    ("tenant appointments off",     dict(appts=False),               False),
    ("location inactive",           dict(active=False),              False),
    ("location not bookable",       dict(bookable=False),            False),
    ("location row missing",        dict(drop_location=True),        False),
    ("tenant row missing",          dict(drop_tenant=True),          False),
    ("binding/location tenant mismatch", dict(binding_tenant=THIRD), False),
]


@pytest.mark.parametrize("label,kw,expected", ELIGIBILITY_CASES,
                         ids=[c[0] for c in ELIGIBILITY_CASES])
def test_eligibility_matrix(label, kw, expected):
    ok, why = r.binding_is_routing_eligible(candidate(**kw))
    assert ok is expected, f"{label}: {why}"
    if not expected:
        assert why, "a refusal must say why"


@pytest.mark.parametrize("label,kw,_e", ELIGIBILITY_CASES, ids=[c[0] for c in ELIGIBILITY_CASES])
def test_an_ineligible_sole_binding_is_inactive_not_unbound(label, kw, _e):
    res = resolve(location_bindings=[candidate(**kw)])
    if label == "all good":
        assert res.outcome == r.RESOLVED
    else:
        assert res.outcome == r.INACTIVE_BINDING
        assert res.candidate_count == 1 and res.eligible_count == 0
        assert res.detail


def test_zero_bindings_is_unbound_location():
    res = resolve(location_bindings=[])
    assert res.outcome == r.UNBOUND_LOCATION
    assert res.candidate_count == 0
    assert CORK_PID in res.detail


def test_missing_provider_location_is_unknown_location():
    for pid in ("", None, "   "):
        res = resolve(provider_location_id=pid)
        assert res.outcome == r.UNKNOWN_LOCATION
        assert not res.may_mutate


def test_unbound_inactive_and_unknown_are_three_distinct_answers():
    """They are different operator problems; collapsing them destroys the signal."""
    assert len({
        resolve(provider_location_id="").outcome,
        resolve(location_bindings=[]).outcome,
        resolve(location_bindings=[candidate(status=None)]).outcome,
    }) == 3


def test_right_merchant_but_wrong_location_does_not_resolve():
    res = resolve(provider_location_id=DUBLIN_PID, location_bindings=[])
    assert res.outcome == r.UNBOUND_LOCATION


# ═══════════════════════════════════════════════════════════════════════════
# §5 — merchant semantics
# ═══════════════════════════════════════════════════════════════════════════

def test_merchant_classification_distinguishes_absent_from_unmapped():
    assert r.classify_merchant("", []) == r.MERCHANT_ABSENT
    assert r.classify_merchant(None, []) == r.MERCHANT_ABSENT
    assert r.classify_merchant(MERCHANT, []) == r.MERCHANT_UNMAPPED
    assert r.classify_merchant(MERCHANT, [tenant(DANI)]) == r.MERCHANT_MAPPED


def test_empty_merchant_set_lets_the_location_resolve_transitionally():
    """DANI currently has square_merchant_id NULL. Requiring the cross-check
    would refuse every one of its events."""
    res = resolve(merchant_candidates=[])
    assert res.outcome == r.RESOLVED
    assert res.tenant_id == DANI
    assert res.merchant_status == r.MERCHANT_UNMAPPED


def test_absent_merchant_id_also_resolves_and_is_recorded_as_absent():
    res = resolve(merchant_id="", merchant_candidates=[])
    assert res.outcome == r.RESOLVED
    assert res.merchant_status == r.MERCHANT_ABSENT


def test_a_populated_merchant_set_is_a_mandatory_cross_check():
    res = resolve(merchant_candidates=[tenant(SHAHID)])   # DANI's binding wins
    assert res.outcome == r.IDENTITY_CONFLICT
    assert not res.may_mutate


def test_merchant_identity_is_not_meaningless_metadata():
    """The same location resolves or conflicts purely on the merchant mapping."""
    assert resolve(merchant_candidates=[]).outcome == r.RESOLVED
    assert resolve(merchant_candidates=[tenant(DANI)]).outcome == r.RESOLVED
    assert resolve(merchant_candidates=[tenant(SHAHID)]).outcome == r.IDENTITY_CONFLICT


def test_the_location_resolver_never_returns_unknown_merchant():
    """UNKNOWN_MERCHANT is reserved for the future catalog (merchant-only)
    resolver. An unreachable branch here would rot."""
    seen = set()
    for mc in ([], [tenant(DANI)], [tenant(SHAHID)]):
        for lb in ([], [candidate()], [candidate(status=None)],
                   [candidate(bid="a"), candidate(bid="b", tid=SHAHID, lid="l2")]):
            for pid in ("", CORK_PID):
                seen.add(resolve(merchant_candidates=mc, location_bindings=lb,
                                 provider_location_id=pid).outcome)
    assert r.UNKNOWN_MERCHANT not in seen
    assert seen <= {r.RESOLVED, r.UNKNOWN_LOCATION, r.UNBOUND_LOCATION,
                    r.INACTIVE_BINDING, r.AMBIGUOUS_BINDING, r.IDENTITY_CONFLICT}


# ═══════════════════════════════════════════════════════════════════════════
# §10 — security properties
# ═══════════════════════════════════════════════════════════════════════════

def test_row_order_cannot_change_the_resolved_identity():
    eligible = candidate(bid="b-dani", tid=DANI, lid="loc-cork", pid=CORK_PID)
    noise = [
        candidate(bid="b-off", tid=SHAHID, lid="loc-sh", pid=CORK_PID, appts=False),
        candidate(bid="b-null", tid=THIRD, lid="loc-3", pid=CORK_PID, status=None),
        candidate(bid="b-dead", tid=THIRD, lid="loc-4", pid=CORK_PID, active=False),
    ]
    outcomes = set()
    for perm in itertools.permutations([eligible] + noise):
        res = resolve(merchant_candidates=[tenant(DANI)], location_bindings=list(perm))
        outcomes.add((res.outcome, res.tenant_id, res.tenant_location_id, res.binding_id))
    assert outcomes == {(r.RESOLVED, DANI, "loc-cork", "b-dani")}


def test_row_order_cannot_turn_an_ambiguity_into_a_winner():
    both = [candidate(bid="b1", tid=DANI, lid="loc-cork", pid=CORK_PID),
            candidate(bid="b2", tid=SHAHID, lid="loc-sh", pid=CORK_PID)]
    for perm in itertools.permutations(both):
        res = resolve(merchant_candidates=[tenant(DANI), tenant(SHAHID)],
                      location_bindings=list(perm))
        assert res.outcome == r.AMBIGUOUS_BINDING
        assert not res.tenant_id


def test_shuffled_large_candidate_sets_are_stable():
    rng = random.Random(20260911)
    base = [candidate(bid="win", tid=DANI, lid="loc-cork", pid=CORK_PID)] + [
        candidate(bid=f"n{i}", tid=f"t{i}", lid=f"l{i}", pid=CORK_PID,
                  status=rng.choice([None, "INACTIVE", "MISSING"]))
        for i in range(12)]
    for _ in range(25):
        rng.shuffle(base)
        res = resolve(merchant_candidates=[tenant(DANI)], location_bindings=list(base))
        assert (res.outcome, res.tenant_id, res.binding_id) == (r.RESOLVED, DANI, "win")


def test_an_unrelated_merchant_candidate_cannot_redirect_a_location():
    res = resolve(merchant_candidates=[tenant(DANI), tenant(THIRD), tenant(SHAHID)])
    assert res.outcome == r.RESOLVED
    assert res.tenant_id == DANI          # the LOCATION decided, not the merchant list


def test_adding_a_second_eligible_binding_flips_resolved_to_ambiguous():
    one = resolve(merchant_candidates=[tenant(DANI), tenant(SHAHID)])
    assert one.outcome == r.RESOLVED
    two = resolve(merchant_candidates=[tenant(DANI), tenant(SHAHID)],
                  location_bindings=[candidate(),
                                     candidate(bid="b2", tid=SHAHID, lid="loc-sh")])
    assert two.outcome == r.AMBIGUOUS_BINDING


def test_removing_merchant_mappings_does_not_change_the_resolved_tenant():
    with_map = resolve(merchant_candidates=[tenant(DANI)])
    without = resolve(merchant_candidates=[])
    assert with_map.outcome == without.outcome == r.RESOLVED
    assert with_map.tenant_id == without.tenant_id == DANI
    assert with_map.tenant_location_id == without.tenant_location_id


def test_no_outcome_other_than_resolved_ever_names_a_tenant():
    for res in (resolve(provider_location_id=""),
                resolve(location_bindings=[]),
                resolve(location_bindings=[candidate(status=None)]),
                resolve(location_bindings=[candidate(), candidate(bid="b2", tid=SHAHID,
                                                                  lid="l2")]),
                resolve(merchant_candidates=[tenant(SHAHID)])):
        assert res.outcome != r.RESOLVED
        assert res.tenant_id == "" and res.tenant_location_id == ""
        assert not res.ok and not res.may_mutate
        assert res.outcome in r.FAIL_CLOSED


def test_may_mutate_is_true_only_for_a_complete_resolution():
    assert resolve().may_mutate is True
    incomplete = r.Resolution(r.RESOLVED, tenant_id=DANI)   # no location
    assert incomplete.ok is True and incomplete.may_mutate is False


# ═══════════════════════════════════════════════════════════════════════════
# §6 — identity must be credential-independent
# ═══════════════════════════════════════════════════════════════════════════

def test_the_resolver_never_touches_credentials_or_the_provider():
    import ast
    import inspect
    src = inspect.getsource(r)
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and \
               isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    code = ast.unparse(tree)
    # credentials, database access and provider I/O must all be absent
    for forbidden in ("get_access_token", "square_access_token", "square_refresh_token",
                      "httpx", "requests", "get_client", "supabase",
                      "connect.squareup.com", "await "):
        assert forbidden not in code, f"resolver must not reference {forbidden!r}"

    # and it must genuinely be synchronous/pure: no async defs at all
    assert not any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree))


def test_a_token_holding_tenant_is_not_preferred():
    """Two eligible bindings stay ambiguous even when only one tenant has a token."""
    rich = candidate(bid="b-rich", tid=DANI, lid="loc-cork", pid=CORK_PID)
    rich["tenant"]["square_access_token"] = "tok"
    poor = candidate(bid="b-poor", tid=SHAHID, lid="loc-sh", pid=CORK_PID)
    res = resolve(merchant_candidates=[tenant(DANI), tenant(SHAHID)],
                  location_bindings=[rich, poor])
    assert res.outcome == r.AMBIGUOUS_BINDING


def test_resolution_never_carries_a_credential():
    res = resolve()
    for slot in r.Resolution.__slots__:
        assert "token" not in slot and "secret" not in slot
        assert "token" not in str(getattr(res, slot)).lower()


# ═══════════════════════════════════════════════════════════════════════════
# §1 — the retrieval layer must not select
# ═══════════════════════════════════════════════════════════════════════════

def test_the_new_merchant_lookup_has_no_limit_and_no_ordering():
    import ast
    import inspect

    from db import square_routing

    src = inspect.getsource(square_routing.list_tenants_by_square_merchant_id)
    tree = ast.parse(src.lstrip())
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.body and \
           isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            n.body = n.body[1:]
    code = ast.unparse(tree)
    assert ".limit(" not in code
    assert ".single(" not in code
    assert ".order(" not in code
    assert "[0]" not in code


def test_the_old_unsafe_helper_still_exists_untouched():
    """W7A adds; it does not remove. The existing handlers still depend on it and
    are not being switched over until W7B/C/D."""
    import inspect

    import db.supabase as dbs

    src = inspect.getsource(dbs.get_tenant_by_square_merchant_id)
    assert ".limit(1)" in src


@pytest.mark.asyncio
async def test_merchant_lookup_returns_all_matches_not_one():
    from unittest.mock import patch

    from db import square_routing

    rows = [tenant(DANI), tenant(SHAHID), tenant(THIRD)]

    class _Q:
        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            return type("R", (), {"data": rows})()

    with patch("db.square_routing.get_client", return_value=type("C", (), {
            "table": lambda self, n: _Q()})()):
        got = await square_routing.list_tenants_by_square_merchant_id(MERCHANT)
    assert len(got) == 3
    assert {t["id"] for t in got} == {DANI, SHAHID, THIRD}


@pytest.mark.asyncio
async def test_merchant_lookup_short_circuits_on_empty_input():
    from db import square_routing
    assert await square_routing.list_tenants_by_square_merchant_id("") == []
    assert await square_routing.list_square_bindings_for_location("") == []
    assert await square_routing.load_location_candidates("") == []


# ═══════════════════════════════════════════════════════════════════════════
# §15 — zero blast radius
# ═══════════════════════════════════════════════════════════════════════════

def test_the_resolver_is_reachable_only_through_the_observability_layer():
    """W7B wired W7A in — for OBSERVATION only.

    The guard that mattered was never "nothing imports this"; it was "nothing
    that MUTATES imports this". So the allowed importers are pinned by name: the
    shadow observer, and the endpoint that calls it. A booking or catalog handler
    reaching for the resolver would mean routing had changed without review.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    allowed = {"services/square_webhook_observability.py",
               "services/square_booking_reconcile.py",   # W7D: the cutover itself
               "routers/payments.py",
               "services/square_webhook_resolution.py",
               "db/square_routing.py"}

    importers = []
    for path in list((root / "routers").rglob("*.py")) + list((root / "services").rglob("*.py")) \
            + list((root / "db").rglob("*.py")):
        rel = str(path.relative_to(root))
        tree = ast.parse(path.read_text())
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        if any("square_webhook_resolution" in x or "square_routing" in x for x in names):
            importers.append(rel)

    assert set(importers) <= allowed, f"unexpected importer(s): {sorted(set(importers) - allowed)}"
    # and the mutating handlers specifically must not be among them
    assert "services/square_booking.py" not in importers


def test_the_square_webhook_dispatch_is_unchanged():
    import inspect

    from routers import payments

    src = inspect.getsource(payments.square_webhook)
    assert "square_webhook_resolution" not in src
    assert "square_routing" not in src
    for case in ('"payment.updated" | "payment.created"',
                 '"booking.created" | "booking.updated"',
                 '"catalog.version.updated"'):
        assert case in src


def test_the_booking_and_catalog_handlers_still_use_the_old_lookup():
    """Pinned deliberately: if a later change switches them over, it must be a
    reviewed W7B/C/D decision, not a side effect."""
    import inspect

    from services import square_booking

    for fn in (square_booking.handle_booking_event, square_booking.handle_catalog_update):
        src = inspect.getsource(fn)
        assert "get_tenant_by_square_merchant_id" in src
        assert "square_webhook_resolution" not in src
