import os
import re
import logging
from dataclasses import dataclass
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

load_dotenv()

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")


def _master_client() -> Client:
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set")
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _sub_client(subaccount_sid: str, subaccount_token: str) -> Client:
    return Client(subaccount_sid, subaccount_token)


def regulatory_client(subaccount_sid: str, subaccount_token: str) -> Client:
    """A client that can read a SUB-ACCOUNT's regulatory resources.

    W9H-QA.2 measured a trap worth a named function. Twilio has two URL shapes:

      api.twilio.com/2010-04-01/Accounts/{sid}/...   PATH-scoped
      numbers.twilio.com/v2/RegulatoryCompliance/... CREDENTIAL-scoped

    The Numbers v2 URLs carry no account segment at all, so `Client(parent_sid,
    parent_token, account_sid=sub_sid)` silently returns the PARENT's Bundles,
    EndUsers and SupportingDocuments while appearing to be scoped to the
    sub-account. During W9H-QA.2 that made a brand-new, provably empty sub-account
    report one SupportingDocument -- a census that would have been reported as the
    customer's had it not been impossible on its face.

    Only the sub-account's OWN credentials scope Numbers v2. Use this rather than
    constructing a client with account_sid= whenever Bundles, EndUsers or
    SupportingDocuments are being read or written for a tenant.
    """
    if not subaccount_sid or not subaccount_token:
        raise ValueError("a regulatory client requires the sub-account's own credentials")
    return Client(subaccount_sid, subaccount_token)


async def create_subaccount(business_name: str) -> dict:
    try:
        client = _master_client()
        account = client.api.accounts.create(
            friendly_name=f"OpenLines - {business_name}"
        )
        logger.info("Created Twilio sub-account %s for '%s'", account.sid, business_name)
        return {"sid": account.sid, "auth_token": account.auth_token}
    except TwilioRestException as e:
        logger.error("Failed to create sub-account for '%s': %s", business_name, e)
        raise



async def close_subaccount(subaccount_sid: str) -> bool:
    """Close a Twilio sub-account. Returns True only if Twilio confirmed it.  (W9A)

    Twilio has no delete for sub-accounts; `status='closed'` is the terminal
    state and is irreversible, which is why the only caller is a rollback that
    created the account seconds earlier and knows nothing else has used it.

    Never raises. A rollback that throws would replace a clear provisioning
    error with a confusing one, and the orphan is still worth reporting loudly
    rather than crashing on.
    """
    if not subaccount_sid:
        return False
    try:
        _master_client().api.accounts(subaccount_sid).update(status="closed")
        logger.info("Closed Twilio sub-account %s", subaccount_sid)
        return True
    except Exception as e:
        logger.error("ORPHAN SUB-ACCOUNT %s could not be closed: %s — it must be "
                     "closed by hand in the Twilio console", subaccount_sid, e)
        return False


# Per-country search config.
# area_codes: try these first in order; fall through to national search if all miss.
# Empty list means go straight to national search.
_COUNTRY_CONFIG: dict[str, dict] = {
    "CA": {"twilio_code": "CA", "area_codes": ["416", "647", "905", "604", "403", "780", "613", "438"]},
    "US": {"twilio_code": "US", "area_codes": ["212", "310", "312", "415", "718", "617", "404", "206"]},
    "GB": {"twilio_code": "GB", "area_codes": []},
    "AU": {"twilio_code": "AU", "area_codes": []},
    "IE": {"twilio_code": "IE", "area_codes": []},
    "NZ": {"twilio_code": "NZ", "area_codes": []},
}

SUPPORTED_COUNTRIES = set(_COUNTRY_CONFIG.keys())


class CountryNotSupported(Exception):
    """A country we have no number inventory configuration for.

    A distinct type rather than a generic ValueError so the routers can map it to
    a controlled customer-facing refusal instead of a 500, and so a test can
    assert that an unsupported country never reaches number search at all.
    """

    def __init__(self, country_code: str):
        self.country_code = str(country_code or "")
        super().__init__(f"country_not_supported:{self.country_code or '<empty>'}")

