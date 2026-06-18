"""
Tests for the deposit refund handlers (Stripe charge.refunded and Square
payment.updated carrying refunded_money). Covers the shared _process_refund
logic, idempotency, and provider-specific lookup/dispatch.
"""
import pytest
from unittest.mock import AsyncMock, patch


PAYMENT = {
    "id": "pay-1",
    "tenant_id": "tenant-1",
    "appointment_id": "appt-1",
    "amount_cents": 2000,
    "currency": "cad",
    "status": "succeeded",
    "caller_phone": "+16475551234",
    "caller_name": "John Doe",
    "service": "apartment viewing",
}

TENANT = {"id": "tenant-1", "business_name": "Shahid Real Estate"}

APPOINTMENT = {"id": "appt-1", "google_event_id": "evt-1", "status": "confirmed"}


def _patches(payment=PAYMENT, appointment=APPOINTMENT, tenant=TENANT):
    """Patch the shared collaborators of _process_refund."""
    return [
        patch("routers.payments.db.update_payment", AsyncMock()),
        patch("routers.payments.db.get_appointment_by_id", AsyncMock(return_value=appointment)),
        patch("routers.payments.db.update_appointment", AsyncMock()),
        patch("routers.payments._cancel_appointment_calendar", AsyncMock()),
        patch("routers.payments._notify_refund", AsyncMock()),
        patch("routers.payments._sms_caller_refund", AsyncMock()),
    ]


# ---------------------------------------------------------------------------
# _process_refund
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_refund_marks_payment_and_cancels_appointment():
    from routers import payments

    with patch("routers.payments.db.update_payment", AsyncMock()) as upd_pay, \
         patch("routers.payments.db.get_appointment_by_id", AsyncMock(return_value=dict(APPOINTMENT))), \
         patch("routers.payments.db.update_appointment", AsyncMock()) as upd_appt, \
         patch("routers.payments._cancel_appointment_calendar", AsyncMock()) as cancel_cal, \
         patch("routers.payments._notify_refund", AsyncMock()) as notify, \
         patch("routers.payments._sms_caller_refund", AsyncMock()) as sms:
        await payments._process_refund(dict(PAYMENT), dict(TENANT))

    # payment marked refunded
    upd_pay.assert_awaited_once()
    assert upd_pay.await_args.args[0] == "pay-1"
    assert upd_pay.await_args.args[1]["status"] == "refunded"
    assert "refunded_at" in upd_pay.await_args.args[1]

    # calendar event removed, appointment cancelled
    cancel_cal.assert_awaited_once()
    upd_appt.assert_awaited_once()
    assert upd_appt.await_args.args[0] == "appt-1"
    assert upd_appt.await_args.args[1] == {"status": "cancelled"}

    # caller + business notified
    notify.assert_awaited_once()
    sms.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_refund_is_idempotent():
    from routers import payments
    already_refunded = {**PAYMENT, "status": "refunded"}

    with patch("routers.payments.db.update_payment", AsyncMock()) as upd_pay, \
         patch("routers.payments.db.update_appointment", AsyncMock()) as upd_appt, \
         patch("routers.payments._notify_refund", AsyncMock()) as notify, \
         patch("routers.payments._sms_caller_refund", AsyncMock()) as sms:
        await payments._process_refund(already_refunded, dict(TENANT))

    upd_pay.assert_not_awaited()
    upd_appt.assert_not_awaited()
    notify.assert_not_awaited()
    sms.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_refund_without_appointment():
    from routers import payments
    no_appt = {**PAYMENT, "appointment_id": None}

    with patch("routers.payments.db.update_payment", AsyncMock()) as upd_pay, \
         patch("routers.payments.db.update_appointment", AsyncMock()) as upd_appt, \
         patch("routers.payments._cancel_appointment_calendar", AsyncMock()) as cancel_cal, \
         patch("routers.payments._notify_refund", AsyncMock()), \
         patch("routers.payments._sms_caller_refund", AsyncMock()):
        await payments._process_refund(no_appt, dict(TENANT))

    upd_pay.assert_awaited_once()
    cancel_cal.assert_not_awaited()
    upd_appt.assert_not_awaited()


# ---------------------------------------------------------------------------
# Stripe: _handle_charge_refunded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stripe_charge_refunded_looks_up_by_payment_intent():
    from routers import payments

    with patch("routers.payments.db.get_payment_by_payment_intent", AsyncMock(return_value=dict(PAYMENT))) as lookup, \
         patch("routers.payments.db.get_tenant_by_id", AsyncMock(return_value=dict(TENANT))), \
         patch("routers.payments._process_refund", AsyncMock()) as proc:
        await payments._handle_charge_refunded({"payment_intent": "pi_123"})

    lookup.assert_awaited_once_with("pi_123")
    proc.assert_awaited_once()


@pytest.mark.asyncio
async def test_stripe_charge_refunded_missing_payment_intent():
    from routers import payments

    with patch("routers.payments.db.get_payment_by_payment_intent", AsyncMock()) as lookup, \
         patch("routers.payments._process_refund", AsyncMock()) as proc:
        await payments._handle_charge_refunded({})

    lookup.assert_not_awaited()
    proc.assert_not_awaited()


@pytest.mark.asyncio
async def test_stripe_charge_refunded_no_payment_record():
    from routers import payments

    with patch("routers.payments.db.get_payment_by_payment_intent", AsyncMock(return_value=None)), \
         patch("routers.payments._process_refund", AsyncMock()) as proc:
        await payments._handle_charge_refunded({"payment_intent": "pi_unknown"})

    proc.assert_not_awaited()


# ---------------------------------------------------------------------------
# Square: _handle_square_refund + dispatch from payment.updated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_square_refund_looks_up_by_order_id():
    from routers import payments

    with patch("routers.payments.db.get_payment_by_checkout_session", AsyncMock(return_value=dict(PAYMENT))) as lookup, \
         patch("routers.payments.db.get_tenant_by_id", AsyncMock(return_value=dict(TENANT))), \
         patch("routers.payments._process_refund", AsyncMock()) as proc:
        await payments._handle_square_refund({"order_id": "ord-1"})

    lookup.assert_awaited_once_with("ord-1")
    proc.assert_awaited_once()


@pytest.mark.asyncio
async def test_square_payment_updated_with_refund_routes_to_refund_handler():
    """A COMPLETED payment.updated carrying refunded_money must go to the
    refund handler, never re-trigger the deposit confirmation."""
    from routers import payments

    event = {
        "type": "payment.updated",
        "data": {"object": {"payment": {
            "status": "COMPLETED",
            "order_id": "ord-1",
            "id": "sqpay-1",
            "refunded_money": {"amount": 2000, "currency": "CAD"},
        }}},
    }

    with patch("routers.payments._handle_square_refund", AsyncMock()) as refund, \
         patch("routers.payments.db.get_payment_by_checkout_session", AsyncMock(return_value=dict(PAYMENT))) as lookup:
        await payments._handle_square_payment_completed(event)

    refund.assert_awaited_once()
    # must NOT fall through to the normal deposit-confirmation lookup
    lookup.assert_not_awaited()
