"""
Tests for the caller-initiated cancellation refund policy:
 - refund_eligible() time-window math
 - issue_provider_refund() provider dispatch + failure handling
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# refund_eligible
# ---------------------------------------------------------------------------

from services.refunds import refund_eligible

NOW = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)


def test_eligible_well_outside_window():
    appt = NOW + timedelta(hours=48)
    assert refund_eligible(appt, 24, now=NOW) is True


def test_not_eligible_inside_window():
    appt = NOW + timedelta(hours=10)
    assert refund_eligible(appt, 24, now=NOW) is False


def test_eligible_exactly_at_boundary():
    appt = NOW + timedelta(hours=24)
    assert refund_eligible(appt, 24, now=NOW) is True


def test_just_inside_boundary_not_eligible():
    appt = NOW + timedelta(hours=24) - timedelta(minutes=1)
    assert refund_eligible(appt, 24, now=NOW) is False


def test_always_refund_policy_zero_hours():
    appt = NOW + timedelta(minutes=5)
    assert refund_eligible(appt, 0, now=NOW) is True


def test_never_auto_refund_large_threshold():
    appt = NOW + timedelta(hours=100)
    assert refund_eligible(appt, 9999, now=NOW) is False


def test_past_appointment_not_eligible():
    appt = NOW - timedelta(hours=1)
    assert refund_eligible(appt, 24, now=NOW) is False


def test_none_appt_not_eligible():
    assert refund_eligible(None, 24, now=NOW) is False


# ---------------------------------------------------------------------------
# issue_provider_refund
# ---------------------------------------------------------------------------

STRIPE_PAYMENT = {
    "id": "pay-s", "provider": "stripe", "amount_cents": 2000, "currency": "cad",
    "stripe_account_id": "acct_1", "payment_intent_id": "pi_1",
}
SQUARE_PAYMENT = {
    "id": "pay-q", "provider": "square", "amount_cents": 2000, "currency": "cad",
    "payment_intent_id": "sqpay_1",
}
TENANT = {"id": "t-1", "square_access_token": "enc-token", "stripe_account_id": "acct_1"}


@pytest.mark.asyncio
async def test_issue_refund_stripe_dispatch():
    from services import refunds
    with patch("services.stripe_service.refund_payment", AsyncMock(return_value={"id": "re_1"})) as stripe_refund:
        ok = await refunds.issue_provider_refund(dict(STRIPE_PAYMENT), dict(TENANT))
    assert ok is True
    stripe_refund.assert_awaited_once_with(stripe_account_id="acct_1", payment_intent_id="pi_1")


@pytest.mark.asyncio
async def test_issue_refund_square_dispatch():
    from services import refunds
    with patch("services.square_service.refund_payment", AsyncMock(return_value={"id": "rf_1"})) as sq_refund, \
         patch("services.security.decrypt", return_value="plain-token"):
        ok = await refunds.issue_provider_refund(dict(SQUARE_PAYMENT), dict(TENANT))
    assert ok is True
    sq_refund.assert_awaited_once()
    kwargs = sq_refund.await_args.kwargs
    assert kwargs["square_payment_id"] == "sqpay_1"
    assert kwargs["amount_cents"] == 2000
    assert kwargs["access_token"] == "plain-token"


@pytest.mark.asyncio
async def test_issue_refund_missing_stripe_ids_returns_false():
    from services import refunds
    broken = {**STRIPE_PAYMENT, "payment_intent_id": "", "stripe_account_id": ""}
    tenant_no_acct = {"id": "t-1"}
    with patch("services.stripe_service.refund_payment", AsyncMock()) as stripe_refund:
        ok = await refunds.issue_provider_refund(broken, tenant_no_acct)
    assert ok is False
    stripe_refund.assert_not_awaited()


@pytest.mark.asyncio
async def test_issue_refund_provider_error_returns_false():
    from services import refunds
    with patch("services.stripe_service.refund_payment", AsyncMock(side_effect=Exception("stripe boom"))):
        ok = await refunds.issue_provider_refund(dict(STRIPE_PAYMENT), dict(TENANT))
    assert ok is False
