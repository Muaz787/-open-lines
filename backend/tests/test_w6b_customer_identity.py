"""
W6B — one caller, one Square customer, however many workers ask at once.

Square's customer SEARCH index is eventually consistent; GET by id is not. The old
find_or_create_customer searched, missed, and created — so two resolutions seconds
apart both created. A W5.2 probe did exactly that and produced two customers for
one caller.

There is no advisory lock available: this repository reaches Postgres only through
PostgREST, so there is no session to hold one in. Uniqueness IS the lock. The
tests below therefore care about two things above all — that exactly one worker
ever reaches CreateCustomer, and that a worker which crashes mid-create is
recovered by replaying the SAME stable key rather than by hoping the search index
has caught up.

The concurrency tests run genuinely competing coroutines against a fake store that
enforces the real unique index. Sequential mocks pretending to be concurrent would
prove nothing about the thing most likely to be wrong.
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from services import customer_identity as ci

T1, T2 = "tenant-one", "tenant-two"
IE, CA = "+353871234567", "+16477633632"
REAL_NAME = "Aoife Kelly"


# ── the store: a fake provider_customers that enforces the real constraints ──

class Store:
    """Behaves like the table, including its unique index and CAS semantics.

    Every mutation goes through a lock so interleavings are real rather than
    accidental, exactly as Postgres would serialise them.
    """

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.lock = asyncio.Lock()

    # Production decides staleness by comparing claimed_at against a cutoff, so
    # the fake must too — an opt-in flag the real code never reads would test
    # nothing. Fresh claims sit after the cutoff; mark_stale backdates one.
    FRESH = "2026-09-10T20:00:00+00:00"
    STALE = "2020-01-01T00:00:00+00:00"
    CUTOFF = "2021-01-01T00:00:00+00:00"

    def mark_stale(self, row_id):
        self.rows[row_id]["claimed_at"] = self.STALE

    def _key(self, t, p, ph):
        return (t, p, ph)

    async def get_mapping(self, tenant_id, provider, phone):
        for r in self.rows.values():
            if self._key(r["tenant_id"], r["provider"], r["normalized_phone"]) == self._key(tenant_id, provider, phone):
                return dict(r)
        return None

    async def get_by_id(self, row_id):
        r = self.rows.get(row_id)
        return dict(r) if r else None

    async def try_create_claim(self, tenant_id, provider, phone, claim_token):
        async with self.lock:
            if await self._exists(tenant_id, provider, phone):
                return None                                  # the unique index
            rid = str(uuid.uuid4())
            self.rows[rid] = {"id": rid, "tenant_id": tenant_id, "provider": provider,
                              "normalized_phone": phone, "provider_customer_id": None,
                              "provider_merchant_id": None, "claim_token": claim_token,
                              "claimed_at": self.FRESH}
            return dict(self.rows[rid])

    async def _exists(self, tenant_id, provider, phone):
        return any(self._key(r["tenant_id"], r["provider"], r["normalized_phone"])
                   == self._key(tenant_id, provider, phone) for r in self.rows.values())

    async def acquire_unowned_claim_cas(self, row_id, claim_token):
        async with self.lock:
            r = self.rows.get(row_id)
            if r and r["provider_customer_id"] is None and r["claim_token"] is None:
                r["claim_token"] = claim_token
                return True
            return False

    async def takeover_stale_claim_cas(self, row_id, prev_token, prev_claimed_at, claim_token):
        async with self.lock:
            r = self.rows.get(row_id)
            if (r and r["provider_customer_id"] is None
                    and r["claim_token"] == prev_token
                    and r["claimed_at"] == prev_claimed_at
                    and r["claimed_at"] < self.CUTOFF):
                r["claim_token"] = claim_token
                r["claimed_at"] = self.FRESH
                return True
            return False

    async def finalize_mapping_cas(self, row_id, claim_token, provider_customer_id,
                                   provider_merchant_id=None):
        async with self.lock:
            r = self.rows.get(row_id)
            if r and r["claim_token"] == claim_token and r["provider_customer_id"] is None:
                r["provider_customer_id"] = provider_customer_id
                r["provider_merchant_id"] = provider_merchant_id
                r["claim_token"] = None
                return True
            return False

    async def release_claim_cas(self, row_id, claim_token):
        async with self.lock:
            r = self.rows.get(row_id)
            if r and r["claim_token"] == claim_token and r["provider_customer_id"] is None:
                r["claim_token"] = None
                return True
            return False

    def stale_cutoff_iso(self):
        return self.CUTOFF


class Square:
    """A fake Square that honours idempotency_key, as the real one was measured to."""

    def __init__(self, existing=None, search_error=None, create_error=None,
                 create_returns_none=False):
        # {"id":..., "phone":...}; a bare id means "matches any phone", which is
        # how the adoption tests seed a pre-existing customer.
        self.customers = list(existing or [])
        self.search_error = search_error
        self.create_error = create_error
        self.create_returns_none = create_returns_none
        self.searches = 0
        self.creates = 0
        self.keys: list[str] = []
        self.payloads: list[dict] = []
        self.last_given_name = ""
        self.by_key: dict[str, str] = {}

    async def search_customers_by_phone(self, token, phone):
        self.searches += 1
        if self.search_error:
            raise self.search_error
        return [c for c in self.customers if c.get("phone") in (None, phone)]

    async def create_customer(self, token, *, phone, given_name="", idempotency_key=""):
        self.creates += 1
        self.keys.append(idempotency_key)
        self.last_given_name = given_name
        # The exact logical request, so a test can compare two attempts field by field.
        self.payloads.append({"phone": phone, "given_name": given_name,
                              "idempotency_key": idempotency_key})
        if self.create_error:
            raise self.create_error
        if self.create_returns_none:
            return None
        if idempotency_key in self.by_key:
            return self.by_key[idempotency_key]          # Square dedupes
        cid = f"SQ-{len(self.by_key) + 1}"
        self.by_key[idempotency_key] = cid
        self.customers.append({"id": cid, "phone": phone})
        return cid


def install(store):
    return patch.multiple(
        "db.provider_customers",
        get_mapping=AsyncMock(side_effect=store.get_mapping),
        get_by_id=AsyncMock(side_effect=store.get_by_id),
        try_create_claim=AsyncMock(side_effect=store.try_create_claim),
        acquire_unowned_claim_cas=AsyncMock(side_effect=store.acquire_unowned_claim_cas),
        takeover_stale_claim_cas=AsyncMock(side_effect=store.takeover_stale_claim_cas),
        finalize_mapping_cas=AsyncMock(side_effect=store.finalize_mapping_cas),
        release_claim_cas=AsyncMock(side_effect=store.release_claim_cas),
        stale_cutoff_iso=store.stale_cutoff_iso,
    )


async def resolve(store, sq, tenant=T1, phone=IE):
    with install(store):
        return await ci.resolve_customer_id(
            tenant_id=tenant, token="tok", phone=phone, square=sq)


# ── 17 & 18. phone normalization ─────────────────────────────────────────────

@pytest.mark.parametrize("raw, expect", [
    ("+353871234567", "+353871234567"),
    ("+353 87 123 4567", "+353871234567"),
    ("+16477633632", "+16477633632"),
    ("+1 (647) 763-3632", "+16477633632"),
])
def test_trusted_e164_survives_exactly(raw, expect):
    assert ci.normalize_e164(raw) == expect


@pytest.mark.parametrize("raw", ["6477633632", "0871234567", "1234567890", "087 123 4567",
                                 "", "   ", None, "+", "+0123456789", "+00000000000", "abc"])
def test_non_e164_is_refused_never_guessed(raw):
    """The NANP rule in telephony.normalize_phone would turn a 10-digit Irish
    number into a US one. This key is durable identity — a wrong country code binds
    the caller to the wrong customer permanently, so we refuse instead of infer."""
    assert ci.normalize_e164(raw) == ""


@pytest.mark.asyncio
async def test_a_non_e164_phone_never_reaches_square():
    sq = Square()
    status, cid = await resolve(Store(), sq, phone="6477633632")
    assert (status, cid) == (ci.FAILED, None)
    assert sq.searches == 0 and sq.creates == 0


# ── 1 & 2. the steady state ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_mapped_customer_costs_no_provider_call_at_all():
    store, sq = Store(), Square()
    await resolve(store, sq)                       # first: claim, search, create
    sq2 = Square()
    status, cid = await resolve(store, sq2)
    assert (status, cid) == (ci.OK, "SQ-1")
    assert sq2.searches == 0, "a mapped caller must not be searched for"
    assert sq2.creates == 0, "a mapped caller must not be created again"


# ── 3 & 4. adoption vs creation ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_existing_square_customer_is_adopted_not_duplicated():
    """How every caller who predates this table gets mapped."""
    store, sq = Store(), Square(existing=[{"id": "SQ-OLD"}])
    status, cid = await resolve(store, sq)
    assert (status, cid) == (ci.OK, "SQ-OLD")
    assert sq.creates == 0
    row = await store.get_mapping(T1, "square", IE)
    assert row["provider_customer_id"] == "SQ-OLD" and row["claim_token"] is None


@pytest.mark.asyncio
async def test_no_existing_customer_creates_exactly_one():
    store, sq = Store(), Square()
    status, cid = await resolve(store, sq)
    assert status == ci.OK and cid == "SQ-1"
    assert sq.creates == 1


# ── 5. the idempotency key ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_idempotency_key_is_the_bare_row_uuid():
    """Not prefixed, and never claim_token — the token changes hands on takeover,
    which is precisely what a provider identity must not do."""
    store, sq = Store(), Square()
    await resolve(store, sq)
    row = await store.get_mapping(T1, "square", IE)
    assert sq.keys == [str(row["id"])]
    uuid.UUID(sq.keys[0])                                   # parses as a bare UUID
    assert not sq.keys[0].startswith("square-customer-")


# ── 6 & 7. REAL concurrency ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ten_concurrent_resolutions_create_exactly_one_customer():
    """The defect, reproduced as a race and then closed.

    Ten coroutines compete for one (tenant, phone). The fake store enforces the
    same unique index the migration does, so only one insert can win — and only
    the winner is allowed to reach Square.
    """
    store, sq = Store(), Square()
    with install(store):
        results = await asyncio.gather(*[
            ci.resolve_customer_id(tenant_id=T1, token="tok", phone=IE, square=sq)
            for _ in range(10)])

    assert sq.creates == 1, f"expected exactly one CreateCustomer, got {sq.creates}"
    ids = {cid for status, cid in results if status == ci.OK}
    assert ids == {"SQ-1"}, f"all winners must agree on one customer, got {ids}"
    assert all(status == ci.OK for status, _ in results)
    assert len([r for r in store.rows.values()
                if r["tenant_id"] == T1 and r["normalized_phone"] == IE]) == 1


@pytest.mark.asyncio
async def test_concurrent_losers_never_call_square_themselves():
    """One search, one create, nine losers — the losers wait on the DB claim, they
    do not go and ask Square themselves."""
    store, sq = Store(), Square()
    with install(store):
        await asyncio.gather(*[
            ci.resolve_customer_id(tenant_id=T1, token="tok", phone=IE, square=sq)
            for _ in range(10)])
    assert sq.searches == 1
    assert sq.creates == 1


# ── 8 & 9. identity is per tenant, per phone ─────────────────────────────────

@pytest.mark.asyncio
async def test_the_same_phone_in_two_tenants_maps_independently():
    """Two tenants are two Square merchants with two tokens, so the same phone is
    two different customers. Keying the mapping globally by phone would collapse
    them and hand one merchant's customer to another."""
    store, sq1, sq2 = Store(), Square(), Square()
    s1, c1 = await resolve(store, sq1, tenant=T1)
    s2, c2 = await resolve(store, sq2, tenant=T2)
    assert s1 == s2 == ci.OK
    assert sq1.creates == 1 and sq2.creates == 1
    rows = [r for r in store.rows.values() if r["normalized_phone"] == IE]
    assert len(rows) == 2
    assert {r["tenant_id"] for r in rows} == {T1, T2}


