"""
Who may use the Square in-place deposit move (issue #179), while it is validated
in production with one CAD $1 test deposit.

Everything new is off unless ALL of these are set on the web service:

  SQUARE_INPLACE_TEST_TENANT_ID      the one workspace
  SQUARE_INPLACE_TEST_LOCATION_ID    its Square location (Toronto Test)
  SQUARE_INPLACE_TEST_CALLER_PHONE   the one caller, E.164, matched against call metadata
  SQUARE_INPLACE_TEST_CODE_SHA256    sha256 of a one-time code the caller reads out
  SQUARE_INPLACE_TEST_EXPIRES_AT     ISO-8601 UTC, at most 24 hours ahead

A booking by that caller, at that location, with that code, before that time,
gets one CAD $1 deposit link (services/inplace_test_deposit.py). Using the code
writes a row to inplace_test_runs (migration 047): that row is what makes the
code single-use, allows exactly one payment link, and names the one appointment
the in-place move and the deposit-confirmation lock may then act on.

Everyone else keeps today's behaviour: no deposit (workspace deposits stay off),
today's team handoff for a Square deposit move, today's confirmation text.

To stop the test immediately, set disabled_at on its inplace_test_runs row (takes
effect on the next request, no redeploy); before the code is used, insert a
disabled row for its hash. Removing a variable or letting the expiry pass also
switches it off. Recovery of a move already under way is not affected: it
settles by reading Square (services.calendar_reschedule.run_recovery).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

MAX_WINDOW = timedelta(hours=24)
TEST_DEPOSIT_CENTS = 100          # CAD $1.00, fixed; not configurable
TEST_DEPOSIT_CURRENCY = "cad"


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
            and _env("SQUARE_INPLACE_TEST_CALLER_PHONE")
            and re.fullmatch(r"[0-9a-f]{64}", _env("SQUARE_INPLACE_TEST_CODE_SHA256"))
            and at):
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
    """sha256 of the code's digits; '' when there are none."""
    digits = re.sub(r"\D", "", str(code or ""))
    return hashlib.sha256(digits.encode()).hexdigest() if digits else ""


def code_matches(code) -> bool:
    h = code_hash(code)
    return bool(h) and hmac.compare_digest(h, _env("SQUARE_INPLACE_TEST_CODE_SHA256"))


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
    return bool(run and str(run.get("tenant_id")) == test_tenant() and not run.get("disabled_at")
                and run.get("code_sha256") == _env("SQUARE_INPLACE_TEST_CODE_SHA256"))
