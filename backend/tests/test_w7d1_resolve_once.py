"""W7D.1 — one Resolution per delivery, shared by telemetry and correctness.

THE CHANGE
Before this, a single booking delivery resolved identity TWICE. W7B's
shadow_resolve() and W7D's _resolve_identity() issued the same two PostgREST
reads -- list_tenants_by_square_merchant_id and load_location_candidates --
against the same inputs, in the same request. Four routing reads where two do.

WHY IT IS WORTH REMOVING
That duplication sat on the exact code path that took the API down. W7D's
production failure was an HTTP/2 GOAWAY on a long-lived pooled connection; the
reason it fired on EVERY delivery rather than occasionally was that W7D had
doubled the PostgREST calls per webhook. W7T fixed the transport. This removes
the amplifier.

WHAT MUST NOT CHANGE, AND IS ASSERTED HERE
  * The ledger is never routing authority. The shared object is computed in
    memory from DB inputs; nothing is read back from provider_webhook_events.
  * Correctness never depends on telemetry succeeding. Passing no Resolution is
    a real, exercised path, not a theoretical one.
  * Sharing one mutable object between two consumers would be a new hazard, so
    the Resolution is frozen and that is proved, not asserted in prose.
  * Every routing outcome decides exactly what it decided before.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services import square_booking_reconcile as rec
from services import square_webhook_identity as ident
from services import square_webhook_observability as obs
from services import square_webhook_resolution as wres

from tests.test_w7d_booking_webhook_cutover import (
    CORK_PID, DUB_PID, DANI, SHAHID, MERCHANT, BOOKING, CORK_LOC,
    World, bundle, envelope, env, tenant, _executable_source,
)


class Counter:
    """Counts the two routing reads, and returns what the scenario specifies."""

    def __init__(self, merchants, bindings):
        self.merchants, self.bindings = merchants, bindings
        self.merchant_reads = self.binding_reads = 0

    async def list_merchants(self, merchant_id):
        self.merchant_reads += 1
        return list(self.merchants)

    async def load_bindings(self, provider_location_id):
        self.binding_reads += 1
        return list(self.bindings)

    @property
    def total(self):
        return self.merchant_reads + self.binding_reads


def counting(merchants=None, bindings=None):
    c = Counter(merchants if merchants is not None else [tenant(DANI)],
                bindings if bindings is not None else [bundle()])
    return c, patch.multiple(
        "db.square_routing",
        list_tenants_by_square_merchant_id=AsyncMock(side_effect=c.list_merchants),
        load_location_candidates=AsyncMock(side_effect=c.load_bindings))


# ═══════════════════════════════════════════════════════════════════════════
# A — the saving is real, and measured
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_A1_the_old_shape_costs_four_routing_reads():
    """The baseline this change removes. Each consumer resolving for itself."""
    c, patcher = counting()
    w = World()
    # env() installs its own routing mocks, so the counter goes INSIDE it.
    with env(w), patcher:
        await obs.shadow_resolve(obs.extract(envelope()))          # telemetry
        await rec.reconcile_booking_event(envelope())              # correctness
    assert c.merchant_reads == 2, "the merchant lookup ran twice"
    assert c.binding_reads == 2, "the binding lookup ran twice"
    assert c.total == 4


@pytest.mark.asyncio
async def test_A2_resolve_once_costs_two():
    """The same work, sharing one computation."""
    c, patcher = counting()
    w = World()
    with env(w), patcher:
        resolution = await ident.resolve_event(envelope())
        await rec.reconcile_booking_event(envelope(), resolution=resolution)
    assert c.merchant_reads == 1
    assert c.binding_reads == 1
    assert c.total == 2, "resolve-once must halve the routing reads"


@pytest.mark.asyncio
async def test_A3_the_endpoint_shape_end_to_end_costs_two():
    """Exactly what routers/payments.py does: resolve, observe, reconcile."""
    c, patcher = counting()
    recorded = {}
    w = World()
    with env(w), patcher, \
         patch("db.provider_webhook_events.record_delivery",
               new=AsyncMock(return_value={"id": "row-1", "delivery_count": 1})), \
         patch("db.provider_webhook_events.set_shadow_resolution",
               new=AsyncMock(side_effect=lambda rid, **kw: recorded.update(kw))):
        ev = envelope()
        resolution = await ident.resolve_event(ev)
        await obs.observe(ev, resolution=resolution)
        out = await rec.reconcile_booking_event(ev, resolution=resolution)
    assert c.total == 2, f"a full delivery issued {c.total} routing reads, expected 2"
    assert recorded["resolution"] == wres.RESOLVED
    assert out.result == rec.RECONCILED_CREATED


@pytest.mark.asyncio
async def test_A4_a_non_booking_event_costs_no_routing_reads_at_all():
    """Resolution is scoped to booking events. A payment must not pay for it."""
    c, patcher = counting()
    with patcher:
        res = await ident.resolve_event(
            {"event_id": "e", "type": "payment.updated", "merchant_id": MERCHANT,
             "data": {"type": "payment", "id": "p", "object": {"payment": {}}}})
    assert res is None
    assert c.total == 0


# ═══════════════════════════════════════════════════════════════════════════
# B — the ledger is still never routing authority
# ═══════════════════════════════════════════════════════════════════════════

def test_B1_the_identity_module_never_touches_the_ledger():
    code = _executable_source(ident)
    for forbidden in ("provider_webhook_events", "set_shadow_resolution", "ledger",
                      "record_delivery", "set_legacy_result"):
        assert forbidden not in code, f"identity reached for {forbidden}"


def test_B2_identity_is_computed_from_db_inputs_and_the_pure_resolver():
    code = _executable_source(ident)
    assert "list_tenants_by_square_merchant_id" in code
    assert "load_location_candidates" in code
    assert "resolve_square_tenant_location" in code


def test_B3_the_reconciler_resolves_through_identity_not_the_ledger():
    code = _executable_source(rec)
    assert "identity.load_and_resolve" in code
    assert "provider_webhook_events" not in code
    assert "ledger" not in code


def test_B4_the_endpoint_routes_on_the_resolver_not_on_the_observation():
    import ast
    import inspect

    from routers import payments
    tree = ast.parse(inspect.getsource(payments.square_webhook).lstrip())
    code = ast.unparse(tree)
    # the value handed to the reconciler is produced by resolve_event, and the
    # ledger row is a separate variable that never feeds it
    assert "_resolution = await _w7id.resolve_event(event)" in code
    assert "resolution=_resolution" in code
    assert "_resolution = _observation" not in code
    for column in ("resolved_tenant", "resolution_detail", "shadow_resolution"):
        assert column not in code


# ═══════════════════════════════════════════════════════════════════════════
# C — sharing is only safe because the shared thing cannot change
# ═══════════════════════════════════════════════════════════════════════════

def test_C1_a_resolution_refuses_every_write():
    r = wres.Resolution(wres.RESOLVED, tenant_id=DANI, tenant_location_id=CORK_LOC)
    for field in ("outcome", "tenant_id", "tenant_location_id", "provider_location_id",
                  "binding_id", "merchant_status", "detail", "eligible_count",
                  "candidate_count"):
        with pytest.raises(AttributeError):
            setattr(r, field, "tampered")
    assert r.outcome == wres.RESOLVED
    assert r.tenant_id == DANI


def test_C2_a_resolution_refuses_deletion_and_new_attributes():
    r = wres.Resolution(wres.RESOLVED, tenant_id=DANI, tenant_location_id=CORK_LOC)
    with pytest.raises(AttributeError):
        del r.outcome
    with pytest.raises(AttributeError):
        r.something_new = 1


def test_C3_construction_still_works_and_the_derived_properties_are_intact():
    r = wres.Resolution(wres.RESOLVED, tenant_id=DANI, tenant_location_id=CORK_LOC,
                        binding_id="b1", merchant_status=wres.MERCHANT_MAPPED,
                        detail="d", eligible_count=1, candidate_count=2)
    assert (r.ok, r.may_mutate) == (True, True)
    assert (r.eligible_count, r.candidate_count) == (1, 2)
    refused = wres.Resolution(wres.IDENTITY_CONFLICT, detail="no")
    assert (refused.ok, refused.may_mutate) == (False, False)


@pytest.mark.asyncio
async def test_C4_telemetry_persists_the_very_object_correctness_routes_on():
    """Not an equal one -- the same one. Two computations could agree today and
    diverge after any change to the inputs between them; one object cannot."""
    seen = {}
    c, patcher = counting()
    w = World()
    captured = {}
    real = rec._resolve_identity

    async def spy(meta):
        captured["recomputed"] = True
        return await real(meta)

    with env(w), patcher, \
         patch("db.provider_webhook_events.record_delivery",
               new=AsyncMock(return_value={"id": "row-1", "delivery_count": 1})), \
         patch("db.provider_webhook_events.set_shadow_resolution",
               new=AsyncMock(side_effect=lambda rid, **kw: seen.update(kw))), \
         patch.object(rec, "_resolve_identity", new=spy):
        ev = envelope()
        resolution = await ident.resolve_event(ev)
        await obs.observe(ev, resolution=resolution)
        await rec.reconcile_booking_event(ev, resolution=resolution)

    assert "recomputed" not in captured, "the reconciler recomputed a resolution it was given"
    assert seen["resolved_tenant_id"] == resolution.tenant_id
    assert seen["resolution"] == resolution.outcome


# ═══════════════════════════════════════════════════════════════════════════
# D — correctness never depends on telemetry
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_D1_no_resolution_supplied_means_resolve_for_yourself():
    w = World()
    with env(w):
        out = await rec.reconcile_booking_event(envelope())
    assert out.result == rec.RECONCILED_CREATED
    assert out.tenant_location_id == CORK_LOC


@pytest.mark.asyncio
async def test_D2_resolve_event_fails_open_when_a_routing_read_raises():
    """A routing-read hiccup at the top of the endpoint must not become a
    payment outage. None is returned, and None is not a decision."""
    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(side_effect=RuntimeError("PostgREST down"))):
        assert await ident.resolve_event(envelope()) is None


@pytest.mark.asyncio
async def test_D3_when_the_shared_computation_failed_the_reconciler_still_routes():
    """The fallback is the whole reason failing open is acceptable."""
    w = World()
    with env(w):
        with patch("db.square_routing.list_tenants_by_square_merchant_id",
                   new=AsyncMock(side_effect=RuntimeError("transient"))):
            resolution = await ident.resolve_event(envelope())
        assert resolution is None
        out = await rec.reconcile_booking_event(envelope(), resolution=resolution)
    assert out.result == rec.RECONCILED_CREATED, "a telemetry failure changed correctness"


@pytest.mark.asyncio
async def test_D4_load_and_resolve_does_NOT_fail_open():
    """Only the endpoint-level helper fails open. The computation itself must
    propagate, so a caller that needs an answer cannot mistake an error for a
    refusal."""
    with patch("db.square_routing.load_location_candidates",
               new=AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError):
            await ident.load_and_resolve(obs.extract(envelope()))


@pytest.mark.asyncio
async def test_D5_a_ledger_write_failure_does_not_change_routing():
    w = World()
    with env(w), \
         patch("db.provider_webhook_events.record_delivery",
               new=AsyncMock(side_effect=RuntimeError("ledger down"))):
        ev = envelope()
        resolution = await ident.resolve_event(ev)
        row = await obs.observe(ev, resolution=resolution)
        assert row is None
        out = await rec.reconcile_booking_event(ev, resolution=resolution)
    assert out.result == rec.RECONCILED_CREATED


@pytest.mark.asyncio
async def test_D6_observe_without_a_resolution_still_shadow_resolves():
    """The standalone telemetry path is unchanged for callers outside the
    endpoint, and for W7B's own tests."""
    seen = {}
    c, patcher = counting()
    with patcher, \
         patch("db.provider_webhook_events.record_delivery",
               new=AsyncMock(return_value={"id": "row-1", "delivery_count": 1})), \
         patch("db.provider_webhook_events.set_shadow_resolution",
               new=AsyncMock(side_effect=lambda rid, **kw: seen.update(kw))):
        await obs.observe(envelope())
    assert seen["resolution"] == wres.RESOLVED
    assert c.total == 2, "the standalone path must still do its own two reads"