@pytest.mark.asyncio
async def test_two_phones_in_one_tenant_map_independently():
    store, sq = Store(), Square()
    _, c1 = await resolve(store, sq, phone=IE)
    _, c2 = await resolve(store, sq, phone=CA)
    assert c1 != c2 and sq.creates == 2


# ── 10 & 11. claim states ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unowned_unresolved_row_is_acquired_immediately():
    """A released claim (token NULL) is available at once. Making the next worker
    wait out a staleness timeout would punish them for the last one's caution."""
    store, sq = Store(), Square(existing=[{"id": "A"}, {"id": "B"}])
    status, _ = await resolve(store, sq)
    assert status == ci.AMBIGUOUS
    row = await store.get_mapping(T1, "square", IE)
    assert row["claim_token"] is None and row["provider_customer_id"] is None

    sq2 = Square()                                  # ambiguity resolved at Square
    status2, cid2 = await resolve(store, sq2)
    assert (status2, cid2) == (ci.OK, "SQ-1")
    assert sq2.creates == 1


@pytest.mark.asyncio
async def test_a_recently_owned_claim_blocks_provider_calls_and_reports_unavailable():
    store = Store()
    rid = (await store.try_create_claim(T1, "square", IE, "someone-elses-token"))["id"]
    sq = Square()
    with install(store), patch("services.customer_identity.LOSER_WAIT_SECONDS", 0):
        status, cid = await ci.resolve_customer_id(
            tenant_id=T1, token="tok", phone=IE, square=sq)
    assert (status, cid) == (ci.UNAVAILABLE, None)
    assert sq.creates == 0, "a caller must never create because someone else is slow"
    assert store.rows[rid]["claim_token"] == "someone-elses-token"


