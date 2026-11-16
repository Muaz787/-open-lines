"""
Who may move a Square appointment that has a deposit, in place (issue #179).

The in-place move (services.square_inplace_reschedule) was first switched on only
for the one appointment bound to an armed validation run (services.square_inplace_scope).
That run passed on 2026-11-06. This module is the general release: every Square
Appointments workspace may now have a deposit appointment moved by the assistant,
under the same rules the engine already enforces (same location, service, team
member and length; booking still as on record; a PAID deposit inside the business's
own cancellation window is not moved; anything unprovable goes to the team).

Kill switch: set SQUARE_DEPOSIT_MOVES=off on the web service (also accepts
0/false/no). Deposit appointments then go back to the team exactly as before,
except an armed validation run, which keeps working on its own appointment.
Moves already under way are unaffected: recovery settles them by reading Square.

The deposit-confirmation lock (migration 047's payment_confirmation claim) follows
the same switch: wherever a deposit appointment can be moved, a confirmation must
own the appointment while it reads and sends the time, or it could text a time
that a move has just replaced.
"""
from __future__ import annotations

import os

from services import square_inplace_scope

_OFF = ("off", "0", "false", "no")


def released() -> bool:
    """Is the general release on? On unless explicitly switched off."""
    return os.getenv("SQUARE_DEPOSIT_MOVES", "on").strip().lower() not in _OFF


def any_enabled() -> bool:
    """Can a deposit appointment be moved anywhere right now?"""
    return released() or square_inplace_scope.enabled()


async def allowed(tenant_id, appointment_id) -> bool:
    """May the in-place move / confirmation lock act on this appointment?"""
    if not appointment_id:
        return False
    if released():
        return True
    return await square_inplace_scope.allowed(tenant_id, appointment_id)