# Canadian area codes grouped by province. Used to keep a new number in the
# SAME province as the business — so an Ontario business never gets a Quebec
# number just because a single Toronto code was momentarily out of inventory.
_CA_AREA_CODES_BY_PROVINCE: dict[str, list[str]] = {
    "ON": ["416", "647", "437", "905", "289", "365", "613", "343", "519", "226", "705", "249", "807"],
    "QC": ["514", "438", "263", "450", "579", "418", "581", "819", "873"],
    "BC": ["604", "778", "236", "672", "250"],
    "AB": ["403", "587", "825", "780", "368"],
    "MB": ["204", "431"],
    "SK": ["306", "639"],
    "NS": ["902", "782"],
    "NB": ["506"],
    "NL": ["709"],
    "PE": ["902", "782"],
}
_PROVINCE_BY_AREA_CODE: dict[str, str] = {
    ac: prov for prov, acs in _CA_AREA_CODES_BY_PROVINCE.items() for ac in acs
}
# When a Canadian business's province can't be determined, default to Ontario
# (home market) rather than a national search that could land out-of-province.
DEFAULT_CA_PROVINCE = "ON"


# Domestic trunk prefixes, by ISO country, for numbers written the way a local
# says them. Only consulted when a caller supplies the country EXPLICITLY.
_NATIONAL_PREFIX: dict[str, str] = {
    "IE": "353",   # 087 123 4567  -> +353 87 123 4567
    "GB": "44",
}


def normalize_phone(phone: str, default_country: str = "") -> str:
    """Best-effort E.164 normalization (strips spaces/parens/dashes) so numbers are
    safe for Twilio SMS and 'whatsapp:<E.164>'. An existing '+' is preserved.

    `default_country` is an ISO code the CALLER must supply deliberately. Without
    it the NANP assumptions below are unchanged, which is what every existing
    tenant depends on. With it, a number written in that country's domestic
    trunk form ('087…' in Ireland) resolves correctly.  (W9A)

    Two rules make this safe for Ireland without endangering North America:

      * '00' is the international access prefix in Ireland, the UK and most of
        the world. '00353871234567' means '+353871234567'. It previously became
        '+00353871234567', which is not a number. That fix needs no country
        context at all -- it is unambiguous.
      * a leading single '0' is a DOMESTIC trunk prefix, and what follows it is
        meaningless without knowing the country. It is therefore only stripped
        when default_country says which country, and never guessed. A bare
        10-digit number still becomes NANP unless a country says otherwise,
        because that is what North American callers have always relied on.
    """
    if not phone:
        return ""
    has_plus = phone.strip().startswith("+")
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return ""
    if has_plus:
        return "+" + digits

    # Unambiguous: the international access prefix, in any country.
    if digits.startswith("00") and len(digits) > 4:
        return "+" + digits[2:]

    cc = _NATIONAL_PREFIX.get((default_country or "").strip().upper())
    if cc:
        if digits.startswith(cc):
            return "+" + digits
        if digits.startswith("0"):
            return "+" + cc + digits.lstrip("0")
        return "+" + cc + digits

    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits


def area_code_from_phone(phone: str) -> str:
    """Extract the North American (NANP) area code from a phone string, or '' if
    it isn't a 10-/11-digit NANP number. Used to match the business's own region."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits[:3] if len(digits) == 10 else ""


async def find_available_number(
    subaccount_sid: str,
    subaccount_token: str,
    country_code: str = "CA",
    preferred_area_code: str = "",
    province: str = "",
) -> str:
    cc = str(country_code or "").strip().upper()
    if cc not in _COUNTRY_CONFIG:
        # FAIL CLOSED. This used to log a warning and continue as Canada, which
        # meant an unrecognised or malformed country silently bought a Canadian
        # number: the wrong country on the invoice, the wrong country in any
        # future regulatory filing, and a business whose callers dial another
        # continent. A country we cannot serve has to be refused, not
        # substituted.
        raise CountryNotSupported(cc)

    config = _COUNTRY_CONFIG[cc]
    twilio_code = config["twilio_code"]

    if cc == "CA":
        # Keep the number in the business's province. Strongest signal is the
        # province of the business's own area code; else the detected province;
        # else Ontario (home market). We try the preferred code first, then EVERY
        # area code in that province, and only fall back to a national search as a
        # last resort — so an Ontario business never lands on a Quebec/BC number.
        prov = _PROVINCE_BY_AREA_CODE.get(preferred_area_code, "") or (province or "").upper()
        if prov not in _CA_AREA_CODES_BY_PROVINCE:
            prov = DEFAULT_CA_PROVINCE
        prov_codes = _CA_AREA_CODES_BY_PROVINCE[prov]
        area_codes = ([preferred_area_code] if preferred_area_code else []) + \
            [a for a in prov_codes if a != preferred_area_code]
        logger.info("Number search: CA province=%s, codes=%s (preferred=%s)", prov, area_codes, preferred_area_code or "-")
    else:
        # Prefer the business's own area code first, then popular codes, then national.
        area_codes = list(config["area_codes"])
        if preferred_area_code:
            area_codes = [preferred_area_code] + [a for a in area_codes if a != preferred_area_code]

    client = _sub_client(subaccount_sid, subaccount_token)

    # Try area codes first (North America)
    for area_code in area_codes:
        try:
            results = client.available_phone_numbers(twilio_code).local.list(
                area_code=area_code, limit=1,
            )
            if results:
                number = results[0].phone_number
                logger.info("Found %s in area code %s (sub-account %s)", number, area_code, subaccount_sid)
                return number
        except TwilioRestException as e:
            logger.warning("Area code %s search failed on sub-account %s: %s", area_code, subaccount_sid, e)

    # National fallback — no area code filter
    try:
        results = client.available_phone_numbers(twilio_code).local.list(limit=1)
        if results:
            number = results[0].phone_number
            logger.info("Found %s via national search in %s (sub-account %s)", number, twilio_code, subaccount_sid)
            return number
    except TwilioRestException as e:
        logger.error("National search failed for %s on sub-account %s: %s", twilio_code, subaccount_sid, e)
        raise

    raise ValueError(f"No available local numbers found in {twilio_code}")


# ═══════════════════════════════════════════════════════════════════════════
# Regulated inventory and purchase  (W9I-F)
# ═══════════════════════════════════════════════════════════════════════════
#
# DELIBERATELY SEPARATE from find_available_number/purchase_number_with_sid,
# which are the CA/US path and must not change. Two differences make sharing
# them wrong rather than merely inconvenient:
#
#   * A regulated purchase REQUIRES provider bindings. W9C measured Twilio
#     refusing an Irish number with "Phone Number Requires an Address but
#     AddressSid was empty"; the North American path passes neither an
#     AddressSid nor a BundleSid and never needs to.
#   * The North American search SUBSTITUTES. It walks a province's area codes
#     and then falls back to a national search, which is right when any local
#     number will do and wrong when a customer named a premises -- silently
#     handing them a number for a different city is the thing Stage F forbids.


class NumberCandidate:
    """One available number, with what the provider says about it.

    `locality` is carried because a UI may want to show it, NOT because it is
    proof of anything: W9C found provider locality labels misleading, and
    purchase-time acceptance is the only authority on whether a number is
    compatible with a regulatory address.
    """

    __slots__ = ("phone_number", "locality", "region", "capabilities")

    def __init__(self, phone_number: str, locality: str, region: str,
                 capabilities: dict):
        self.phone_number = phone_number
        self.locality = locality or ""
        self.region = region or ""
        self.capabilities = capabilities or {}

    def supports(self, *required: str) -> bool:
        return all(bool(self.capabilities.get(c)) for c in required)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"NumberCandidate({self.phone_number}, locality={self.locality!r})"


async def find_regulated_candidates(subaccount_sid: str, subaccount_token: str,
                                    iso_country: str, *, locality: str = "",
                                    limit: int = 10) -> list["NumberCandidate"]:
    """Available local inventory in ONE country, optionally in one locality.

    Returns [] when there is nothing -- an empty shelf is a state the caller
    reports, not an exception. NEVER widens the search: if a locality was asked
    for and has no inventory, the answer is "none", not a number somewhere else.
    """
    cc = str(iso_country or "").strip().upper()
    if cc not in _COUNTRY_CONFIG:
        raise CountryNotSupported(cc)
    client = _sub_client(subaccount_sid, subaccount_token)
    kwargs: dict = {"limit": max(1, int(limit))}
    if locality:
        kwargs["in_locality"] = locality
    try:
        results = client.available_phone_numbers(
            _COUNTRY_CONFIG[cc]["twilio_code"]).local.list(**kwargs)
    except TwilioRestException as e:
        logger.error("Regulated inventory search failed for %s on sub-account %s: %s",
                     cc, subaccount_sid, e)
        raise
    out = []
    for r in results:
        caps = getattr(r, "capabilities", None) or {}
        if not isinstance(caps, dict):
            caps = {k: getattr(caps, k, False) for k in ("voice", "SMS", "MMS")}
        out.append(NumberCandidate(
            phone_number=str(getattr(r, "phone_number", "") or ""),
            locality=str(getattr(r, "locality", "") or ""),
            region=str(getattr(r, "region", "") or ""),
            capabilities={str(k).lower(): bool(v) for k, v in caps.items()}))
    return [c for c in out if c.phone_number]


async def purchase_regulated_number(subaccount_sid: str, subaccount_token: str,
                                    phone_number: str, *, address_sid: str,
                                    bundle_sid: str) -> tuple[str, str]:
    """Buy a number that a regulator requires identity documents for.

    BOTH bindings are required arguments with no defaults, and are refused when
    empty. Twilio rejects the purchase itself without an AddressSid, so a missing
    one would surface as a provider error -- but a missing BUNDLE would not
    necessarily, and a regulated number bought without its bundle is a number
    whose compliance record does not point at it. Refusing here makes that
    impossible rather than unlikely.

    Both SIDs must come from the SAME sub-account as the credentials: Numbers v2
    is credential-scoped (W9C), so another account's bundle is invisible here and
    a parent-account bundle cannot be used at all.
    """
    if not address_sid:
        raise ValueError("purchase_regulated_number requires an address_sid")
    if not bundle_sid:
        raise ValueError("purchase_regulated_number requires a bundle_sid")
    client = _sub_client(subaccount_sid, subaccount_token)
    try:
        incoming = client.incoming_phone_numbers.create(
            phone_number=phone_number, address_sid=address_sid, bundle_sid=bundle_sid)
    except TwilioRestException as e:
        # The number, not the identity data, is what goes in the log.
        logger.error("Regulated purchase of %s on sub-account %s failed: %s",
                     phone_number, subaccount_sid, e)
        raise
    logger.info("Purchased regulated number %s on sub-account %s (SID %s)",
                incoming.phone_number, subaccount_sid, incoming.sid)
    return incoming.phone_number, incoming.sid


async def purchase_number_with_sid(
    subaccount_sid: str,
    subaccount_token: str,
    phone_number: str,
) -> tuple[str, str]:
    """Buy a number and return BOTH its E.164 and the provider object's SID.

    The SID exists because migration 027's canonical model is keyed on it --
    tpn_provider_object_key is unique on (provider, account, provider_sid), and it
    is what lets a later reconciliation ask Twilio about a specific number rather
    than matching on a string that could have been re-issued. purchase_number()
    below still returns only the E.164, so every existing caller is unchanged.
    """
    try:
        client = _sub_client(subaccount_sid, subaccount_token)
        incoming = client.incoming_phone_numbers.create(phone_number=phone_number)
        logger.info(
            "Purchased number %s on sub-account %s (SID %s)",
            incoming.phone_number, subaccount_sid, incoming.sid,
        )
        return incoming.phone_number, incoming.sid
    except TwilioRestException as e:
        logger.error(
            "Failed to purchase number %s on sub-account %s: %s",
            phone_number, subaccount_sid, e,
        )
        raise


async def purchase_number(
    subaccount_sid: str,
    subaccount_token: str,
    phone_number: str,
) -> str:
    """Kept for the callers and tests that only need the number itself."""
    e164, _sid = await purchase_number_with_sid(
        subaccount_sid, subaccount_token, phone_number)
    return e164


async def release_number(
    subaccount_sid: str,
    subaccount_token: str,
    phone_number: str,
) -> bool:
    """Release a purchased number back to Twilio.

    Returns True only if the number was actually found and deleted. Returns False
    if it wasn't on this sub-account, and RAISES if Twilio rejects the request.

    It used to swallow every exception and return None, which was fine when the
    only caller was the provisioning rollback (best-effort cleanup of a number
    nobody had yet). It is not fine now that this is the primary release path: a
    caller that cannot tell success from failure clears the number off the tenant
    row anyway, and we lose the record of a number Twilio keeps billing us for.
    Callers must act on the result.
    """
    client = _sub_client(subaccount_sid, subaccount_token)
    numbers = client.incoming_phone_numbers.list(phone_number=phone_number, limit=1)
    if not numbers:
        logger.warning(
            "release_number: %s is not on sub-account %s — nothing released",
            phone_number, subaccount_sid,
        )
        return False
    numbers[0].delete()
    logger.info("Released number %s from sub-account %s", phone_number, subaccount_sid)
    return True


# Production WhatsApp: a single central OpenLines sender + approved Content
# Templates (one per owner event). No sandbox default — if the sender or the
# given template SID is unset, that WhatsApp send is skipped.
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")
TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID = os.getenv("TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID", "")
TWILIO_WHATSAPP_DEPOSIT_TEMPLATE_SID = os.getenv("TWILIO_WHATSAPP_DEPOSIT_TEMPLATE_SID", "")
TWILIO_WHATSAPP_CANCEL_TEMPLATE_SID  = os.getenv("TWILIO_WHATSAPP_CANCEL_TEMPLATE_SID", "")


def _wa_from() -> str:
    """Normalize the sender to the `whatsapp:+E164` form Twilio expects."""
    f = (TWILIO_WHATSAPP_FROM or "").strip()
    if not f:
        return ""
    return f if f.startswith("whatsapp:") else f"whatsapp:{f}"


def whatsapp_sender_configured() -> bool:
    return bool(_wa_from())


async def send_whatsapp_template(to_number: str, template_sid: str, variables: dict) -> bool:
    """Send a WhatsApp message via an APPROVED Twilio Content Template from the
    central OpenLines sender. Production only; never freeform. Returns False (and
    logs) if the sender or template SID isn't configured, or on error — callers
    treat as non-fatal."""
    import json

    if not (_wa_from() and template_sid):
        logger.warning("WhatsApp skipped: sender or template SID not configured")
        return False
    if not to_number:
        return False
    try:
        client = _master_client()
        msg = client.messages.create(
            from_=_wa_from(),
            to=f"whatsapp:{to_number}",
            content_sid=template_sid,
            content_variables=json.dumps(variables),
        )
        logger.info("WhatsApp template sent to %s (SID %s)", to_number, msg.sid)
        return True
    except TwilioRestException as e:
        logger.error("Failed to send WhatsApp to %s: %s", to_number, e)
        return False


async def send_sms(
    subaccount_sid: str,
    subaccount_token: str,
    from_number: str,
    to_number: str,
    body: str,
) -> bool:
    """Send an SMS from the tenant's provisioned number to the caller."""
    try:
        client = _sub_client(subaccount_sid, subaccount_token)
        message = client.messages.create(body=body, from_=from_number, to=to_number)
        logger.info("SMS sent to %s (SID %s)", to_number, message.sid)
        return True
    except TwilioRestException as e:
        logger.error("Failed to send SMS to %s: %s", to_number, e)
        return False