# ── 12, 13, 14, 23. crash and takeover ───────────────────────────────────────

@pytest.mark.asyncio
async def test_a_stale_claim_is_taken_over_by_exactly_one_worker():
    store = Store()
    row = await store.try_create_claim(T1, "square", IE, "abandoned-token")
    store.mark_stale(row["id"])
    sq = Square()
    with install(store):
        results = await asyncio.gather(*[
            ci.resolve_customer_id(tenant_id=T1, token="tok", phone=IE, square=sq)
            for _ in range(5)])
    assert sq.creates == 1
    assert {cid for s, cid in results if s == ci.OK} == {"SQ-1"}


@pytest.mark.asyncio
async def test_crash_after_createcustomer_recovers_to_the_same_customer():
    """The window provider idempotency exists for.

    Worker A creates the customer and dies before finalizing. B takes the stale
    claim over and replays with the SAME row-id key, so Square hands back A's
    customer instead of making a second one. Recovery does not depend on the
    search index having caught up.
    """
    store, sq = Store(), Square()
    row = await store.try_create_claim(T1, "square", IE, "worker-A")
    key = str(row["id"])
    await sq.create_customer("tok", phone=IE, idempotency_key=key)     # A's create
    assert sq.creates == 1
    store.mark_stale(row["id"])

    sq.customers = []          # search index has NOT caught up — deliberately blind
    with install(store):
        status, cid = await ci.resolve_customer_id(
            tenant_id=T1, token="tok", phone=IE, square=sq)

    assert (status, cid) == (ci.OK, "SQ-1"), "must converge on A's customer"
    assert sq.creates == 2, "B did replay CreateBooking-style"
    assert sq.keys == [key, key], "and it replayed with the SAME stable key"
    assert len(sq.by_key) == 1, "so Square holds exactly one customer"


