"""
Who may use the Square in-place deposit move (issue #179), while it is validated.

Production validation runs on ONE named test tenant and the appointments named
for it, and nothing else:

  SQUARE_INPLACE_TEST_TENANT_ID        the tenant's id
  SQUARE_INPLACE_TEST_APPOINTMENT_IDS  comma-separated appointment ids

Both must be set, on the web service. For anyone else, a Square deposit
appointment is handed to the team exactly as before, and a deposit confirmation
names the time exactly as before, without taking ownership of the appointment.
Unset either variable to switch it off.
"""
from __future__ import annotations

import os


def _tenant() -> str:
    return os.getenv("SQUARE_INPLACE_TEST_TENANT_ID", "").strip()


def _appointments() -> set[str]:
    return {a.strip() for a in os.getenv("SQUARE_INPLACE_TEST_APPOINTMENT_IDS", "").split(",") if a.strip()}


def enabled() -> bool:
    return bool(_tenant() and _appointments())


def allowed(tenant_id, appointment_id) -> bool:
    return enabled() and str(tenant_id or "") == _tenant() and str(appointment_id or "") in _appointments()