async def point_number_to_vapi(
    subaccount_sid: str,
    subaccount_token: str,
    phone_number: str,
    vapi_sip_uri: str,
) -> bool:
    try:
        client = _sub_client(subaccount_sid, subaccount_token)
        numbers = client.incoming_phone_numbers.list(phone_number=phone_number, limit=1)
        if not numbers:
            raise ValueError(f"Number {phone_number} not found on sub-account {subaccount_sid}")
        numbers[0].update(voice_url=vapi_sip_uri, voice_method="POST")
        logger.info(
            "Pointed %s to Vapi SIP URI on sub-account %s",
            phone_number, subaccount_sid,
        )
        return True
    except (TwilioRestException, ValueError) as e:
        logger.error(
            "Failed to point %s to Vapi on sub-account %s: %s",
            phone_number, subaccount_sid, e,
        )
        raise


# ---------------------------------------------------------------------------
# W9D — read-only provider facts the phone-number backfill needs.
#
# Both helpers exist so services/phone_backfill.py can be tested by patching one
# named function, and so every Twilio call in this codebase stays inside this
# module. Neither ever raises: a backfill that crashes on one tenant's
# unreachable sub-account is worse than one that reports and skips.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderNumberList:
    """The outcome of asking a provider what numbers an account holds.

    WHY THIS IS NOT JUST A LIST. The first version of this returned [] both when
    Twilio said "this account holds nothing" and when the call to Twilio failed.
    For ordinary runtime code that conflation is a safe default -- an empty list
    makes callers do nothing. For an OWNERSHIP MIGRATION it is not safe in either
    direction: reading a provider outage as "owns no numbers" would let a backfill
    conclude a live number does not exist, and reading a genuinely empty account as
    "unknown" would hide a real data inconsistency behind a retryable-looking
    error. W9E hit exactly that -- a tenant whose number had been released at
    Twilio was reported as `provider_numbers_unavailable`, which reads as a
    transient outage when it was a permanent fact.

    So the three states are distinct and the caller is forced to choose:

        ok and numbers      -> the account holds these
        ok and not numbers  -> the account holds NOTHING, authoritatively
        not ok              -> we do not know; never treat as either of the above

    error_detail is built from the exception TYPE, HTTP status and Twilio error
    code only. It never carries the provider's message body or URL, because those
    echo the request -- including the account SID used to authenticate.
    """
    status: str                              # "success" | "error"
    numbers: tuple[dict, ...] = ()
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "success"

    @property
    def is_empty(self) -> bool:
        """Authoritatively empty. False when the query failed -- unknown is not empty."""
        return self.ok and not self.numbers