@pytest.mark.asyncio
async def test_the_original_owner_cannot_finalize_after_being_taken_over():
    store = Store()
    row = await store.try_create_claim(T1, "square", IE, "worker-A")
    store.mark_stale(row["id"])
    assert await store.takeover_stale_claim_cas(
        row["id"], "worker-A", store.STALE, "worker-B")     # CAS reads the backdated value
    assert await store.finalize_mapping_cas(row["id"], "worker-A", "SQ-STALE") is False
    assert await store.finalize_mapping_cas(row["id"], "worker-B", "SQ-GOOD") is True
    assert store.rows[row["id"]]["provider_customer_id"] == "SQ-GOOD"


@pytest.mark.asyncio
async def test_an_unknown_createcustomer_outcome_keeps_the_claim_and_the_key():
    """A timeout may or may not have committed. Rotating identity here is what
    creates the second customer, so we keep both and let a replay settle it."""
    store = Store()
    sq = Square(create_error=TimeoutError("connection dropped"))
    status, cid = await resolve(store, sq)
    assert (status, cid) == (ci.FAILED, None)
    row = await store.get_mapping(T1, "square", IE)
    assert row["claim_token"] is not None, "ownership must be retained, not released"
    assert row["provider_customer_id"] is None
    assert sq.keys == [str(row["id"])]


