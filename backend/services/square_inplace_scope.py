"""
Who may use the Square in-place deposit move (issue #179), while it is validated
in production with one CAD $1 test deposit.

Everything new is off unless ALL of these are set on the web service:

  SQUARE_INPLACE_TEST_TENANT_ID      the one workspace
  SQUARE_INPLACE_TEST_LOCATION_ID    its Square location (Toronto Test)
  SQUARE_INPLACE_TEST_CALLER_PHONE   the one caller, E.164, matched against call metadata
  SQUARE_INPLACE_TEST_EXPIRES_AT     ISO-8601 UTC, at most 24 hours ahead

AND a run has been armed: an operator inserts a row into inplace_test_runs
(migration 047) holding only the sha256 of a one-time code of at least 12 digits.
Without an armed, enabled row nothing happens. A booking by that caller, at that
location, before that time, reading out that code, uses the row (single use),
binds it to the new appointment, and gets one CAD $1 deposit link
(services/inplace_test_deposit.py). The in-place move and the deposit-confirmation
lock then act only on that bound appointment.

Everyone else keeps today's behaviour: no deposit (workspace deposits stay off),
today's team handoff for a Square deposit move, today's confirmation text.

To stop the test immediately, set disabled_at on its inplace_test_runs rows; it
takes effect on the next request, used or not, with no redeploy. A call from the
test caller that ends without using an armed code disables it too (the code may
now be in that call's transcript), and the test caller's calls are not recorded.
Removing a variable or letting the expiry pass also switches it off. Recovery of a move already under way is not affected: it
settles by reading Square (services.calendar_reschedule.run_recovery).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

MAX_WINDOW = timedelta(hours=24)
TEST_DEPOSIT_CENTS = 100          # CAD $1.00, fixed; not configurable
TEST_DEPOSIT_CURRENCY = "cad"
MIN_CODE_DIGITS = 12


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expires_at() -> datetime | None:
    raw = _env("SQUARE_INPLACE_TEST_EXPIRES_AT")
    if not raw:
        return None
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else None


def enabled() -> bool:
    """Is a validation window configured and open right now?"""
    at = _expires_at()
    if not (_env("SQUARE_INPLACE_TEST_TENANT_ID") and _env("SQUARE_INPLACE_TEST_LOCATION_ID")
            and _env("SQUARE_INPLACE_TEST_CALLER_PHONE") and at):
        return False
    now = _now()
    if at - now > MAX_WINDOW:
        logger.warning("square_inplace_scope: expiry is more than 24 hours ahead; test is off")
        return False
    return now < at


def test_tenant() -> str:
    return _env("SQUARE_INPLACE_TEST_TENANT_ID")


def test_location() -> str:
    return _env("SQUARE_INPLACE_TEST_LOCATION_ID")


def caller_in_test(tenant_id, metadata_phone: str) -> bool:
    """This call is from the test caller (per telephony metadata) to the test workspace."""
    from services.customer_identity import normalize_e164
    want = normalize_e164(_env("SQUARE_INPLACE_TEST_CALLER_PHONE"))
    return (enabled() and str(tenant_id or "") == test_tenant() and bool(want)
            and normalize_e164(metadata_phone) == want)


def code_hash(code) -> str:
    """sha256 of the code's digits; '' when there are fewer than MIN_CODE_DIGITS."""
    digits = re.sub(r"\D", "", str(code or ""))
    return hashlib.sha256(digits.encode()).hexdigest() if len(digits) >= MIN_CODE_DIGITS else ""


async def burn_unused_codes(tenant_id, metadata_phone: str, vapi_call_id: str) -> int:
    """After a call from the test caller ends: disable every armed code it did not
    use. Whatever was said is now in that call's transcript."""
    if not caller_in_test(tenant_id, metadata_phone):
        return 0
    from db import inplace_test_runs as db_runs
    try:
        n = await db_runs.disable_unused(str(tenant_id))
    except Exception as e:
        logger.error("square_inplace_scope: could not burn unused codes after call %s: %s", vapi_call_id, e)
        return 0
    if n:
        logger.warning("square_inplace_scope: call %s ended without using its code; %s armed "
                       "code(s) disabled — arm a new one", vapi_call_id, n)
    return n


async def allowed(tenant_id, appointment_id) -> bool:
    """May the in-place move / confirmation lock act on this appointment? Only the
    appointment a live, enabled test run is bound to."""
    if not (enabled() and appointment_id and str(tenant_id or "") == test_tenant()):
        return False
    from db import inplace_test_runs as db_runs
    try:
        run = await db_runs.for_appointment(str(appointment_id))
    except Exception as e:
        logger.warning("square_inplace_scope: run lookup failed for %s: %s", appointment_id, e)
        return False
    return bool(run and str(run.get("tenant_id")) == test_tenant() and not run.get("disabled_at"))