def _safe_provider_error(exc: Exception) -> str:
    """A log-safe description of a provider failure. No message body, no URL."""
    parts = [type(exc).__name__]
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    if status is not None:
        parts.append(f"http={status}")
    if code is not None:
        parts.append(f"twilio_code={code}")
    return " ".join(parts)


async def fetch_subaccount_numbers(subaccount_sid: str,
                                   subaccount_token: str) -> ProviderNumberList:
    """Every IncomingPhoneNumber the sub-account holds, with success/error distinguished.

    Never raises. Missing credentials are an ERROR, not an empty account: we have
    not asked the provider anything, so we know nothing.
    """
    if not subaccount_sid or not subaccount_token:
        return ProviderNumberList(status="error", error_detail="missing_credentials")
    try:
        client = _sub_client(subaccount_sid, subaccount_token)
        rows = client.incoming_phone_numbers.list(limit=200)
    except Exception as e:
        logger.error("Could not list numbers on sub-account %s: %s", subaccount_sid, e)
        return ProviderNumberList(status="error", error_detail=_safe_provider_error(e))
    out: list[dict] = []
    for n in rows:
        out.append({
            "sid": getattr(n, "sid", "") or "",
            "phone_number": getattr(n, "phone_number", "") or "",
            "account_sid": getattr(n, "account_sid", "") or "",
            # The date the number entered the account -- i.e. when it was
            # provisioned. This is the only trustworthy activation timestamp
            # available; IncomingPhoneNumber carries no country field at all.
            "date_created": getattr(n, "date_created", None),
            "status": getattr(n, "status", "") or "",
            "origin": getattr(n, "origin", "") or "",
        })
    return ProviderNumberList(status="success", numbers=tuple(out))


