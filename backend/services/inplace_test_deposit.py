"""
The one CAD $1 deposit of the #179 production validation (services/square_inplace_scope).

Called after a Square Appointments booking has been made and recorded. Returns
None — and the booking stays exactly as for any other caller — unless every one
of these holds:

  * the call is from the test caller (telephony metadata, never the model) to the
    test workspace, inside the validation window;
  * the caller read out the one-time code, and it matches;
  * the booking is at the test location, and the workspace's currency is CAD;
  * the code had not been used by another call, and the run isn't disabled;
  * this appointment is the run's appointment, and no link was created before.

Then it creates the link through the same deposit code every workspace uses,
with Square as the provider and CAD $1.00 as the amount, and records the payment
on the run. Workspace deposit settings are never read or changed.
"""
from __future__ import annotations

import logging

from db import inplace_test_runs as db_runs
from services import square_inplace_scope as scope

logger = logging.getLogger(__name__)

ALREADY_SENT = "already_sent"


async def deposit_for_booking(*, tenant: dict, tenant_id: str, vapi_call_id: str, metadata_phone: str,
                              test_code, appointment_id: str | None, location_id: str,
                              caller_name: str, service: str) -> dict | str | None:
    """None: not the test, nothing done. ALREADY_SENT: the run's one link exists.
    Otherwise the deposit sender's status dict."""
    if not scope.caller_in_test(tenant_id, metadata_phone):
        return None
    if not test_code:
        logger.info("inplace_test: test caller booked without a code; ordinary booking")
        return None
    if not scope.code_matches(test_code):
        logger.warning("inplace_test: test code did not match; ordinary booking")
        return None
    if (location_id != scope.test_location() or str(tenant.get("square_location_id") or "") != scope.test_location()
            or (tenant.get("square_currency") or "").lower() != scope.TEST_DEPOSIT_CURRENCY or not appointment_id):
        logger.warning("inplace_test: location, currency or appointment not as configured; ordinary booking")
        return None

    h = scope.code_hash(test_code)
    try:
        run = await db_runs.use_code(h, tenant_id, vapi_call_id)
        if not run:
            logger.warning("inplace_test: code already used by another call, or disabled; ordinary booking")
            return None
        if str(run.get("appointment_id") or "") not in ("", str(appointment_id)):
            logger.warning("inplace_test: run already bound to another appointment; ordinary booking")
            return None
        if not run.get("appointment_id") and not await db_runs.bind_appointment(h, appointment_id):
            fresh = await db_runs.get(h) or {}
            if str(fresh.get("appointment_id") or "") != str(appointment_id):
                return None
        if not await db_runs.claim_link(h, appointment_id):
            return ALREADY_SENT
    except Exception as e:
        logger.error("inplace_test: run bookkeeping failed; no deposit: %s", e)
        return None

    from routers.tools import _create_and_send_deposit
    dep = await _create_and_send_deposit(
        tenant, caller_phone=metadata_phone, caller_name=caller_name, service=service,
        appointment_id=appointment_id, amount_cents=scope.TEST_DEPOSIT_CENTS, force_provider="square")
    if dep.get("payment_id"):
        try:
            await db_runs.record_payment(h, dep["payment_id"])
        except Exception as e:
            logger.error("inplace_test: could not record payment %s on the run: %s", dep["payment_id"], e)
    logger.info("inplace_test: test deposit for appointment %s: sent=%s error=%s",
                appointment_id, dep.get("sms_sent"), dep.get("error"))
    return dep
