"""Which call-summary channels a tenant may choose, and where each one goes.

ONE MODEL, TWO SURFACES. Onboarding asks the question, Settings changes the
answer, and the dispatcher obeys it. All three read through here so there is
exactly one place that knows what a preference means.

TWO SEMANTICS, AND THE TIMESTAMP DECIDES WHICH

    notification_prefs_set_at IS NULL      LEGACY   -- never asked
    notification_prefs_set_at IS NOT NULL  EXPLICIT -- the tenant chose

LEGACY is today's behaviour, preserved exactly: SMS and WhatsApp both resolve to
`sms_alert_number OR business_phone`. It is quarantined in one function, clearly
marked, and no new tenant can enter it. A production audit found 2 tenants
depending on it, all for WhatsApp via sms_alert_number; deleting it without this
path would have stopped their summaries silently.

EXPLICIT has no fallback of any kind. Every enabled channel carries its own
destination; a channel without one is off. It never borrows another channel's
number, never reaches for business_phone, and never reaches for the registration
email.

The move from legacy to explicit happens once, on a successful save, and is
one-way. Nothing clears the timestamp -- which is what makes "explicit" a
guarantee rather than a hint.

CAPABILITY, NOT COUNTRY
SMS is offered only when the tenant's own long-term number can send one: it is
sent FROM that number, and there is no central OpenLines sender. Nothing here
looks at a country. Irish numbers surfaced this because the Irish local product
is voice-only today; an Irish number that one day carries SMS becomes eligible
with no code change, and a voice-only number anywhere behaves identically.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

EMAIL = "email"
SMS = "sms"
WHATSAPP = "whatsapp"
CHANNELS = (EMAIL, SMS, WHATSAPP)

#: Why a channel is not on offer. For operators, never for customers.
NO_LONG_TERM_NUMBER = "tenant_has_no_long_term_number"
NOT_SMS_CAPABLE = "number_is_not_sms_capable"
CAPABILITY_UNKNOWN = "number_capability_unknown"
SENDER_NOT_CONFIGURED = "provider_sender_not_configured"

#: Capability belongs to a phone number and changes about as often as the number
#: does. Cached so rendering onboarding or opening Settings does not ask the
#: provider every time, and short enough that a real change is seen the same day.
_CAPABILITY_TTL_SECONDS = 15 * 60
_capability_cache: dict = {}


def _is_explicit(tenant: dict) -> bool:
    return bool(tenant.get("notification_prefs_set_at"))


# ── what may be OFFERED ───────────────────────────────────────────────────

async def eligible_channels(tenant: dict) -> dict:
    """What this tenant may be shown. Says nothing about what they chose."""
    from services import telephony

    wa_ready = bool(telephony._wa_from()
                    and telephony.TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID)
    return {
        EMAIL: {"eligible": True, "reason": ""},
        WHATSAPP: {"eligible": wa_ready,
                   "reason": "" if wa_ready else SENDER_NOT_CONFIGURED},
        SMS: await _sms_eligibility(tenant),
    }


async def _sms_eligibility(tenant: dict) -> dict:
    """Can this tenant's LONG-TERM number send a text?

    Read from the canonical permanent row, never from a temporary test line. A
    regulated tenant may hold a Canadian test number for weeks while a regulator
    works; that number can send SMS and their eventual permanent one cannot, so
    offering SMS on the strength of a temporary artifact would promise something
    that stops working the day the real number arrives.

    W9I-E already separates the two by construction -- mark_temporary_active
    deliberately does not mirror the legacy scalar -- but this reads the
    purpose-scoped row rather than leaning on that, because a guarantee worth
    depending on is worth stating here.
    """
    tenant_id = str(tenant.get("id") or "")
    sub_sid = str(tenant.get("twilio_subaccount_sid") or "").strip()
    sub_tok = str(tenant.get("twilio_auth_token") or "").strip()
    if not tenant_id:
        return {"eligible": False, "reason": NO_LONG_TERM_NUMBER}

    from db import phone_numbers as db_phones
    try:
        row = await db_phones.get_current_permanent(tenant_id)
    except Exception as e:
        logger.error("capability: canonical lookup failed for %s: %s",
                     tenant_id, type(e).__name__)
        return {"eligible": False, "reason": CAPABILITY_UNKNOWN}

    e164 = str((row or {}).get("e164") or "").strip()
    if not e164:
        # Waiting on a regulator, or between numbers. Nothing to send from, so
        # nothing offered -- and not a refusal: the moment they hold a capable
        # number, SMS appears on its own.
        return {"eligible": False, "reason": NO_LONG_TERM_NUMBER}
    if not (sub_sid and sub_tok):
        return {"eligible": False, "reason": CAPABILITY_UNKNOWN}

    caps = await _capabilities(sub_sid, sub_tok, e164)
    if caps is None:
        # We asked and could not find out. UNKNOWN IS NOT ELIGIBLE: offering a
        # channel we cannot confirm and failing later is worse than withholding
        # it, and an outage is not evidence a number lacks SMS.
        return {"eligible": False, "reason": CAPABILITY_UNKNOWN}
    if not caps.get("sms"):
        return {"eligible": False, "reason": NOT_SMS_CAPABLE}
    return {"eligible": True, "reason": ""}


async def _capabilities(sub_sid: str, sub_tok: str, e164: str) -> dict | None:
    now = time.monotonic()
    hit = _capability_cache.get(e164)
    if hit and now - hit[0] < _CAPABILITY_TTL_SECONDS:
        return hit[1]
    from services import telephony
    caps = await telephony.number_capabilities(sub_sid, sub_tok, e164)
    # A failed read is deliberately NOT cached: the next caller asks again
    # rather than inheriting a momentary outage for fifteen minutes.
    if caps is not None:
        _capability_cache[e164] = (now, caps)
    return caps


# ── what the tenant actually CHOSE ────────────────────────────────────────

def preferences(tenant: dict) -> dict:
    """The tenant's call-summary choices, exactly as the dispatcher sees them."""
    if _is_explicit(tenant):
        channels, semantics = _explicit_channels(tenant), "explicit"
    else:
        channels, semantics = _legacy_channels(tenant), "legacy"
    return {
        "channels": channels,
        "semantics": semantics,
        # Only meaningful for an explicit tenant. A legacy tenant with nothing
        # enabled was never asked, and calling that "dashboard only" would
        # assert a choice they never made.
        "dashboard_only": semantics == "explicit"
                          and not any(c["enabled"] for c in channels.values()),
    }