# ═══════════════════════════════════════════════════════════════════════════
# E — every routing outcome decides exactly what it decided before
# ═══════════════════════════════════════════════════════════════════════════

SCENARIOS = {
    "resolved":          (None, None, rec.RECONCILED_CREATED),
    "identity_conflict": ([tenant(SHAHID, merchant=MERCHANT)], None, wres.IDENTITY_CONFLICT),
    "unbound_location":  (None, [], wres.UNBOUND_LOCATION),
    "ambiguous_binding": (None, [bundle(bid="b1", tid=DANI, lid="loc-a"),
                                 bundle(bid="b2", tid=SHAHID, lid="loc-b")],
                          wres.AMBIGUOUS_BINDING),
    "inactive_binding":  (None, [bundle(status="INACTIVE")], wres.INACTIVE_BINDING),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
@pytest.mark.asyncio
async def test_E_shared_and_unshared_reach_the_same_outcome(name):
    merchants, bindings, expected = SCENARIOS[name]
    merchants = merchants if merchants is not None else [tenant(DANI)]
    bindings = bindings if bindings is not None else [bundle()]

    # unshared: the reconciler resolves for itself
    w1 = World()
    with env(w1, merchants=merchants, bindings=bindings):
        unshared = await rec.reconcile_booking_event(envelope())

    # shared: identity is computed once and handed over
    w2 = World()
    with env(w2, merchants=merchants, bindings=bindings):
        resolution = await ident.resolve_event(envelope())
        shared = await rec.reconcile_booking_event(envelope(), resolution=resolution)

    assert unshared.result == expected, f"{name}: baseline changed"
    assert shared.result == unshared.result, f"{name}: resolve-once changed the outcome"
    assert shared.tenant_id == unshared.tenant_id
    assert shared.tenant_location_id == unshared.tenant_location_id
    # a refusal creates nothing, either way
    if expected != rec.RECONCILED_CREATED:
        assert not w1.inserts and not w2.inserts


@pytest.mark.asyncio
async def test_E1b_an_envelope_with_no_location_is_unknown_either_way():
    """UNKNOWN_LOCATION is a different refusal from UNBOUND_LOCATION -- our
    extraction failed, rather than Square naming a location nobody onboarded --
    and resolve-once must not blur them."""
    w1 = World()
    with env(w1):
        unshared = await rec.reconcile_booking_event(envelope(omit_location=True))
    w2 = World()
    with env(w2):
        resolution = await ident.resolve_event(envelope(omit_location=True))
        shared = await rec.reconcile_booking_event(
            envelope(omit_location=True), resolution=resolution)
    assert unshared.result == wres.UNKNOWN_LOCATION
    assert shared.result == unshared.result
    assert resolution.outcome == wres.UNKNOWN_LOCATION
    assert not w1.inserts and not w2.inserts


@pytest.mark.asyncio
async def test_E2_a_refusal_passed_in_still_creates_nothing_and_asks_no_retry():
    c, patcher = counting(merchants=[tenant(SHAHID, merchant=MERCHANT)])
    w = World()
    with env(w, merchants=[tenant(SHAHID, merchant=MERCHANT)]) as provider, patcher:
        resolution = await ident.resolve_event(envelope())
        assert resolution.outcome == wres.IDENTITY_CONFLICT
        assert resolution.may_mutate is False
        out = await rec.reconcile_booking_event(envelope(), resolution=resolution)
    assert out.result == wres.IDENTITY_CONFLICT
    assert out.should_retry is False
    assert not w.inserts
    provider["create"].assert_not_called()
    provider["cancel"].assert_not_called()
    assert c.total == 2


@pytest.mark.asyncio
async def test_E3_a_non_booking_envelope_is_refused_even_with_a_resolution():
    """The event-type gate still comes first; a stray Resolution cannot open it."""
    resolution = wres.Resolution(wres.RESOLVED, tenant_id=DANI, tenant_location_id=CORK_LOC)
    out = await rec.reconcile_booking_event(
        {"event_id": "e", "type": "payment.updated", "merchant_id": MERCHANT,
         "data": {"type": "payment", "id": "p", "object": {"payment": {}}}},
        resolution=resolution)
    assert out.result == rec.NOT_BOOKING_EVENT


@pytest.mark.asyncio
async def test_E4_concurrent_deliveries_each_resolve_once():
    c, patcher = counting()
    with patcher:
        results = await asyncio.gather(*(ident.resolve_event(envelope(event_id=f"e{i}"))
                                         for i in range(5)))
    assert all(r.outcome == wres.RESOLVED for r in results)
    assert c.total == 10, "five deliveries must cost two reads each, not four"