# ── 19, 20, 21. ambiguity and provider failure ───────────────────────────────

@pytest.mark.asyncio
async def test_several_square_matches_create_nothing_and_bind_nothing():
    store, sq = Store(), Square(existing=[{"id": "A"}, {"id": "B"}, {"id": "C"}])
    status, cid = await resolve(store, sq)
    assert (status, cid) == (ci.AMBIGUOUS, None)
    assert sq.creates == 0
    row = await store.get_mapping(T1, "square", IE)
    assert row["provider_customer_id"] is None, "picking one deterministically is not picking correctly"


@pytest.mark.asyncio
async def test_ambiguity_releases_the_claim_to_null():
    store, sq = Store(), Square(existing=[{"id": "A"}, {"id": "B"}])
    await resolve(store, sq)
    row = await store.get_mapping(T1, "square", IE)
    assert row["claim_token"] is None


@pytest.mark.asyncio
async def test_a_failed_provider_search_never_becomes_a_creation():
    """A search that errored is not a search that found nothing."""
    store, sq = Store(), Square(search_error=RuntimeError("connection reset"))
    status, cid = await resolve(store, sq)
    assert (status, cid) == (ci.FAILED, None)
    assert sq.creates == 0


@pytest.mark.asyncio
async def test_a_definitive_provider_rejection_releases_the_claim():
    store, sq = Store(), Square(create_returns_none=True)
    status, _ = await resolve(store, sq)
    assert status == ci.FAILED
    row = await store.get_mapping(T1, "square", IE)
    assert row["claim_token"] is None, "nothing exists to be idempotent about"


# ── 22. finalize ownership ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_finalize_with_the_wrong_token_never_overwrites():
    store = Store()
    row = await store.try_create_claim(T1, "square", IE, "mine")
    assert await store.finalize_mapping_cas(row["id"], "mine", "SQ-FIRST") is True
    assert await store.finalize_mapping_cas(row["id"], "mine", "SQ-SECOND") is False
    assert store.rows[row["id"]]["provider_customer_id"] == "SQ-FIRST"


# ── 15 & 16. W5.2 name protections still hold ────────────────────────────────

@pytest.mark.asyncio
async def test_the_create_payload_is_phone_and_key_only():
    """1. A stable key is only half of idempotency — the retry must also be the
    same request. So the body carries nothing but the two values that provably
    survive takeover, crash and a later call."""
    store, sq = Store(), Square()
    await resolve(store, sq)
    row = await store.get_mapping(T1, "square", IE)
    assert sq.payloads == [{"phone": IE, "given_name": "", "idempotency_key": str(row["id"])}]


def test_the_resolution_layer_cannot_even_accept_a_name():
    """2 & 3, structurally rather than by assertion: no signature in the idempotent
    path takes a name, so no future edit can quietly reintroduce one."""
    import inspect
    from services import square_booking
    assert "given_name" not in inspect.signature(ci.resolve_customer_id).parameters
    assert "given_name" not in inspect.signature(square_booking.resolve_customer).parameters
    assert "given_name" not in inspect.getsource(ci._reconcile)


@pytest.mark.asyncio
async def test_a_changed_caller_name_cannot_alter_the_create_payload():
    """4. "Daniel" on the first attempt, "Dan" after takeover. The tool layer now
    has no way to pass either into creation, so both attempts are byte-identical."""
    store, sq = Store(), Square()
    row = await store.try_create_claim(T1, "square", IE, "worker-A")
    key = str(row["id"])
    await sq.create_customer("tok", phone=IE, idempotency_key=key)      # A, as "Daniel"
    store.mark_stale(row["id"])
    sq.customers = []                                                    # search still blind

    with install(store):                                                 # B, as "Dan"
        status, cid = await ci.resolve_customer_id(
            tenant_id=T1, token="tok", phone=IE, square=sq)

    assert status == ci.OK and cid == "SQ-1"
    assert sq.payloads[0] == sq.payloads[1], "the replay must be the same logical request"
    assert len(sq.by_key) == 1, "one Square customer"


