"""
Cost computation. Separates a PUBLISHED-RATE ESTIMATE from ACTUAL METERED prices,
and separates connected transfer minutes from ringing/unanswered minutes.

Provider rounding is modelled explicitly (NOT a generic round):
  * Twilio voice bills per MINUTE, rounded UP to the next whole minute (ceil).
  * Vapi bills per second in our model (no artificial rounding); when actual Vapi
    cost is provided we use it verbatim.
Actual metered totals come from provider records the operator supplies per leg
(`price` for Twilio legs, `cost` for the Vapi call) and are reported separately
from the estimate.

Leg schema (list of dicts):
  {provider: "twilio"|"vapi", direction: "inbound"|"outbound",
   state: "connected"|"ringing"|"unanswered", seconds: int,
   price: float (optional, ACTUAL Twilio leg price),
   cost:  float (optional, ACTUAL Vapi call cost)}
"""
from __future__ import annotations

import math

from . import constants as C


def _twilio_minutes(seconds: int) -> int:
    """Twilio rounds voice UP to the whole minute."""
    return max(1, math.ceil(max(0, int(seconds)) / 60)) if seconds else 0


def estimate_leg_usd(leg: dict) -> float:
    provider = leg.get("provider")
    seconds = int(leg.get("seconds") or 0)
    if provider == "twilio":
        mins = _twilio_minutes(seconds)
        rate = C.RATE_TWILIO_INBOUND_PER_MIN if leg.get("direction") == "inbound" else C.RATE_TWILIO_OUTBOUND_PER_MIN
        return round(mins * rate, 6)
    if provider == "vapi":
        # per-second proration of the blended stack rate (no forced rounding)
        return round((seconds / 60.0) * C.RATE_VAPI_STACK_PER_MIN, 6)
    return 0.0


def summarize(legs: list[dict]) -> dict:
    published = 0.0
    actual = 0.0
    actual_available = True
    connected_minutes = 0.0
    ringing_minutes = 0.0
    by_provider: dict[str, float] = {}

    for leg in legs:
        est = estimate_leg_usd(leg)
        published += est
        by_provider[leg.get("provider", "?")] = round(by_provider.get(leg.get("provider", "?"), 0.0) + est, 6)

        secs = int(leg.get("seconds") or 0)
        if leg.get("state") == "connected":
            connected_minutes += secs / 60.0
        elif leg.get("state") in ("ringing", "unanswered"):
            ringing_minutes += secs / 60.0

        # actual metered: Twilio leg 'price' (often negative in Twilio records) or Vapi 'cost'
        metered = leg.get("price")
        if metered is None:
            metered = leg.get("cost")
        if metered is None:
            actual_available = False
        else:
            actual += abs(float(metered))

    return {
        "published_estimate_usd": round(published, 4),
        "actual_metered_usd": round(actual, 4) if actual_available else None,
        "actual_metered_complete": actual_available,
        "connected_minutes": round(connected_minutes, 3),
        "ringing_unanswered_minutes": round(ringing_minutes, 3),
        "by_provider_estimate_usd": by_provider,
        "note": ("published_estimate uses Twilio ceil-to-minute + Vapi per-second; "
                 "actual_metered is summed from provider-reported prices and is the "
                 "figure of record. Do not treat the estimate as billed."),
    }
