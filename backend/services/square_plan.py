"""
Does this seller's Square plan let us write bookings?

Square only accepts bookings, moves and cancellations from an app ("seller-level
writes") when the seller pays for Appointments Plus or Premium. On the free plan
reads still work (availability, services, team), but every write comes back:

    HTTP 403 {"errors":[{"category":"AUTHENTICATION_ERROR","code":"FORBIDDEN",
              "detail":"Merchant subscription does not support write operations."}]}

Square publishes the answer ahead of time as
business_booking_profile.support_seller_level_writes. We read it live with a
short cache, so there is nothing to migrate or backfill and a salon that
upgrades is picked up within minutes. A plan refusal seen on any write marks the
token as read-only straight away.

When writes aren't supported, the assistant still offers real availability, but
it records a request for the team (callback_requests row + owner alert) and tells
the caller the team will confirm, instead of promising a booking Square will
refuse.
"""
from __future__ import annotations

import hashlib
import logging
import time

logger = logging.getLogger(__name__)

_TTL_SECONDS = 600
# token fingerprint -> (supports_writes: bool, checked_at)
_cache: dict[str, tuple[bool, float]] = {}


def _key(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()[:24]


def _now() -> float:
    return time.monotonic()


def is_plan_refusal(status_code: int | None, body_text: str = "") -> bool:
    """A 403 that is Square refusing because of the seller's plan, not our auth."""
    if status_code != 403:
        return False
    text = (body_text or "").lower()
    return "subscription" in text and "write" in text


def mark_no_writes(token: str) -> None:
    if token:
        _cache[_key(token)] = (False, _now())
        logger.warning("square_plan: seller's Square plan refused a booking write; "
                       "treating it as read-only")


async def seller_writes(token: str) -> bool | None:
    """True / False from Square's booking profile, or None when it couldn't be read.

    None means "unknown": callers go ahead and try, and a plan refusal then marks
    the token read-only."""
    if not token:
        return None
    k = _key(token)
    hit = _cache.get(k)
    if hit and _now() - hit[1] < _TTL_SECONDS:
        return hit[0]
    from services import square_booking
    try:
        profile = await square_booking.retrieve_booking_profile(token)
    except Exception as e:
        logger.warning("square_plan: booking profile read failed: %s", e)
        return None
    value = profile.get("support_seller_level_writes") if profile else None
    if not isinstance(value, bool):
        return None
    _cache[k] = (value, _now())
    return value


async def tenant_writes(tenant: dict) -> bool | None:
    from services import square_booking
    try:
        token = await square_booking.get_access_token(tenant)
    except Exception:
        return None
    return await seller_writes(token or "")


# ---------------------------------------------------------------------------
# Hand the request to the team
# ---------------------------------------------------------------------------

KIND_BOOK = "book"
KIND_CANCEL = "cancel"

_TITLES = {KIND_BOOK: "Booking request", KIND_CANCEL: "Cancellation request"}


async def record_request(*, tenant: dict, tenant_id: str, call_id: str, kind: str,
                         caller_name: str, caller_phone: str, detail: str) -> bool:
    """One open callback_requests row per caller + request, then alert the owner.
    Best-effort: never raises. True when a new request was stored."""
    try:
        from db import routing as rdb
        reason = f"{_TITLES.get(kind, 'Request')}: {detail}"
        open_rows = await rdb.list_callbacks(tenant_id, status="open")
        if any(r.get("reason") == reason and (r.get("caller_phone") or "") == caller_phone
               for r in open_rows):
            logger.info("square_plan: %s already recorded for tenant %s call %s",
                        kind, tenant_id, call_id)
            return False
        await rdb.create_callback(tenant_id, {
            "call_id": None, "caller_name": caller_name or "", "caller_phone": caller_phone,
            "reason": reason, "urgency": "normal", "status": "open",
        })
        logger.info("square_plan: recorded %s request for tenant %s call %s", kind, tenant_id, call_id)
        await _alert_owner(tenant, tenant_id=tenant_id, call_id=call_id, kind=kind,
                           caller_name=caller_name, caller_phone=caller_phone, reason=reason)
        return True
    except Exception as e:
        logger.error("square_plan: recording %s failed for tenant %s call %s: %s",
                     kind, tenant_id, call_id, e)
        return False


async def _alert_owner(tenant: dict, *, tenant_id, call_id, kind, caller_name,
                       caller_phone, reason) -> None:
    business = tenant.get("business_name") or ""
    to = tenant.get("notification_email") or ""
    if to and tenant.get("email_enabled", True):
        try:
            from services.email import send_square_request_email
            await send_square_request_email(
                to=to, business_name=business, title=_TITLES.get(kind, "Request"),
                caller_name=caller_name, caller_number=caller_phone, reason=reason,
                tenant_id=tenant_id, idempotency_key=f"square-plan:{kind}:{call_id}:{reason[:80]}")
        except Exception as e:
            logger.error("square_plan: email failed for tenant %s: %s", tenant_id, e)
    try:
        from services.owner_notify import send_owner_sms_whatsapp
        who = f"{caller_name} ({caller_phone})" if caller_name else caller_phone
        await send_owner_sms_whatsapp(
            tenant, sms_body=f"📅 {reason} — from {who}. Please confirm with them. — {business}",
            wa_template_sid="", wa_vars={}, event=f"square_{kind}_request")
    except Exception as e:
        logger.error("square_plan: SMS failed for tenant %s: %s", tenant_id, e)


def booking_message(*, service: str, friendly: str, business_name: str, recorded: bool) -> str:
    sent = ("This request has already been sent to the team, so don't take it down again. "
            if recorded else "")
    return (f"NOT BOOKED YET. {business_name}'s booking system only lets the team confirm "
            f"appointments, so the caller's request for {service} on {friendly} has been passed "
            f"to them. {sent}Tell the caller you've sent their request for that time and the team "
            "will text or call to confirm it. Do not say it is booked or confirmed.")


def cancel_message(*, recorded: bool) -> str:
    sent = ("This request has already been sent to the team, so don't take it down again. "
            if recorded else "")
    return ("NOT CANCELLED YET. This business's booking system only lets the team cancel "
            f"appointments, so the request has been passed to them. {sent}Tell the caller the "
            "team will cancel it and confirm with them. Do not say it is cancelled.")