@pytest.mark.asyncio
async def test_a_name_becoming_available_later_cannot_alter_the_payload():
    """5. First attempt had no name; by the takeover a lead row has filled one in.
    Identity creation never sees either."""
    store, sq = Store(), Square()
    row = await store.try_create_claim(T1, "square", IE, "worker-A")
    await sq.create_customer("tok", phone=IE, idempotency_key=str(row["id"]))
    store.mark_stale(row["id"])
    sq.customers = []
    with install(store):
        status, cid = await ci.resolve_customer_id(
            tenant_id=T1, token="tok", phone=IE, square=sq)
    assert (status, cid) == (ci.OK, "SQ-1")
    assert {p["given_name"] for p in sq.payloads} == {""}
    assert len({p["idempotency_key"] for p in sq.payloads}) == 1


@pytest.mark.asyncio
async def test_a_mapped_caller_with_a_new_name_triggers_no_provider_call():
    """6. Once mapped, a different name is simply not a reason to talk to Square."""
    store, sq = Store(), Square()
    await resolve(store, sq)
    sq2 = Square()
    status, cid = await resolve(store, sq2)
    assert (status, cid) == (ci.OK, "SQ-1")
    assert sq2.searches == 0 and sq2.creates == 0


@pytest.mark.asyncio
async def test_the_appointment_record_still_keeps_the_caller_name():
    """7. W5.2 is untouched: the name still reaches the OpenLines appointment even
    though it never reaches Square. Dropping it from identity must not drop it
    from our own records."""
    from routers import tools
    from services import slot_offers

    offer = {"tenant_location_id": "loc-cork", "provider_location_id": "L0Q8GTAZCHD42",
             "service_variation_id": "V1", "service_variation_version": 1,
             "start_at_utc": "2026-10-01T13:00:00Z", "team_member_id": "TM1",
             "service_name": "Consultation", "duration_minutes": 60}
    adopted = [{"id": "loc-cork", "name": "Cork", "active": True, "booking_enabled": True}]
    insert = AsyncMock()

    with patch("services.call_location.get_or_create",
               new=AsyncMock(return_value={"vapi_call_id": "c1", "active_location_id": "loc-cork"})), \
         patch("services.slot_offers.resolve_for_booking",
               new=AsyncMock(return_value=(slot_offers.OK, offer))), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
         patch("services.square_booking.resolve_customer",
               new=AsyncMock(return_value=(ci.OK, "SQ-1"))), \
         patch("services.square_booking.resolve_slot", new=AsyncMock(return_value={
             "team_member_id": "TM1", "service_variation_version": 1,
             "duration_minutes": 60, "start_at": "2026-10-01T13:00:00Z"})), \
         patch("services.square_booking.create_booking",
               new=AsyncMock(return_value={"id": "BK1", "status": "ACCEPTED"})), \
         patch("services.slot_offers.mark_consumed", new=AsyncMock()), \
         patch("db.supabase.insert_appointment", new=insert), \
         patch("services.analytics.capture"):
        await tools._multi_location_book(
            "tc-1", "c1", {"id": T1}, T1, {"slot_ref": "slot_1"},
            caller_name=REAL_NAME, caller_phone=IE, adopted=adopted)

    assert insert.await_args.args[0]["caller_name"] == REAL_NAME


def test_the_low_level_create_still_strips_placeholders_itself():
    """W5.2's sink guard must survive W6B's refactor of this function."""
    import inspect
    from services import square_booking
    src = inspect.getsource(square_booking.create_customer)
    assert "caller_identity.is_placeholder_name" in src


# ── 24. the booking path still gets a usable id ──────────────────────────────

