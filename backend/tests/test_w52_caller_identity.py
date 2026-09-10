"""
W5.2 — the live call that booked correctly and still wrote down the wrong person.

Call 01a08ca0-… booked a Cork consultation exactly right: one CreateBooking, right
location, right time. Then it created a Square customer named "Returning Caller".

The chain is worth stating because it is not a model failure so much as an echo:
the caller was recognised, their lead row had no name, so assistant-request put
"RETURNING CALLER (name not captured yet)" into the system prompt — and when the
model was asked for a caller_name, it handed back the phrase it had just read.

A name describes a person. "Returning Caller" describes a conversational state.
Persisting the second as the first produces a customer file nobody can search and
a confirmation addressed to nobody. These tests hold that line at every sink.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import caller_identity as ci

REAL_NAME = "Aoife Kelly"
PHONE = "+353871234567"


# ── 1-4. placeholders are not identities ─────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Returning Caller",          # 1. the exact string the live call produced
    "returning caller",          # 2. case
    "  Returning   CALLER  ",    # 2. whitespace, internal and surrounding
    "Unknown Caller",            # 3.
    "Customer",                  # 4.
    "Caller", "Unknown", "Guest", "Anonymous", "Not Provided", "N/A", "n/a", "None",
])
def test_placeholder_names_are_rejected(name):
    assert ci.is_placeholder_name(name) is True
    assert ci.resolve_caller_name(name) == ""


def test_empty_and_missing_are_treated_as_no_name():
    for empty in ("", "   ", None):
        assert ci.is_placeholder_name(empty) is True
        assert ci.resolve_caller_name(empty) == ""


# ── 5. real names survive ────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Aoife Kelly", "Niamh", "Seán Ó Briain", "Mary-Kate O'Hara", "Wei Zhang", "N. Byrne",
])
def test_real_names_survive_untouched(name):
    assert ci.is_placeholder_name(name) is False
    assert ci.resolve_caller_name(name) == name.strip()


@pytest.mark.parametrize("name", ["Mark Guest", "Anonymous Achebe", "Customer Nwosu"])
def test_a_placeholder_word_inside_a_real_name_is_not_a_placeholder(name):
    """Matching is against the whole normalized string, never a substring. Someone
    actually called Guest must not lose their name to this rule."""
    assert ci.is_placeholder_name(name) is False
    assert ci.resolve_caller_name(name) == name


# ── 6. trust precedence ──────────────────────────────────────────────────────

def test_trusted_history_is_used_when_the_model_offers_a_placeholder():
    assert ci.resolve_caller_name("Returning Caller", REAL_NAME) == REAL_NAME


def test_a_name_given_on_this_call_beats_stored_history():
    assert ci.resolve_caller_name("Niamh Byrne", REAL_NAME) == "Niamh Byrne"


def test_two_placeholders_yield_no_name_rather_than_the_lesser_evil():
    assert ci.resolve_caller_name("Returning Caller", "Unknown") == ""


def test_no_name_is_ever_derived_from_anything_else():
    """There is no fourth rung on the ladder. Phone, business name and greeting are
    all plausible sources of a string and none of them is a person's name."""
    assert ci.resolve_caller_name("Customer", None) == ""
    assert PHONE not in ci.resolve_caller_name("Customer", None)


@pytest.mark.asyncio
async def test_the_tool_layer_consults_stored_history_before_giving_up():
    from routers import tools
    with patch("db.supabase.get_lead_by_phone",
               new=AsyncMock(return_value={"name": REAL_NAME})) as lead:
        got = await tools._trusted_caller_name("t-1", "Returning Caller", PHONE)
    assert got == REAL_NAME
    lead.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_real_supplied_name_does_not_trigger_a_history_lookup():
    from routers import tools
    with patch("db.supabase.get_lead_by_phone", new=AsyncMock()) as lead:
        assert await tools._trusted_caller_name("t-1", "Niamh", PHONE) == "Niamh"
    lead.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_history_lookup_yields_no_name_and_does_not_raise():
    """Booking must not depend on reading history. Its absence means we hold no
    name, which is the right answer rather than a degraded one."""
    from routers import tools
    with patch("db.supabase.get_lead_by_phone", new=AsyncMock(side_effect=RuntimeError("db down"))):
        assert await tools._trusted_caller_name("t-1", "Returning Caller", PHONE) == ""


