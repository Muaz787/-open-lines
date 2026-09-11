"""
W6A2 prerequisite C2 — let a future frozen operation supply its own key.

create_booking generated str(uuid.uuid4()) internally, so there was no way for a
durable reschedule operation to replay its own CreateBooking. The key column
already exists on appointment_reschedule_operations; it had nowhere to go.

The change is deliberately one-directional. Ordinary booking keeps a fresh key
per request, because its body is rebuilt from a live resolve_slot and a retry is
therefore a DIFFERENT request — a stable key over a mutable body is worse than no
stable key, since it converts a harmless duplicate into an idempotency conflict.
Only a caller that can also freeze the body may supply one.

These tests pin both halves: the default stays random, and a supplied key is used
exactly as given.
"""
import json
import uuid
from unittest.mock import patch

import pytest

from services import square_booking as sb

ARGS = dict(location_id="L0Q8GTAZCHD42", start_at_iso="2026-11-01T13:00:00Z",
            customer_id="CUST1", team_member_id="TM1",
            service_variation_id="VAR1", service_variation_version=1789040442821,
            duration_minutes=60, note="Booked via Open Lines AI receptionist — Consultation")


class _Captured:
    """Intercepts httpx where square_booking hands it a body, so assertions are
    about the outgoing JSON rather than about Python arguments."""

    def __init__(self, status=200, payload=None):
        self.bodies: list[dict] = []
        self.status = status
        self.payload = payload if payload is not None else {
            "booking": {"id": "BK1", "status": "ACCEPTED", "version": 0,
                        "location_id": "L0Q8GTAZCHD42"}}

    def client(self):
        outer = self

        class _Resp:
            def __init__(self, status, payload):
                self.status_code = status
                self.is_success = 200 <= status < 300
                self._p, self.text = payload, "err"

            def json(self):
                return self._p

            def raise_for_status(self):
                raise RuntimeError(f"HTTP {self.status_code}")

        class _C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, **kw):
                outer.bodies.append(kw["json"])
                return _Resp(outer.status, outer.payload)

        return patch("services.square_booking.httpx.AsyncClient", _C)


# ── 1 & 2. the default stays random ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_no_supplied_key_still_generates_a_uuid():
    cap = _Captured()
    with cap.client():
        await sb.create_booking("tok", **ARGS)
    key = cap.bodies[0]["idempotency_key"]
    uuid.UUID(key)                       # parses, so it is a real UUID
    assert len(cap.bodies) == 1


@pytest.mark.asyncio
async def test_2_two_ordinary_calls_get_different_keys():
    """Ordinary booking must NOT become stable-idempotent by accident: two
    bookings of the same slot are two logical requests."""
    cap = _Captured()
    with cap.client():
        await sb.create_booking("tok", **ARGS)
        await sb.create_booking("tok", **ARGS)
    assert cap.bodies[0]["idempotency_key"] != cap.bodies[1]["idempotency_key"]


# ── 3, 4, 5. a supplied key is used exactly ──────────────────────────────────

@pytest.mark.asyncio
async def test_3_a_supplied_key_is_sent_unchanged():
    cap = _Captured()
    supplied = "5f2b9c1e-0000-4000-8000-abcdefabcdef"
    with cap.client():
        await sb.create_booking("tok", idempotency_key=supplied, **ARGS)
    assert cap.bodies[0]["idempotency_key"] == supplied


@pytest.mark.asyncio
async def test_4_repeated_calls_with_the_same_key_send_the_same_key():
    """The property recovery depends on: replay is the same logical request."""
    cap = _Captured()
    supplied = str(uuid.uuid4())
    with cap.client():
        await sb.create_booking("tok", idempotency_key=supplied, **ARGS)
        await sb.create_booking("tok", idempotency_key=supplied, **ARGS)
    assert cap.bodies[0]["idempotency_key"] == cap.bodies[1]["idempotency_key"] == supplied


@pytest.mark.asyncio
async def test_5_a_uuid_object_crosses_the_boundary_as_its_canonical_string():
    """appointment_reschedule_operations.provider_idempotency_key is a uuid; the
    JSON boundary needs its canonical text form, unchanged."""
    cap = _Captured()
    u = uuid.UUID("7a642233-c541-4a6d-9e28-91b02cb934dd")
    with cap.client():
        await sb.create_booking("tok", idempotency_key=u, **ARGS)
    assert cap.bodies[0]["idempotency_key"] == "7a642233-c541-4a6d-9e28-91b02cb934dd"
    assert isinstance(cap.bodies[0]["idempotency_key"], str)


@pytest.mark.asyncio
async def test_5b_a_supplied_string_is_never_canonicalised_or_trimmed():
    """Silently repairing a caller's key would destroy the one property it exists
    to provide, so an odd-looking key is sent as-is rather than normalised."""
    cap = _Captured()
    odd = "7A642233-C541-4A6D-9E28-91B02CB934DD"      # upper case
    with cap.client():
        await sb.create_booking("tok", idempotency_key=odd, **ARGS)
    assert cap.bodies[0]["idempotency_key"] == odd