@pytest.mark.asyncio
async def test_the_multi_location_booking_path_receives_a_usable_customer_id():
    from routers import tools
    from services import slot_offers

    offer = {"tenant_location_id": "loc-cork", "provider_location_id": "L0Q8GTAZCHD42",
             "service_variation_id": "V1", "service_variation_version": 1,
             "start_at_utc": "2026-10-01T13:00:00Z", "team_member_id": "TM1",
             "service_name": "Consultation", "duration_minutes": 60}
    adopted = [{"id": "loc-cork", "name": "Cork", "active": True, "booking_enabled": True}]
    store, sq = Store(), Square()
    create = AsyncMock(return_value={"id": "BK1", "status": "ACCEPTED"})

    with install(store), \
         patch("services.call_location.get_or_create",
               new=AsyncMock(return_value={"vapi_call_id": "c1", "active_location_id": "loc-cork"})), \
         patch("services.slot_offers.resolve_for_booking",
               new=AsyncMock(return_value=(slot_offers.OK, offer))), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
         patch("services.square_booking.search_customers_by_phone",
               new=AsyncMock(side_effect=sq.search_customers_by_phone)), \
         patch("services.square_booking.create_customer",
               new=AsyncMock(side_effect=sq.create_customer)), \
         patch("services.square_booking.resolve_slot", new=AsyncMock(return_value={
             "team_member_id": "TM1", "service_variation_version": 1,
             "duration_minutes": 60, "start_at": "2026-10-01T13:00:00Z"})), \
         patch("services.square_booking.create_booking", new=create), \
         patch("services.slot_offers.mark_consumed", new=AsyncMock()), \
         patch("db.supabase.insert_appointment", new=AsyncMock()), \
         patch("services.analytics.capture"):
        out = await tools._multi_location_book(
            "tc-1", "c1", {"id": T1}, T1, {"slot_ref": "slot_1"},
            caller_name=REAL_NAME, caller_phone=IE, adopted=adopted)

    assert create.await_count == 1
    assert create.await_args.kwargs["customer_id"] == "SQ-1"
    assert "confirmed" in out["results"][0]["result"].lower()


@pytest.mark.asyncio
async def test_customer_ambiguity_refuses_the_booking_rather_than_guessing():
    from routers import tools
    from services import slot_offers

    offer = {"tenant_location_id": "loc-cork", "provider_location_id": "L0Q8GTAZCHD42",
             "service_variation_id": "V1", "start_at_utc": "2026-10-01T13:00:00Z",
             "team_member_id": "TM1", "service_name": "Consultation"}
    adopted = [{"id": "loc-cork", "name": "Cork", "active": True, "booking_enabled": True}]
    create = AsyncMock()

    with patch("services.call_location.get_or_create",
               new=AsyncMock(return_value={"vapi_call_id": "c1", "active_location_id": "loc-cork"})), \
         patch("services.slot_offers.resolve_for_booking",
               new=AsyncMock(return_value=(slot_offers.OK, offer))), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
         patch("services.square_booking.resolve_slot", new=AsyncMock(return_value={
             "team_member_id": "TM1", "start_at": "2026-10-01T13:00:00Z"})), \
         patch("services.square_booking.resolve_customer",
               new=AsyncMock(return_value=(ci.AMBIGUOUS, None))), \
         patch("services.square_booking.create_booking", new=create):
        out = await tools._multi_location_book(
            "tc-1", "c1", {"id": T1}, T1, {"slot_ref": "slot_1"},
            caller_name="", caller_phone=IE, adopted=adopted)

    create.assert_not_awaited()
    spoken = out["results"][0]["result"].lower()
    assert "several customer records" in spoken
    for word in ("confirmed", "booked"):
        assert f"is {word}" not in spoken


# ── the HTTP boundary ────────────────────────────────────────────────────────

class _Captured:
    """Intercepts httpx at the point square_booking hands it a body, so the
    assertion is about the outgoing JSON rather than about Python kwargs."""

    def __init__(self):
        self.bodies: list[dict] = []
        self.n = 0

    def client(self):
        outer = self

        class _Resp:
            def __init__(self, payload):
                self._p, self.is_success, self.status_code, self.text = payload, True, 200, ""

            def json(self):
                return self._p

            def raise_for_status(self):
                pass

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, **kw):
                if url.endswith("/v2/customers/search"):
                    return _Resp({"customers": []})
                outer.bodies.append(kw["json"])          # the literal outgoing body
                # Square dedupes on the key: the same key yields the same customer.
                key = kw["json"].get("idempotency_key")
                return _Resp({"customer": {"id": f"SQ-{key}"}})

        return _Client