def _explicit_channels(tenant: dict) -> dict:
    """No fallback of any kind. A channel without its own destination is off."""
    def ch(flag: str, dest_field: str) -> dict:
        dest = str(tenant.get(dest_field) or "").strip()
        return {"enabled": bool(tenant.get(flag, False)) and bool(dest),
                "destination": dest}
    return {
        EMAIL: ch("email_enabled", "notification_email"),
        SMS: ch("sms_enabled", "sms_alert_number"),
        WHATSAPP: ch("whatsapp_enabled", "whatsapp_alert_number"),
    }


def _legacy_channels(tenant: dict) -> dict:
    """THE COMPATIBILITY PATH. Do not extend it; do not let a new tenant in.

    Reproduces the dispatcher's historical behaviour exactly, including the
    shared destination both SMS and WhatsApp resolved to. It exists so that
    applying migration 037 and releasing the explicit model changes nothing for
    a tenant who never asked for either.
    """
    shared = (str(tenant.get("sms_alert_number") or "").strip()
              or str(tenant.get("business_phone") or "").strip())
    email_to = str(tenant.get("notification_email") or "").strip()
    # An explicit WhatsApp destination wins if one somehow exists, so a legacy
    # tenant who has been given one is honoured rather than kept on the shared
    # number.
    wa_to = str(tenant.get("whatsapp_alert_number") or "").strip() or shared
    return {
        EMAIL: {"enabled": bool(tenant.get("email_enabled", True)) and bool(email_to),
                "destination": email_to},
        SMS: {"enabled": bool(tenant.get("sms_enabled", False)) and bool(shared),
              "destination": shared},
        WHATSAPP: {"enabled": bool(tenant.get("whatsapp_enabled", False)) and bool(wa_to),
                   "destination": wa_to},
    }


# ── validation, server-side and authoritative ─────────────────────────────

class PreferenceError(ValueError):
    """A preference the server will not store."""


def validate_explicit(patch: dict, *, current: dict) -> None:
    """An enabled channel must carry its own destination. Raises otherwise.

    Applied to the MERGED result rather than the patch alone, so enabling a
    channel in one request and its destination in another cannot slip through.
    """
    merged = {**(current or {}), **{k: v for k, v in patch.items() if v is not None}}
    for flag, dest_field, label in (
            ("email_enabled", "notification_email", "an email address"),
            ("sms_enabled", "sms_alert_number", "a mobile number"),
            ("whatsapp_enabled", "whatsapp_alert_number", "a WhatsApp number")):
        if merged.get(flag) and not str(merged.get(dest_field) or "").strip():
            raise PreferenceError(f"Choose {label} to receive summaries there.")


async def validate_capability(patch: dict, *, current: dict, tenant: dict) -> None:
    """A channel may only be TURNED ON if it can actually deliver. Raises otherwise.

    Hiding SMS in the picker is not enforcement: the API is reachable directly,
    and without this a crafted request could enable SMS on a voice-only number
    and the tenant would simply never receive a summary.

    Two deliberate narrowings:

      * only channels being NEWLY enabled are checked. A tenant already on SMS
        who edits their email must not be blocked, and turning a channel OFF is
        always allowed -- otherwise a capability change could trap someone in a
        configuration they cannot leave.
      * an UNKNOWN capability refuses the enable rather than permitting it. We
        cannot promise delivery we cannot confirm, and the tenant can retry. It
        is not destructive: nothing already stored is rewritten, which is what
        Stage L asks for.
    """
    merged = {**(current or {}), **{k: v for k, v in patch.items() if v is not None}}
    turning_on = [name for name, flag in ((EMAIL, "email_enabled"),
                                          (SMS, "sms_enabled"),
                                          (WHATSAPP, "whatsapp_enabled"))
                  if merged.get(flag) and not (current or {}).get(flag)]
    if not turning_on:
        return
    eligible = await eligible_channels(tenant)
    friendly = {SMS: "Text messages aren't available for your number yet.",
                WHATSAPP: "WhatsApp isn't available on your account yet.",
                EMAIL: "Email isn't available right now."}
    for name in turning_on:
        if not eligible[name]["eligible"]:
            logger.warning("refused to enable %s for a tenant: %s",
                           name, eligible[name]["reason"])
            raise PreferenceError(friendly[name])


def mask(destination: str) -> str:
    """A destination safe to put in an operational log."""
    d = str(destination or "")
    if "@" in d:
        name, _, domain = d.partition("@")
        return f"{name[:2]}***@{domain}"
    return f"***{d[-4:]}" if len(d) > 4 else "***"
