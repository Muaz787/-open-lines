"""
W6A2-C4 — cancel one appointment at its provider, under global ownership.

W6A1 built this logic inside the cancel tool. C4 adds two more callers — the
refund path and the deferred-intent worker — and three copies of a
location-verification rule is three chances for one of them to drift. So the
provider half lives here and the tool delegates to it.

The contract is C1's taxonomy, not a bool:
    ok        provider confirmed cancelled, or confirmed already cancelled,
              or definitively reports the booking absent
    unknown   we cannot establish what happened — the caller must RETAIN
              ownership and reconcile, never release
    mismatch  the provider's copy is at a different location than ours; refuse
    failed    provider definitively rejected it; the booking is still live
"""
from __future__ import annotations

import logging

from services import square_booking

logger = logging.getLogger(__name__)

OK = "ok"
UNKNOWN = "unknown"
MISMATCH = "mismatch"
FAILED = "failed"


async def cancel_square_booking(tenant: dict, appt: dict, event_id: str,
                                tenant_id: str) -> str:
    """Verify against Square, then cancel. See module docstring for the contract.

    The location check is the point. A local row can drift — a bad backfill, a
    manual edit, a bug we have not found — and cancelling on an id alone would
    then destroy a booking at a location nobody mentioned. Square's own copy is
    the authority, and if the two disagree we stop.
    """
    token = await square_booking.get_access_token(tenant)
    if not token:
        logger.error("cancel[square]: no access token for tenant %s", tenant_id)
        return FAILED

    fetch_status, booking = await square_booking.get_booking_detailed(token, event_id)
    if fetch_status == square_booking.FETCH_UNKNOWN:
        # Unreadable: we cannot verify the location, so we must not cancel — and
        # equally cannot claim the cancellation failed.
        logger.error("cancel[square]: booking %s unreadable for tenant %s", event_id, tenant_id)
        return UNKNOWN
    if fetch_status == square_booking.FETCH_NOT_FOUND:
        logger.warning("cancel[square]: booking %s absent at the provider (tenant %s) — "
                       "reconciling local state", event_id, tenant_id)
        return OK

    expected = str(appt.get("provider_location_id") or "")
    actual = str(booking.get("location_id") or "")
    if expected and actual and expected != actual:
        logger.error(
            "cancel[square]: INTEGRITY FAILURE — appointment %s says location %s but "
            "Square booking %s is at %s. Refusing to cancel (tenant %s).",
            appt.get("id"), expected, event_id, actual, tenant_id)
        return MISMATCH
    if expected and not actual:
        logger.error("cancel[square]: booking %s exposes no location_id; refusing to "
                     "cancel against expected %s (tenant %s)", event_id, expected, tenant_id)
        return MISMATCH

    status, _, err_code = await square_booking.cancel_booking_detailed(token, event_id)
    if status in (square_booking.CANCEL_OK, square_booking.CANCEL_ALREADY):
        if status == square_booking.CANCEL_ALREADY:
            logger.info("cancel[square]: booking %s was already cancelled — reconciling", event_id)
        return OK
    if status == square_booking.CANCEL_NOT_FOUND:
        logger.warning("cancel[square]: booking %s reported NOT_FOUND — reconciling "
                       "local state (tenant %s)", event_id, tenant_id)
        return OK
    if status == square_booking.CANCEL_UNKNOWN:
        logger.error("cancel[square]: cancel of %s outcome UNKNOWN (tenant %s)", event_id, tenant_id)
        return UNKNOWN
    logger.error("cancel[square]: cancel of %s returned %s%s (tenant %s)",
                 event_id, status, f" [{err_code}]" if err_code else "", tenant_id)
    return FAILED


async def cancel_calendar_event(tenant: dict, event_id: str, tenant_id: str) -> str:
    """Google/Outlook equivalent. Failures are UNKNOWN, not FAILED.

    Neither provider tells us whether a delete landed when the call errors, and
    those SDK wrappers raise the same exception for a refusal and a timeout. The
    honest classification is therefore uncertainty — which keeps ownership rather
    than releasing it.
    """
    from services import calendar as cal_svc
    from services.calendar import CalendarTokenExpiredError
    from services import ms_calendar as ms_cal_svc
    from services.ms_calendar import MsCalendarTokenExpiredError
    import db.supabase as db

    refresh_token = tenant.get("google_refresh_token")
    provider = "google"
    if not refresh_token:
        refresh_token = tenant.get("microsoft_refresh_token")
        provider = "microsoft"
    if not refresh_token:
        logger.error("cancel[calendar]: no calendar credential for tenant %s", tenant_id)
        return FAILED

    try:
        if provider == "microsoft":
            await ms_cal_svc.cancel_event(refresh_token, event_id)
        else:
            await cal_svc.cancel_event(refresh_token, event_id)
        return OK
    except (CalendarTokenExpiredError, MsCalendarTokenExpiredError):
        logger.error("cancel[calendar]: token expired for tenant %s — auto-disconnecting", tenant_id)
        clear_field = "microsoft_refresh_token" if provider == "microsoft" else "google_refresh_token"
        try:
            await db.update_tenant(tenant_id, {clear_field: None})
        except Exception:
            pass
        return UNKNOWN
    except Exception as e:
        logger.error("cancel[calendar]: cancel of %s failed for tenant %s: %s",
                     event_id, tenant_id, e)
        return UNKNOWN


async def cancel_at_provider(tenant: dict, appt: dict, tenant_id: str) -> str:
    """Dispatch to whichever provider owns this appointment's booking."""
    event_id = appt.get("google_event_id") or ""
    if not event_id:
        logger.error("cancel: appointment %s has no provider booking id (tenant %s)",
                     appt.get("id"), tenant_id)
        return FAILED
    if tenant.get("square_appointments_enabled"):
        return await cancel_square_booking(tenant, appt, event_id, tenant_id)
    return await cancel_calendar_event(tenant, event_id, tenant_id)