@pytest.mark.asyncio
async def test_the_outgoing_http_body_is_key_and_phone_only():
    """The claim the report made, checked where it is actually true or false.

    given_name="" never reaches the wire because the payload dict only gains the
    field when the name is truthy — but that is a property of the serialization,
    not of the call signature, so it has to be asserted at the boundary.
    """
    from services import square_booking
    cap = _Captured()
    store = Store()
    row = await store.try_create_claim(T1, "square", IE, "worker-A")
    row_uuid = str(row["id"])

    with patch("services.square_booking.httpx.AsyncClient", cap.client()):
        cid = await square_booking.create_customer(
            "tok", phone=IE, idempotency_key=row_uuid)

    assert cap.bodies == [{"phone_number": IE, "idempotency_key": row_uuid}]
    assert "given_name" not in cap.bodies[0]
    assert cid == f"SQ-{row_uuid}"


@pytest.mark.asyncio
async def test_an_empty_name_is_omitted_from_the_wire_not_sent_as_empty():
    from services import square_booking
    cap = _Captured()
    with patch("services.square_booking.httpx.AsyncClient", cap.client()):
        await square_booking.create_customer("tok", phone=IE, given_name="", idempotency_key="K")
    assert cap.bodies[0] == {"phone_number": IE, "idempotency_key": "K"}
    assert "given_name" not in cap.bodies[0]


@pytest.mark.asyncio
async def test_a_placeholder_name_is_omitted_from_the_wire_too():
    """W5.2's sink guard, asserted on the body rather than on the argument. The
    legacy no-tenant shim still passes names, so this protection must stay real."""
    from services import square_booking
    cap = _Captured()
    with patch("services.square_booking.httpx.AsyncClient", cap.client()):
        await square_booking.create_customer(
            "tok", phone=IE, given_name="Returning Caller", idempotency_key="K")
    assert "given_name" not in cap.bodies[0]


@pytest.mark.asyncio
async def test_a_legacy_real_name_still_reaches_the_wire():
    """The other half: W6B must not silently disarm the legacy path's ability to
    send a genuine name."""
    from services import square_booking
    cap = _Captured()
    with patch("services.square_booking.httpx.AsyncClient", cap.client()):
        await square_booking.create_customer(
            "tok", phone=IE, given_name=REAL_NAME, idempotency_key="K")
    assert cap.bodies[0]["given_name"] == REAL_NAME


@pytest.mark.asyncio
async def test_attempt_A_and_takeover_B_send_byte_identical_http_bodies():
    """The whole point, end to end at the wire.

    A resolves while the caller is known as "Daniel"; A crashes; B takes over while
    the caller is known as "Dan". Both drive the real resolution path, and the two
    captured HTTP bodies must be equal — not merely equivalent.
    """
    from services import square_booking
    import json as _json

    cap = _Captured()
    store = Store()

    with install(store), patch("services.square_booking.httpx.AsyncClient", cap.client()):
        # Attempt A — the tool layer knows this caller as "Daniel"; the resolution
        # layer has no parameter through which that could travel.
        await ci.resolve_customer_id(
            tenant_id=T1, token="tok", phone=IE, square=square_booking)

        row = await store.get_mapping(T1, "square", IE)
        row_uuid = str(row["id"])
        # A "crashes": undo the finalize and abandon the claim.
        store.rows[row["id"]]["provider_customer_id"] = None
        store.rows[row["id"]]["claim_token"] = "worker-A"
        store.mark_stale(row["id"])

        # Attempt B — the caller is now known as "Dan".
        status, cid = await ci.resolve_customer_id(
            tenant_id=T1, token="tok", phone=IE, square=square_booking)

    assert status == ci.OK
    assert len(cap.bodies) == 2, f"expected two CreateCustomer bodies, got {len(cap.bodies)}"
    body_a, body_b = cap.bodies
    assert body_a == body_b, f"A={body_a} B={body_b}"
    assert _json.dumps(body_a, sort_keys=True) == _json.dumps(body_b, sort_keys=True)
    assert body_a == {"phone_number": IE, "idempotency_key": row_uuid}
    assert "given_name" not in body_a and "given_name" not in body_b
    assert cid == f"SQ-{row_uuid}", "Square dedupes on the key, so B gets A's customer"
