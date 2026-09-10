"""
W6A2 prerequisite — at most one CreateBooking per slot offer.

The live booking path was read-then-act:

    resolve_for_booking()   -> reads consumed_at, sees NULL
    create_booking()        -> fresh uuid4 idempotency key
    mark_consumed()         -> unconditional UPDATE, AFTER Square

Two concurrent tool calls with the same slot_ref both read NULL, both reached
CreateBooking, and because the key was random per request Square did not dedupe
them. One caller, two appointments. Vapi retries are ordinary, so this was
reachable in production — W5 had closed only the sequential retry.

The claim is now a CAS on consumed_at, taken BEFORE Square. What makes that
sufficient rather than merely better is the unknown-outcome rule: a timeout or
5xx leaves the slot claimed, because the booking may exist and the body cannot be
replayed byte-identically (team_member_id comes from a live resolve_slot, and the
key is regenerated). Releasing there would trade one uncertain booking for two
certain ones.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools
from services import slot_offers, square_booking as sb

TID, CALL, SLOT = "t-dani", "call-1", "slot_1"
CORK_PID, CORK_LOC = "L0Q8GTAZCHD42", "loc-cork"
ADOPTED = [{"id": CORK_LOC, "name": "Cork", "active": True, "booking_enabled": True}]
TENANT = {"id": TID, "square_appointments_enabled": True, "calendar_timezone": "Europe/Dublin"}


def offer(**over):
    o = {"vapi_call_id": CALL, "slot_ref": SLOT, "tenant_id": TID,
         "tenant_location_id": CORK_LOC, "provider_location_id": CORK_PID,
         "service_variation_id": "V1", "service_variation_version": 1,
         "service_name": "Consultation", "team_member_id": "TM1",
         "start_at_utc": "2026-10-01T13:00:00Z", "duration_minutes": 60,
         "expires_at": "2099-01-01T00:00:00+00:00", "consumed_at": None, "booking_id": None}
    o.update(over)
    return o


class Offers:
    """A fake call_slot_offers enforcing the real CAS predicates."""

    def __init__(self, row=None):
        self.row = row or offer()
        self.lock = asyncio.Lock()

    async def get(self, call_id, slot_ref, tenant_id):
        r = self.row
        if r["vapi_call_id"] != call_id or r["slot_ref"] != slot_ref or r["tenant_id"] != tenant_id:
            return None
        return dict(r)

    async def claim(self, call_id, slot_ref, tenant_id):
        async with self.lock:
            r = self.row
            if (r["vapi_call_id"] == call_id and r["slot_ref"] == slot_ref
                    and r["tenant_id"] == tenant_id and r["consumed_at"] is None):
                r["consumed_at"] = "claimed"
                return True
            return False

    async def release(self, call_id, slot_ref):
        async with self.lock:
            if self.row["booking_id"] is None:          # never un-consume a booked slot
                self.row["consumed_at"] = None

    async def consume(self, call_id, slot_ref, booking_id):
        async with self.lock:
            if self.row["booking_id"] is None:
                self.row["consumed_at"] = "consumed"
                self.row["booking_id"] = booking_id
            return dict(self.row)


class Ctx:
    def __init__(self, offers=None, create=None):
        self.offers = offers or Offers()
        self.creates = []
        self.create_impl = create
        self.inserted = []

    async def _create(self, token, **kw):
        self.creates.append(kw)
        if self.create_impl:
            return await self.create_impl(kw)
        return {"id": f"BK{len(self.creates)}", "status": "ACCEPTED"}

    def __enter__(self):
        self._p = [
            patch("db.locations.get_slot_offer", new=AsyncMock(side_effect=self.offers.get)),
            patch("db.locations.claim_slot_offer", new=AsyncMock(side_effect=self.offers.claim)),
            patch("db.locations.release_slot_offer", new=AsyncMock(side_effect=self.offers.release)),
            patch("db.locations.consume_slot_offer", new=AsyncMock(side_effect=self.offers.consume)),
            patch("services.call_location.get_or_create",
                  new=AsyncMock(return_value={"vapi_call_id": CALL, "active_location_id": CORK_LOC})),
            patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")),
            patch("services.square_booking.resolve_slot", new=AsyncMock(return_value={
                "team_member_id": "TM1", "service_variation_version": 1,
                "duration_minutes": 60, "start_at": "2026-10-01T13:00:00Z"})),
            patch("services.square_booking.resolve_customer",
                  new=AsyncMock(return_value=("ok", "CUST"))),
            patch("services.square_booking.create_booking", new=AsyncMock(side_effect=self._create)),
            patch("db.supabase.insert_appointment",
                  new=AsyncMock(side_effect=lambda d: self.inserted.append(d))),
            patch("services.analytics.capture"),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()

    async def book(self):
        return await tools._multi_location_book(
            "tc-1", CALL, TENANT, TID, {"slot_ref": SLOT},
            caller_name="Aoife", caller_phone="+353871234567", adopted=ADOPTED)

    @staticmethod
    def text(r):
        return r["results"][0]["result"]


# ── 1, 2, 3. the race ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_concurrent_bookings_on_one_slot_reach_square_once():
    """The defect, reproduced as a race and then closed."""
    with Ctx() as c:
        results = await asyncio.gather(c.book(), c.book())
    assert len(c.creates) == 1, f"CreateBooking called {len(c.creates)} times"
    assert len(c.inserted) == 1, "and exactly one appointment persisted"
    spoken = [c.text(r).lower() for r in results]
    # Exactly one fresh confirmation. The loser lands on "still confirming" or, if
    # the winner finished first, on the idempotent "already booked" — both correct,
    # and neither books anything.
    assert sum(s.startswith("done!") for s in spoken) == 1, spoken
    loser = next(s for s in spoken if not s.startswith("done!"))
    assert "still confirming" in loser or "already booked" in loser, loser


@pytest.mark.asyncio
async def test_ten_concurrent_bookings_still_reach_square_once():
    with Ctx() as c:
        await asyncio.gather(*[c.book() for _ in range(10)])
    assert len(c.creates) == 1
    assert len(c.inserted) == 1


@pytest.mark.asyncio
async def test_the_claim_loser_performs_no_provider_mutation_at_all():
    offers = Offers(offer(consumed_at="claimed"))     # already held by someone else
    with Ctx(offers=offers) as c:
        res = await c.book()
    assert c.creates == []
    assert "still confirming" in c.text(res).lower()


# ── 4. success ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_successful_booking_leaves_the_slot_permanently_consumed():
    with Ctx() as c:
        await c.book()
    assert c.offers.row["consumed_at"] == "consumed"
    assert c.offers.row["booking_id"] == "BK1"


@pytest.mark.asyncio
async def test_a_sequential_duplicate_after_success_books_nothing_more():
    with Ctx() as c:
        await c.book()
        res = await c.book()
    assert len(c.creates) == 1
    assert "already booked" in c.text(res).lower()


# ── 5 & 6. definitive failure ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_definitive_rejection_releases_the_slot():
    async def reject(_kw):
        raise RuntimeError("400 Bad Request")
    with Ctx(create=reject) as c:
        await c.book()
    assert c.offers.row["consumed_at"] is None, "a rejected slot must be offerable again"
    assert c.offers.row["booking_id"] is None


@pytest.mark.asyncio
async def test_a_released_slot_can_be_claimed_and_booked_on_retry():
    state = {"fail": True}

    async def flaky(_kw):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("400 Bad Request")
        return {"id": "BK-RETRY", "status": "ACCEPTED"}

    with Ctx(create=flaky) as c:
        await c.book()
        res = await c.book()
    assert len(c.creates) == 2
    assert c.offers.row["booking_id"] == "BK-RETRY"
    assert "confirmed" in c.text(res).lower()


# ── 9. the unknown outcome — the trap this must not open ─────────────────────

@pytest.mark.asyncio
async def test_an_unknown_outcome_keeps_the_slot_and_never_retries():
    """A timeout means the booking MAY exist. Releasing here would let a retry
    issue a SECOND CreateBooking under a fresh idempotency key, turning one
    uncertain booking into two certain ones."""
    async def timeout(_kw):
        raise sb.BookingOutcomeUnknown("connection dropped")

    with Ctx(create=timeout) as c:
        res = await c.book()
        assert c.offers.row["consumed_at"] == "claimed", "slot must stay claimed"
        spoken = c.text(res).lower()
        assert "couldn't confirm whether that booking went through" in spoken
        assert "do not book it a second time" in spoken
        # a retry in the same call must not reach Square either
        c.create_impl = None
        res2 = await c.book()
    assert len(c.creates) == 1, "no second CreateBooking after an unknown outcome"
    assert "still confirming" in c.text(res2).lower()


@pytest.mark.asyncio
async def test_a_5xx_is_treated_as_unknown_not_as_rejection():
    class _Resp:
        status_code, is_success, text = 503, False, "upstream"
        def json(self): return {}
        def raise_for_status(self): raise RuntimeError("should not be reached")

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw): return _Resp()

    with patch("services.square_booking.httpx.AsyncClient", _Client):
        with pytest.raises(sb.BookingOutcomeUnknown):
            await sb.create_booking("tok", location_id="L", start_at_iso="2026-10-01T13:00:00Z",
                                    customer_id="C", team_member_id="TM",
                                    service_variation_id="V", service_variation_version=1,
                                    duration_minutes=60)


@pytest.mark.asyncio
async def test_a_4xx_stays_a_definitive_rejection():
    import httpx as _httpx

    class _Resp:
        status_code, is_success, text = 400, False, "bad"
        def json(self): return {}
        def raise_for_status(self):
            raise _httpx.HTTPStatusError("400", request=None, response=None)

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw): return _Resp()

    with patch("services.square_booking.httpx.AsyncClient", _Client):
        with pytest.raises(_httpx.HTTPStatusError):
            await sb.create_booking("tok", location_id="L", start_at_iso="2026-10-01T13:00:00Z",
                                    customer_id="C", team_member_id="TM",
                                    service_variation_id="V", service_variation_version=1,
                                    duration_minutes=60)


# ── 7. refs that must never claim ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("row, expect", [
    (offer(expires_at="2020-01-01T00:00:00+00:00"), "held too long"),
    (offer(tenant_location_id="loc-dublin"),         "offered for"),
    (offer(consumed_at="consumed", booking_id="BK9"), "already booked"),
])
async def test_an_unbookable_offer_never_reaches_the_claim(row, expect):
    with Ctx(offers=Offers(row)) as c:
        res = await c.book()
    assert c.creates == []
    assert c.offers.row["consumed_at"] == row["consumed_at"], "claim must not have run"
    assert expect in c.text(res).lower() or expect in c.text(res)


@pytest.mark.asyncio
async def test_a_ref_from_another_call_or_tenant_never_claims():
    with Ctx() as c:
        res = await tools._multi_location_book(
            "tc-1", "another-call", TENANT, TID, {"slot_ref": SLOT},
            caller_name="A", caller_phone="+353871234567", adopted=ADOPTED)
    assert c.creates == []
    assert c.offers.row["consumed_at"] is None
    assert "couldn't find that time" in c.text(res)


# ── the CAS predicates themselves ────────────────────────────────────────────

def test_the_claim_is_conditional_on_consumed_at_being_null():
    import ast
    import inspect
    from db import locations as dbl
    code = ast.unparse(ast.parse(inspect.getsource(dbl.claim_slot_offer).lstrip()))
    assert "is_('consumed_at', 'null')" in code
    assert "eq('tenant_id', tenant_id)" in code


def test_release_cannot_un_consume_a_booked_slot():
    import ast
    import inspect
    from db import locations as dbl
    code = ast.unparse(ast.parse(inspect.getsource(dbl.release_slot_offer).lstrip()))
    assert "is_('booking_id', 'null')" in code


def test_finalize_cannot_overwrite_an_existing_booking_id():
    import ast
    import inspect
    from db import locations as dbl
    code = ast.unparse(ast.parse(inspect.getsource(dbl.consume_slot_offer).lstrip()))
    assert "is_('booking_id', 'null')" in code


def test_claim_happens_before_create_booking_in_the_source_order():
    import inspect
    src = inspect.getsource(tools._multi_location_book)
    assert src.index("slot_offers.claim(") < src.index("square_booking.create_booking(")


def test_the_unknown_branch_does_not_release_the_slot():
    """The single most important line in this change: releasing on an unknown
    outcome is how one uncertain booking becomes two certain ones."""
    import inspect
    src = inspect.getsource(tools._multi_location_book)
    unknown = src.split("BookingOutcomeUnknown")[1].split("except Exception")[0]
    assert "slot_offers.release" not in unknown