async def lookup_iso_country(phone_number: str) -> str:
    """The ISO-3166-1 alpha-2 country of an E.164 number, per Twilio Lookup v2.

    WHY LOOKUP AND NOT A LOCAL RULE. IncomingPhoneNumber exposes no country, and
    every production number is +1 -- which is Canada AND the United States. A
    prefix rule would have to guess between them, and an analyzer-derived guess is
    exactly what must never become compliance data. Lookup answers from the
    provider's own numbering data (basic lookup, no data packages).

    Returns "" when unresolved, which the caller treats as a reason to SKIP.
    """
    number = str(phone_number or "").strip()
    if not number:
        return ""
    try:
        info = _master_client().lookups.v2.phone_numbers(number).fetch()
    except Exception as e:
        logger.error("Lookup v2 failed for a number: %s", e)
        return ""
    if getattr(info, "valid", None) is False:
        return ""
    return str(getattr(info, "country_code", "") or "").strip().upper()


@dataclass(frozen=True)
class NumberSearch:
    """Where an E.164 lives across every account we control.

    Same three-state discipline as ProviderNumberList: an incomplete sweep is not
    evidence of absence. `complete` is False if ANY account could not be read, which
    is what makes this safe to use as a precondition for deleting a reference.
    """
    status: str                          # "success" | "error"
    accounts: tuple[str, ...] = ()       # account SIDs holding the number
    scanned: int = 0
    unreadable: int = 0
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "success"

    @property
    def complete(self) -> bool:
        return self.ok and self.unreadable == 0

    @property
    def found_nowhere(self) -> bool:
        """Authoritatively absent: a COMPLETE sweep that found nothing."""
        return self.complete and not self.accounts


