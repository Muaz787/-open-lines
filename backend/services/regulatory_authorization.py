"""What the customer actually authorised, and whether it still holds (W9H.1A).

An authorisation is an AUDITABLE CUSTOMER EVENT, not a set of attributes on a
mutable row:

    "Representative X, at time Y, by method Z, authorised OpenLines to submit THIS
     exact set of customer-supplied regulatory identity and address facts to Twilio
     for THIS regulatory purpose."

Two things follow from that sentence, and this module exists to hold them.

FIRST, "this exact set of facts" has to be pinned. Every field it names is
MUTABLE -- migration 028 made them so deliberately, because a customer must be
able to correct their details after a rejection. So an authorisation that merely
pointed at those rows would silently change meaning as they were edited, and a
filing could go out naming a representative, or a premises, nobody authorised.
The fingerprint is what pins it: computed once, stored, and recomputed against the
current facts before anything is filed. It matches, or the authorisation does not
apply.

SECOND, "this regulatory purpose" includes the ADDRESS. Authorising the Limerick
premises is not authorising the Cork one, so the address facts are inside the
digest and an authorisation is scoped to one address row.

THERE IS EXACTLY ONE IMPLEMENTATION OF THIS DIGEST. Not one per layer: a second
copy in a router or a repository is a second definition of what the customer
agreed to, and the two would drift. The API layer never receives a fingerprint
from a client -- see `fingerprint_for` and the gates in regulatory_engine.
"""
from __future__ import annotations

import hashlib
import unicodedata

# ── the scheme ─────────────────────────────────────────────────────────────
# Versioned so the rules below can change without a new digest silently matching
# an old one. Bump it if ANY field, order or normalisation rule changes.
SCHEME = "openlines.authorization.v1"

# The unit separator. Chosen because it cannot occur in any of these values, so
# "a" + "bc" and "ab" + "c" can never serialise identically.
SEP = "\x1f"

# The facts the authorisation covers, in fixed semantic order. Measured against the
# live Ireland regulation RN5b82d0c001b4ef265770d022986f794f, whose end-user fields
# are business_name, business_website, business_registration_number, first_name,
# last_name, email, business_identity, is_subassigned, comments.
#
# WHAT IS DELIBERATELY ABSENT, AND WHY:
#   business_identity / is_subassigned -- system-sourced. W9G.3 resolved these from
#       a Twilio Support confirmation about our ARCHITECTURE; they are not facts
#       about the customer and are stripped from customer input. A customer cannot
#       authorise a statement they never made.
#   comments -- free text either side may edit, including us for operational notes.
#       Invalidating an authorisation because WE annotated a row would drain the
#       word "stale" of meaning. It is transmitted, so if it ever carries
#       substantive claims rather than notes, revisit this and bump SCHEME.
#   provider Address SID, Bundle SID, provider account SID -- provider handles, not
#       customer facts. The Address SID in particular changes if we ever recreate
#       the Address, which would expire an authorisation for a reason the customer
#       has no visibility of.
#   requirements_fingerprint -- describes TWILIO's requirement shape. If Twilio
#       changes its form, that is not the customer withdrawing consent. It is
#       tracked separately, on the profile, for exactly that reason.
FIELDS: tuple[str, ...] = (
    "business_name",
    "business_registration_number",
    "business_website",
    "authorized_rep_first_name",
    "authorized_rep_last_name",
    "authorized_rep_email",
    "address_street",
    "address_street_secondary",
    "address_city",
    "address_region",
    "address_postal_code",
    "address_iso_country",
)

# Uppercased and stripped of whitespace rather than casefolded: a postal code is a
# code, and "V94 HT0X" and "v94ht0x" are the same Eircode.
_POSTAL_FIELDS = frozenset({"address_postal_code"})
# Uppercased: ISO 3166-1 alpha-2 has one canonical form.
_UPPER_FIELDS = frozenset({"address_iso_country"})


def normalize(field: str, value) -> str:
    """One value, reduced to its canonical form.

    Twilio does NOT canonicalise addresses -- W9H-QA.2 submitted a real Limerick
    address with auto_correct_address=True and got every field back verbatim -- so
    the normalisation has to be ours, and it has to be stated rather than assumed.
    """
    if value is None:
        return ""
    text = str(value)
    # NFKC first: it folds compatibility forms, so a full-width or ligature
    # character cannot masquerade as a different fact.
    text = unicodedata.normalize("NFKC", text)
    # Collapse ALL whitespace runs (including tabs and newlines) to one space, and
    # trim. A customer who typed two spaces did not change their business name.
    text = " ".join(text.split())
    if field in _POSTAL_FIELDS:
        return text.replace(" ", "").upper()
    if field in _UPPER_FIELDS:
        return text.upper()
    # casefold, not lower: it is the aggressive form, correct for caseless matching
    # beyond ASCII. Applied to the email too -- domains are case-insensitive, and
    # treating the local part as caseless matches how every provider here behaves.
    return text.casefold()


def canonical_payload(facts: dict) -> str:
    """The exact bytes that get hashed, as text, so a test can read them."""
    parts = [SCHEME]
    for field in FIELDS:
        parts.append(f"{field}={normalize(field, facts.get(field))}")
    return SEP.join(parts)


def fingerprint(facts: dict) -> str:
    """sha256 over the canonical payload, lowercase hex."""
    return hashlib.sha256(canonical_payload(facts).encode("utf-8")).hexdigest()


# ── assembling the facts from what we store ────────────────────────────────

def facts_from(details: dict | None, address: dict | None) -> dict:
    """Gather the 12 authorised facts from the rows that hold them.

    Deliberately the ONLY place the two tables are joined into one fact set, so the
    authorisation gate and the authorisation writer cannot disagree about what was
    covered.
    """
    d = details or {}
    a = address or {}
    return {
        "business_name": d.get("business_name"),
        "business_registration_number": d.get("business_registration_number"),
        "business_website": d.get("business_website"),
        "authorized_rep_first_name": d.get("authorized_rep_first_name"),
        "authorized_rep_last_name": d.get("authorized_rep_last_name"),
        "authorized_rep_email": d.get("authorized_rep_email"),
        "address_street": a.get("street"),
        "address_street_secondary": a.get("street_secondary"),
        "address_city": a.get("city"),
        "address_region": a.get("region"),
        "address_postal_code": a.get("postal_code"),
        "address_iso_country": a.get("iso_country"),
    }


def fingerprint_for(details: dict | None, address: dict | None) -> str:
    """The digest of the CURRENTLY PERSISTED facts.

    The system computes this; a client never supplies it. A caller-supplied digest
    would let anyone assert that whatever is in the database today is what a
    customer agreed to -- which is the entire property this module exists to
    provide.
    """
    return fingerprint(facts_from(details, address))


# ── the outcomes a gate can report ─────────────────────────────────────────
AUTHORIZED = "authorized"
NOT_RECORDED = "authorization_not_recorded"
REVOKED = "authorization_revoked"
STALE = "authorization_stale"
WRONG_SCOPE = "authorization_wrong_scope"

# The permitted ways an authorisation reaches us. A closed vocabulary rather than
# free text, so "email" and "e-mail" cannot both exist and an audit can group by it.
METHODS = ("dashboard", "email", "phone", "written_other")
