"""
GET /payments/processor — which processor took a payment, for /payment-success.

MOCKED: the payments table and Square are faked. The answer must come only from
our own payment record, found by our payment id (Square's return link) or the
Stripe Checkout Session id (Stripe's return link). Anything else is neutral.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from routers import payments
from services import square_service

REF = "7acfb74c-f58a-4923-978c-b2877a6021e3"
SESSION = "cs_test_a1B2c3D4e5F6g7H8"
ROWS = {("id", REF): "square", ("checkout_session_id", SESSION): "stripe",
        ("id", "11111111-1111-4111-8111-111111111111"): None}


class Req:
    client = type("c", (), {"host": "127.0.0.1"})()
    headers: dict = {}


async def ask(**query):
    calls = []

    async def provider(column, value):
        calls.append((column, value))
        return ROWS.get((column, value))
    with patch("db.supabase.get_payment_provider", new=AsyncMock(side_effect=provider)):
        res = await payments.payment_processor(Req(), **query)
    assert res.headers["cache-control"] == "no-store"
    return json.loads(res.body)["processor"], calls


async def test_square_payment_by_our_ref():
    assert await ask(ref=REF) == ("square", [("id", REF)])


async def test_stripe_payment_by_checkout_session():
    assert await ask(session_id=SESSION) == ("stripe", [("checkout_session_id", SESSION)])


@pytest.mark.parametrize("query", [
    {}, {"ref": "00000000-0000-4000-8000-000000000000"}, {"session_id": "cs_test_unknownunknown"},
    {"ref": "not-a-uuid"}, {"ref": REF.upper()}, {"session_id": "pi_123"},
    {"session_id": "cs_live_" + "a" * 300}, {"ref": REF + "' or 1=1"},
])
async def test_anything_else_is_neutral(query):
    processor, calls = await ask(**query)
    assert processor is None
    assert all(v in (query.get("ref"), query.get("session_id")) for _, v in calls)


async def test_malformed_ids_are_never_looked_up():
    for q in ({"ref": "not-a-uuid"}, {"session_id": "pi_123"}, {"ref": REF + "x"}):
        assert (await ask(**q))[1] == []


async def test_a_lookup_failure_is_neutral():
    with patch("db.supabase.get_payment_provider", new=AsyncMock(side_effect=RuntimeError("db down"))):
        res = await payments.payment_processor(Req(), ref=REF)
    assert json.loads(res.body) == {"processor": None}


async def test_an_unknown_stored_provider_is_neutral():
    with patch("db.supabase.get_payment_provider", new=AsyncMock(return_value="paypal")):
        res = await payments.payment_processor(Req(), ref=REF)
    assert json.loads(res.body) == {"processor": None}


async def test_the_square_return_link_carries_our_payment_id():
    sent = {}

    class Resp:
        status_code = 200
        is_success = True

        def raise_for_status(self):
            pass

        def json(self):
            return {"payment_link": {"id": "PL", "order_id": "ORD", "url": "https://square.link/u/x"}}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **k):
            sent.update(json)
            return Resp()
    with patch.object(square_service.httpx, "AsyncClient", new=lambda *a, **k: Client()):
        await square_service.create_payment_link(
            access_token="t", location_id="L", amount_cents=100, currency="cad", name="Deposit",
            note="n", tenant_id="T", payment_id=REF, expiry_minutes=120)
    assert sent["checkout_options"]["redirect_url"].endswith(f"/payment-success?ref={REF}")