async def find_number_across_accounts(phone_number: str) -> NumberSearch:
    """Search the parent account and every sub-account for one E.164.

    Read-only. Used to prove a scalar phone pointer is stale before clearing it, and
    (later) for orphan detection.
    """
    number = str(phone_number or "").strip()
    if not number:
        return NumberSearch(status="error", error_detail="no_number")
    try:
        client = _master_client()
        accounts = client.api.accounts.list(limit=200)
    except Exception as e:
        logger.error("Could not enumerate accounts: %s", e)
        return NumberSearch(status="error", error_detail=_safe_provider_error(e))
    holders: list[str] = []
    unreadable = 0
    for acct in accounts:
        try:
            hits = client.api.accounts(acct.sid).incoming_phone_numbers.list(
                phone_number=number, limit=5)
        except Exception as e:
            unreadable += 1
            logger.error("Could not read numbers on account %s: %s", acct.sid,
                         _safe_provider_error(e))
            continue
        if hits:
            holders.append(acct.sid)
    return NumberSearch(status="success", accounts=tuple(holders),
                        scanned=len(accounts), unreadable=unreadable)


# ---------------------------------------------------------------------------
# W9G Stage X — Irish number DISCOVERY.
#
# THE DEFECT THIS REPLACES. _COUNTRY_CONFIG["IE"]["area_codes"] is empty, so
# find_available_number() fell straight through to an unfiltered national search and
# returned whatever was first in the pool -- W9C measured Portumna, Bandon, Birr for a
# Dublin business. Worse, `area_code=1` / `21` / `61` return ZERO results for Ireland:
# Twilio's area_code filter does not work outside NANP. `in_locality` does.
#
# WHY THIS IS ONLY CANDIDATE DISCOVERY. W9C proved the search result's `locality` is
# NOT the locality an address must satisfy: a number labelled "Dublin" demanded an
# address in Celbridge/Leixlip/Lucan/Maynooth (error 21615), and the purchase also
# requires an approved BundleSid (21649). So nothing here may be described as
# compliance-validated. Acceptance is only ever established by the purchase itself,
# with a real AddressSid and BundleSid -- which is a later gate, not this one.
#
# NOTHING IN THIS FUNCTION PURCHASES A NUMBER.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NumberCandidates:
    """Candidate numbers only. Never a statement about regulatory acceptance."""
    status: str                              # "success" | "error"
    candidates: tuple[dict, ...] = ()
    strategy: str = ""                       # how they were found
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "success"

    @property
    def is_empty(self) -> bool:
        return self.ok and not self.candidates

    #: Deliberately named so no caller can mistake this for a compliance result.
    compliance_validated = False


async def search_candidate_numbers(subaccount_sid: str, subaccount_token: str, *,
                                   iso_country: str, locality: str = "",
                                   limit: int = 20) -> NumberCandidates:
    """Find purchasable candidates, preferring the customer's own locality.

    For IE the strategy is locality-first and NEVER area_code. When a locality is
    given and yields nothing, it falls back to a national sweep but SAYS SO in
    `strategy`, so a caller can refuse to offer an out-of-locality number rather than
    discover the mismatch at purchase time.
    """
    country = str(iso_country or "").strip().upper()
    if not subaccount_sid or not subaccount_token or not country:
        return NumberCandidates(status="error", error_detail="missing_parameters")
    try:
        coll = _sub_client(subaccount_sid, subaccount_token) \
            .available_phone_numbers(country).local
    except Exception as e:
        return NumberCandidates(status="error", error_detail=_safe_provider_error(e))

    def _rows(**kw):
        rows = coll.list(limit=limit, **kw)
        return tuple({
            "phone_number": getattr(r, "phone_number", "") or "",
            "locality": getattr(r, "locality", None),
            "region": getattr(r, "region", None),
            # The provider's own words about what an address must satisfy. Carried
            # through so a caller can see it is 'local' and act accordingly.
            "address_requirements": getattr(r, "address_requirements", None),
            "capabilities": dict(getattr(r, "capabilities", {}) or {}),
            "beta": bool(getattr(r, "beta", False)),
        } for r in rows)

    wanted = str(locality or "").strip()
    try:
        if wanted:
            found = _rows(in_locality=wanted)
            if found:
                return NumberCandidates(status="success", candidates=found,
                                        strategy=f"in_locality={wanted}")
        national = _rows()
        return NumberCandidates(
            status="success", candidates=national,
            strategy=("national_fallback_locality_not_available" if wanted
                      else "national"))
    except Exception as e:
        return NumberCandidates(status="error", error_detail=_safe_provider_error(e))
