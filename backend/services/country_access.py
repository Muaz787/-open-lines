"""May this signup attempt proceed, given where the business is? (W9I-H.0.1)

ONE DECISION, AND IT HAS TO COME FIRST
Live production proof in W9I-H.0 found the card requirement being enforced
BEFORE the country was considered. A business in a country we do not serve was
told to enter payment details, and only after supplying them learned we could
not sell to them. The same ordering meant an authorized Irish pilot had to
complete card setup before their grant was even consulted.

Both are the same defect: availability is a property of the request, and it is
knowable from the country and the onboarding key alone. Nothing should be asked
of a customer we are about to refuse.

WHAT THIS IS NOT
It is not an authorization check on anything downstream. Answering ALLOWED here
means only "this signup may continue to the ordinary flow" -- the card
requirement, the provisioning, the regulatory collection and every gate after it
are untouched and still apply in full. Ireland does not become cardless by being
decided earlier.

IT NEVER CONSUMES ANYTHING. Deciding is a read. The pilot grant is spent later,
once a durable tenant exists, exactly as W9I-H.0 specifies -- otherwise a
customer who abandoned at the card step would have burned their invitation on a
question.
"""
from __future__ import annotations

import logging

from services import ireland_pilot
from services import onboarding_lifecycle as lifecycle_ob

logger = logging.getLogger(__name__)

ALLOWED = "allowed"
DENIED = "denied"

#: Why it was allowed. The caller needs the difference: only a pilot-authorized
#: signup has a grant to spend afterwards.
UNREGULATED = "unregulated_country"
PUBLICLY_OPEN = "publicly_open"
PILOT_CREATE = "pilot_grant_create"
PILOT_RESUME = "pilot_grant_resume"


async def decide(*, iso_country: str, onboarding_key: str = "") -> dict:
    """Returns {"access": ALLOWED|DENIED, "reason": ..., "pilot_grant": bool}.

    `pilot_grant` says whether a grant authorized this attempt and therefore
    needs consuming once a tenant exists. It is False for every ordinary signup,
    which is what keeps CA and US from ever reading the grants table.
    """
    country = str(iso_country or "").strip().upper()

    if not lifecycle_ob.needs_regulatory_clearance(country):
        # CA, US and everything else we serve openly. Unchanged, and deliberately
        # short-circuited before any grant lookup.
        return {"access": ALLOWED, "reason": UNREGULATED, "pilot_grant": False}

    if lifecycle_ob.ireland_onboarding_enabled():
        # Publicly open. A grant is a way past a CLOSED gate, not an extra check
        # on an open one.
        return {"access": ALLOWED, "reason": PUBLICLY_OPEN, "pilot_grant": False}

    verdict = await ireland_pilot.decide(onboarding_key=onboarding_key,
                                         iso_country=country)
    if verdict["outcome"] == ireland_pilot.INTEGRITY:
        # A grant whose key resolves to a tenant it never produced. Logged
        # distinctly for an operator; indistinguishable from every other refusal
        # to the customer.
        logger.error("Ireland pilot grant integrity failure: %s",
                     verdict.get("reason"))
        return {"access": DENIED, "reason": "integrity", "pilot_grant": False}
    if verdict["outcome"] == ireland_pilot.ALLOW_CREATE:
        return {"access": ALLOWED, "reason": PILOT_CREATE, "pilot_grant": True}
    if verdict["outcome"] == ireland_pilot.ALLOW_RESUME:
        return {"access": ALLOWED, "reason": PILOT_RESUME, "pilot_grant": True}
    return {"access": DENIED, "reason": verdict.get("reason") or "closed",
            "pilot_grant": False}
