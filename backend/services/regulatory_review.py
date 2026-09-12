"""The proof that a customer authorised the facts they were actually shown (W9I-C).

THE RACE THIS CLOSES
A customer opens the review page, the page shows the twelve facts, and they click
"authorize". Between those two moments the persisted facts can change -- a second
browser tab, a support correction, another owner of the same tenant. Without a
binding, the authorisation records consent to whatever is in the database at the
instant of the click, which may be something nobody read. An authorisation is an
auditable claim about what a person agreed to; recording it against unseen facts
makes the claim false.

HOW
The review step issues a signed, short-lived token naming exactly what was shown:
the scope (tenant, country, end-user type, address) and the two digests (the
authorisation fingerprint of the twelve facts, and the requirements fingerprint of
the provider's form). The authorise step recomputes both digests from what is
persisted NOW and refuses unless they still match the token.

WHY BOTH HALVES ARE NEEDED
The token alone is not trusted: it is the customer's evidence of what they read,
never the source of what gets authorised. The fingerprint that is recorded is
always recomputed by `regulatory_engine.record_authorization` from the persisted
rows -- this module never supplies one. So a forged or replayed token cannot
choose which facts get authorised; the worst it can do is fail to match.
Conversely, recomputation alone is not enough either: it proves the facts are
unchanged since some moment, not since the moment this customer read them.

WHY NO TABLE
A durable review record would add a row per page view, carrying the customer's
digests, needing retention rules and RLS, to answer a question that is answerable
from a signature. The token is self-verifying, expires on its own, and leaves
nothing to purge. What it must never become is a place where a client can name the
fingerprint to authorise -- see `verify`, which compares rather than reads.

THE KEY is derived from ENCRYPTION_KEY_HEX, which this deployment already
requires, with a domain separator so a review signature can never be confused with
any other use of that secret. No new environment variable, and no fallback to an
unsigned mode: without the key the review step fails closed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time

logger = logging.getLogger(__name__)

SCHEME = "openlines.regulatory.review.v1"
SEP = "\x1f"

#: How long a review stays valid. Long enough to read twelve facts carefully and
#: talk to a colleague; short enough that a token found in a log or a browser
#: history later is worthless. A customer who takes longer is asked to re-review,
#: which is a re-read of the same page, not lost work.
TTL_SECONDS = 30 * 60

OK = "ok"
INVALID = "review_invalid"
EXPIRED = "review_expired"
SCOPE_MISMATCH = "review_wrong_scope"
STALE = "review_stale"


def _key() -> bytes:
    """A review-signing key derived from the deployment secret, domain-separated.

    Fails closed: security._get_enc_key raises when ENCRYPTION_KEY_HEX is absent
    or malformed, and an unsigned review token is not a degraded mode worth having.
    """
    from services.security import _get_enc_key
    return hmac.new(_get_enc_key(), SCHEME.encode("ascii"), hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _signed_payload(claims: dict) -> str:
    """The exact bytes signed, as text, so a test can read them."""
    return SEP.join([
        SCHEME,
        f"tenant_id={claims['tenant_id']}",
        f"iso_country={claims['iso_country']}",
        f"end_user_type={claims['end_user_type']}",
        f"address_id={claims['address_id']}",
        f"authorization_fingerprint={claims['authorization_fingerprint']}",
        f"requirements_fingerprint={claims['requirements_fingerprint']}",
        f"expires_at={claims['expires_at']}",
    ])


def issue(*, tenant_id: str, iso_country: str, end_user_type: str, address_id: str,
          authorization_fingerprint: str, requirements_fingerprint: str,
          now: float | None = None) -> str:
    """Mint the proof for one review of one exact fact set."""
    claims = {
        "tenant_id": str(tenant_id),
        "iso_country": str(iso_country),
        "end_user_type": str(end_user_type),
        "address_id": str(address_id),
        "authorization_fingerprint": str(authorization_fingerprint),
        # May legitimately be empty: the provider's requirement shape is not always
        # knowable at review time (an outage), and that must not block consent to
        # facts the customer can see. Empty binds to empty, never to "anything".
        "requirements_fingerprint": str(requirements_fingerprint or ""),
        "expires_at": int((now if now is not None else time.time()) + TTL_SECONDS),
    }
    sig = hmac.new(_key(), _signed_payload(claims).encode("utf-8"), hashlib.sha256).digest()
    return f"{_b64(json.dumps(claims, sort_keys=True).encode('utf-8'))}.{_b64(sig)}"


def verify(token: str, *, tenant_id: str, iso_country: str, end_user_type: str,
           address_id: str, current_authorization_fingerprint: str,
           current_requirements_fingerprint: str,
           now: float | None = None) -> dict:
    """Does this token prove the customer read the facts that are persisted NOW?

    Returns {"status": ..., "detail": ...}. Every mismatch is reported as its own
    status because they need different things from the customer: an expired review
    is re-read, a stale one means something changed and must be re-read WITH the
    change visible, and a wrong-scope one means this proof belongs to a different
    premises entirely.

    Comparisons are constant-time where they involve the signature. The digest
    comparisons are not secret-dependent -- both sides are computed by us from data
    the customer already has -- but are compared with the same primitive anyway so
    no future reader has to reason about which is which.
    """
    detail = lambda status, d="": {"status": status, "detail": d}

    if not token or "." not in str(token):
        return detail(INVALID, "malformed")
    body_b64, sig_b64 = str(token).rsplit(".", 1)
    try:
        raw = _unb64(body_b64)
        claims = json.loads(raw.decode("utf-8"))
        expected = hmac.new(_key(), _signed_payload(claims).encode("utf-8"),
                            hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig_b64)):
            return detail(INVALID, "bad_signature")
    except KeyError:
        return detail(INVALID, "incomplete_claims")
    except Exception:
        # A malformed token is a client problem, never a server error, and the
        # parse failure itself tells an attacker nothing worth having.
        return detail(INVALID, "undecodable")

    if int(claims["expires_at"]) <= int(now if now is not None else time.time()):
        return detail(EXPIRED, "review_expired")

    # Scope BEFORE freshness: a token for another tenant or another premises is not
    # a stale review of this one, and saying "stale" would send the customer to
    # re-read a page that was never the problem.
    for field, actual in (("tenant_id", tenant_id), ("iso_country", iso_country),
                          ("end_user_type", end_user_type), ("address_id", address_id)):
        if not hmac.compare_digest(str(claims.get(field) or ""), str(actual or "")):
            return detail(SCOPE_MISMATCH, field)

    if not hmac.compare_digest(str(claims.get("authorization_fingerprint") or ""),
                               str(current_authorization_fingerprint or "")):
        return detail(STALE, "facts_changed_since_review")
    if not hmac.compare_digest(str(claims.get("requirements_fingerprint") or ""),
                               str(current_requirements_fingerprint or "")):
        return detail(STALE, "requirements_changed_since_review")

    return {"status": OK, "detail": "", "claims": claims}