# ── 6. the narrow validation rule ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "   ", "\t"])
async def test_6_an_empty_supplied_key_is_rejected_not_replaced(bad):
    """Substituting a fresh UUID for an empty key would be a silent replacement —
    the caller believes it has a stable key and does not."""
    cap = _Captured()
    with cap.client():
        with pytest.raises(ValueError):
            await sb.create_booking("tok", idempotency_key=bad, **ARGS)
    assert cap.bodies == [], "nothing may be sent when the key is invalid"


# ── 7. request-body determinism ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_7_identical_arguments_plus_one_key_produce_identical_json():
    """The determinism audit, executable. idempotency_key was the ONLY internally
    generated value in this body — no now(), no random, no inferred defaults — so
    pinning it makes the whole request reproducible."""
    cap = _Captured()
    supplied = str(uuid.uuid4())
    with cap.client():
        await sb.create_booking("tok", idempotency_key=supplied, **ARGS)
        await sb.create_booking("tok", idempotency_key=supplied, **ARGS)
    a, b = cap.bodies
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@pytest.mark.asyncio
async def test_7b_the_body_carries_exactly_the_expected_provider_fields():
    cap = _Captured()
    with cap.client():
        await sb.create_booking("tok", idempotency_key="K", **ARGS)
    body = cap.bodies[0]
    assert set(body) == {"idempotency_key", "booking"}
    assert set(body["booking"]) == {"location_id", "start_at", "customer_id",
                                    "appointment_segments", "customer_note"}
    seg = body["booking"]["appointment_segments"][0]
    assert set(seg) == {"team_member_id", "service_variation_id",
                        "service_variation_version", "duration_minutes"}


@pytest.mark.asyncio
async def test_7c_optional_segment_fields_are_omitted_not_nulled():
    """Omission vs null changes the bytes, so it has to be deterministic too."""
    cap = _Captured()
    args = dict(ARGS, service_variation_version=None, duration_minutes=None, note="")
    with cap.client():
        await sb.create_booking("tok", idempotency_key="K", **args)
    seg = cap.bodies[0]["booking"]["appointment_segments"][0]
    assert set(seg) == {"team_member_id", "service_variation_id"}
    assert "customer_note" not in cap.bodies[0]["booking"]


# ── 8, 9, 10. ordinary booking is untouched ──────────────────────────────────

def test_8_no_production_caller_passes_an_idempotency_key_yet():
    import ast
    import inspect
    from routers import tools
    for fn in (tools._multi_location_book, tools._square_book_appointment):
        for node in ast.walk(ast.parse(inspect.getsource(fn).lstrip())):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("create_booking"):
                kws = {k.arg for k in node.keywords}
                assert "idempotency_key" not in kws, f"{fn.__name__} must not pin a key yet"


def test_9_the_slot_claim_still_precedes_create_booking():
    import inspect
    from routers import tools
    src = inspect.getsource(tools._multi_location_book)
    assert src.index("slot_offers.claim(") < src.index("square_booking.create_booking(")


def test_10_the_unknown_outcome_branch_still_does_not_release_or_retry():
    """Prerequisite A's rule survives: an unknown outcome keeps the slot and never
    re-issues CreateBooking — which is exactly why ordinary booking must not gain
    a stable key here."""
    import inspect
    from routers import tools
    src = inspect.getsource(tools._multi_location_book)
    unknown = src.split("BookingOutcomeUnknown")[1].split("except Exception")[0]
    assert "slot_offers.release" not in unknown
    assert "create_booking(" not in unknown


# ── 11 & 12. response identity and the C1 taxonomy ───────────────────────────

@pytest.mark.asyncio
async def test_11_a_successful_response_still_exposes_the_provider_booking_id():
    cap = _Captured()
    with cap.client():
        booking = await sb.create_booking("tok", idempotency_key="K", **ARGS)
    assert booking["id"] == "BK1"
    assert booking["status"] == "ACCEPTED"
    assert booking["version"] == 0


@pytest.mark.asyncio
async def test_12_a_5xx_is_still_an_unknown_outcome_with_a_supplied_key():
    cap = _Captured(status=503)
    with cap.client():
        with pytest.raises(sb.BookingOutcomeUnknown):
            await sb.create_booking("tok", idempotency_key="K", **ARGS)


@pytest.mark.asyncio
async def test_12b_a_4xx_is_still_a_definitive_rejection_with_a_supplied_key():
    cap = _Captured(status=400)
    with cap.client():
        with pytest.raises(RuntimeError) as e:
            await sb.create_booking("tok", idempotency_key="K", **ARGS)
    assert not isinstance(e.value, sb.BookingOutcomeUnknown)


@pytest.mark.asyncio
async def test_12c_transport_failure_is_still_unknown_with_a_supplied_key():
    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            raise TimeoutError("dropped")

    with patch("services.square_booking.httpx.AsyncClient", _C):
        with pytest.raises(sb.BookingOutcomeUnknown):
            await sb.create_booking("tok", idempotency_key="K", **ARGS)