# ── 7. the Square customer ───────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, payload, ok=True):
        self._p, self.is_success, self.status_code, self.text = payload, ok, 200, ""

    def json(self):
        return self._p

    def raise_for_status(self):
        if not self.is_success:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Records what we actually send to Square."""
    posts: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        _FakeClient.posts.append((url, kw.get("json")))
        if "customers/search" in url:
            return _FakeResponse({"customers": []})
        return _FakeResponse({"customer": {"id": "CUST-NEW"}})


def _capture():
    _FakeClient.posts = []
    return patch("services.square_booking.httpx.AsyncClient", _FakeClient)


@pytest.mark.asyncio
async def test_no_name_creates_a_square_customer_on_the_phone_alone():
    """The fix for the live defect: phone is the identity key, and the record
    carries no invented name."""
    from services import square_booking
    with _capture():
        cid = await square_booking.find_or_create_customer("tok", given_name="", phone=PHONE)
    assert cid == "CUST-NEW"
    create = [p for u, p in _FakeClient.posts if u.endswith("/v2/customers")][0]
    assert create == {"phone_number": PHONE}
    assert "given_name" not in create


@pytest.mark.asyncio
async def test_the_old_caller_fallback_is_gone():
    """find_or_create_customer used to substitute 'Caller' for a missing name — a
    second, quieter source of exactly the defect W5.2 exists to remove."""
    from services import square_booking
    with _capture():
        await square_booking.find_or_create_customer("tok", given_name="", phone=PHONE)
    create = [p for u, p in _FakeClient.posts if u.endswith("/v2/customers")][0]
    assert "Caller" not in str(create)


@pytest.mark.asyncio
async def test_a_real_name_is_still_sent_to_square():
    from services import square_booking
    with _capture():
        await square_booking.find_or_create_customer("tok", given_name=REAL_NAME, phone=PHONE)
    create = [p for u, p in _FakeClient.posts if u.endswith("/v2/customers")][0]
    assert create == {"given_name": REAL_NAME, "phone_number": PHONE}


@pytest.mark.asyncio
async def test_an_existing_customer_is_matched_by_phone_and_never_renamed():
    from services import square_booking

    class _Existing(_FakeClient):
        async def post(self, url, **kw):
            _FakeClient.posts.append((url, kw.get("json")))
            if "customers/search" in url:
                return _FakeResponse({"customers": [{"id": "CUST-OLD"}]})
            raise AssertionError("must not create when one already exists")

    _FakeClient.posts = []
    with patch("services.square_booking.httpx.AsyncClient", _Existing):
        assert await square_booking.find_or_create_customer(
            "tok", given_name="Returning Caller", phone=PHONE) == "CUST-OLD"


@pytest.mark.asyncio
async def test_neither_name_nor_phone_creates_nothing():
    from services import square_booking
    with _capture():
        assert await square_booking.find_or_create_customer("tok", given_name="", phone="") is None
    assert not [p for u, p in _FakeClient.posts if u.endswith("/v2/customers")]


# ── 8. appointment persistence ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_booked_appointment_row_carries_no_placeholder():
    """End to end through the W5 multi-location path, which is what ran live."""
    from routers import tools
    from services import slot_offers

    offer = {"tenant_location_id": "loc-cork", "provider_location_id": "L0Q8GTAZCHD42",
             "service_variation_id": "V1", "service_variation_version": 1,
             "start_at_utc": "2026-09-14T13:00:00Z", "team_member_id": "TM1",
             "service_name": "Consultation", "duration_minutes": 60}
    adopted = [{"id": "loc-cork", "name": "Cork", "active": True, "booking_enabled": True}]
    insert = AsyncMock()

    with patch("services.call_location.get_or_create",
               new=AsyncMock(return_value={"vapi_call_id": "c1", "active_location_id": "loc-cork"})), \
         patch("services.slot_offers.resolve_for_booking",
               new=AsyncMock(return_value=(slot_offers.OK, offer))), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
         patch("services.square_booking.resolve_slot", new=AsyncMock(return_value={
             "team_member_id": "TM1", "service_variation_version": 1,
             "duration_minutes": 60, "start_at": "2026-09-14T13:00:00Z"})), \
         patch("services.square_booking.resolve_customer",
               new=AsyncMock(return_value=("ok", "CUST"))) as cust, \
         patch("services.square_booking.create_booking",
               new=AsyncMock(return_value={"id": "BK1", "status": "ACCEPTED"})), \
         patch("services.slot_offers.claim", new=AsyncMock(return_value=True)), \
         patch("services.slot_offers.release", new=AsyncMock()), \
         patch("services.slot_offers.mark_consumed", new=AsyncMock()), \
         patch("db.supabase.insert_appointment", new=insert), \
         patch("services.analytics.capture"):
        await tools._multi_location_book(
            "tc-1", "c1", {"id": "t-1"}, "t-1", {"slot_ref": "slot_1"},
            caller_name="", caller_phone=PHONE, adopted=adopted)

    row = insert.await_args.args[0]
    assert row["caller_name"] is None, "an absent name must be NULL, not a placeholder"
    assert row["caller_phone"] == PHONE
    # W6B made this stronger than W5.2 could: Square customer creation no longer
    # accepts a name at all, so a placeholder cannot reach it by any route.
    assert "given_name" not in cust.await_args.kwargs


# ── 9. caller phone is untouched by W5.2 ─────────────────────────────────────

def test_trusted_caller_phone_behaviour_is_unchanged():
    from routers import tools
    assert tools.trusted_caller_phone(
        {"message": {"call": {"customer": {"number": PHONE}}}},
        {"caller_phone": "+353000000001"}) == PHONE
    assert tools.trusted_caller_phone({"message": {}}, {"caller_phone": "+00000000000"}) == ""
    assert tools.trusted_caller_phone({"message": {}}, {"caller_phone": PHONE}) == PHONE
    assert tools.trusted_caller_phone({"message": {}}, {}) == ""


# ── 10 & 11. both booking paths still work ───────────────────────────────────

def test_the_name_is_resolved_once_before_either_booking_path():
    """Single-location and multi-location both read the same resolved value, so
    neither can be fixed while the other quietly keeps the placeholder."""
    import inspect
    from routers import tools
    src = inspect.getsource(tools.book_appointment)
    assert "_trusted_caller_name(" in src
    assert 'args.get("caller_name", "")\n' not in src.split("_trusted_caller_name")[0]


@pytest.mark.asyncio
async def test_multi_location_booking_still_succeeds_with_a_real_name():
    from routers import tools
    from services import slot_offers

    offer = {"tenant_location_id": "loc-cork", "provider_location_id": "L0Q8GTAZCHD42",
             "service_variation_id": "V1", "service_variation_version": 1,
             "start_at_utc": "2026-09-14T13:00:00Z", "team_member_id": "TM1",
             "service_name": "Consultation", "duration_minutes": 60}
    adopted = [{"id": "loc-cork", "name": "Cork", "active": True, "booking_enabled": True}]
    insert, create = AsyncMock(), AsyncMock(return_value={"id": "BK1", "status": "ACCEPTED"})

    with patch("services.call_location.get_or_create",
               new=AsyncMock(return_value={"vapi_call_id": "c1", "active_location_id": "loc-cork"})), \
         patch("services.slot_offers.resolve_for_booking",
               new=AsyncMock(return_value=(slot_offers.OK, offer))), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
         patch("services.square_booking.resolve_slot", new=AsyncMock(return_value={
             "team_member_id": "TM1", "service_variation_version": 1,
             "duration_minutes": 60, "start_at": "2026-09-14T13:00:00Z"})), \
         patch("services.square_booking.resolve_customer",
               new=AsyncMock(return_value=("ok", "CUST"))) as cust, \
         patch("services.square_booking.create_booking", new=create), \
         patch("services.slot_offers.claim", new=AsyncMock(return_value=True)), \
         patch("services.slot_offers.release", new=AsyncMock()), \
         patch("services.slot_offers.mark_consumed", new=AsyncMock()), \
         patch("db.supabase.insert_appointment", new=insert), \
         patch("services.analytics.capture"):
        out = await tools._multi_location_book(
            "tc-1", "c1", {"id": "t-1"}, "t-1", {"slot_ref": "slot_1"},
            caller_name=REAL_NAME, caller_phone=PHONE, adopted=adopted)

    assert create.await_count == 1
    assert "given_name" not in cust.await_args.kwargs, "identity creation is phone-only"
    assert insert.await_args.args[0]["caller_name"] == REAL_NAME, "our own record keeps the name"
    assert "confirmed" in out["results"][0]["result"].lower()


@pytest.mark.asyncio
async def test_the_square_customer_sink_rejects_a_placeholder_on_its_own():
    """Defence in depth, and not hypothetical: a probe against the live Square API
    called this function directly with "Returning Caller" and it created exactly the
    record W5.2 exists to prevent. The tool layer resolves names correctly, but this
    is the last point before the value becomes permanent, so it re-checks."""
    from services import square_booking
    with _capture():
        await square_booking.find_or_create_customer(
            "tok", given_name="Returning Caller", phone=PHONE)
    create = [p for u, p in _FakeClient.posts if u.endswith("/v2/customers")][0]
    assert create == {"phone_number": PHONE}
    assert "Returning Caller" not in str(create)
