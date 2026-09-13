"""Where an OAuth round trip should put the customer back.

THE DEFECT THIS CLOSES
Every callback redirected to a full dashboard page. When the authorisation runs
in a popup opened by onboarding, that meant the popup loaded the entire
dashboard -- auth check, tenant fetch, appointments, call state -- rendered it
for as long as that took, and only then got closed by the opener's next poll.
The customer watched a dashboard they had not asked for appear and vanish in
the middle of signing up.

ONE VOCABULARY, THREE PROVIDERS
Square already carried an origin through its OAuth state and mapped it to a
page; Google and Microsoft carried nothing and hardcoded the calendar page.
Rather than add a second and third scheme, this module owns the vocabulary and
the mapping, and all three callers use it.

WHY A CLOSED ENUM AND NEVER A URL
The browser hands back a context, so it is untrusted input. It selects between
a fixed set of OUR OWN paths and nothing else: there is no parameter anywhere
in this module that can express an external host, a scheme, or a path segment.
An unrecognised value resolves to the default rather than being rejected, so a
mangled round trip still lands the customer somewhere sensible.

Tampering is therefore bounded to "arrive at a different one of our own pages" --
which is where the customer was already going before this existed. The identity
that matters is not in the context at all: tenant_id comes from the single-use
state nonce the callback validates, never from the query string.
"""
from __future__ import annotations

import re
from urllib.parse import urlencode

#: The complete set of places an OAuth round trip may return to.
ONBOARDING = "onboarding"
CALENDAR = "calendar"
PAYMENTS = "payments"

ORIGINS = (ONBOARDING, CALENDAR, PAYMENTS)

#: Where an unknown, absent or malformed context goes. The calendar page is the
#: pre-existing behaviour for every provider that had no context at all.
DEFAULT_ORIGIN = CALENDAR

#: The completion surface. Deliberately not under /dashboard: the whole point is
#: that no dashboard route, layout or query is loaded.
COMPLETION_PATH = "/oauth/complete"

_UUID = re.compile(r"^[0-9a-fA-F-]{8,64}$")

#: Only these separators may appear in a state string, and only one of them.
_SEP = ":"


def normalize(origin: str | None) -> str:
    """Coerce an untrusted context to a known one. Never raises."""
    value = str(origin or "").strip().lower()
    return value if value in ORIGINS else DEFAULT_ORIGIN


def encode_state(nonce: str, origin: str | None) -> str:
    """The state parameter handed to the provider: the nonce, plus a context.

    The nonce stays exactly what the store issued -- it is what proves the round
    trip and yields the tenant. The context rides alongside it because the
    oauth_states row has nowhere to put one, and giving it somewhere would be a
    migration for a value whose worst case is landing on the wrong page of ours.
    """
    return f"{nonce}{_SEP}{normalize(origin)}"


def decode_state(raw: str | None) -> tuple[str, str]:
    """Split a state parameter into (nonce, context).

    A state without a context is a live round trip that began before this
    existed, and must keep working: it resolves to the default, which is the
    page it would have gone to anyway.
    """
    value = str(raw or "")
    if _SEP not in value:
        return value, DEFAULT_ORIGIN
    nonce, _, origin = value.rpartition(_SEP)
    return nonce, normalize(origin)


def page_for(frontend_url: str, origin: str, tenant_id: str) -> str:
    """The real page behind a context. The only place a path is ever built."""
    base = str(frontend_url).rstrip("/")
    origin = normalize(origin)
    if origin == ONBOARDING:
        return f"{base}/onboarding"
    safe_tenant = tenant_id if _UUID.match(str(tenant_id or "")) else ""
    if not safe_tenant:
        # Nothing to address a tenant page with. The marketing root is the only
        # honest destination, and is never an external host.
        return f"{base}/"
    return f"{base}/dashboard/{safe_tenant}/{origin}"


def completion_url(frontend_url: str, *, origin: str, tenant_id: str,
                   provider: str, status: str) -> str:
    """The lightweight page every callback returns to.

    It decides between closing itself and continuing to `page_for`, because only
    the browser knows whether this window has an opener -- the server cannot.
    """
    params = urlencode({
        "ctx": normalize(origin),
        "tenant": str(tenant_id or ""),
        "provider": str(provider or ""),
        "status": "connected" if status == "connected" else "error",
    })
    return f"{str(frontend_url).rstrip('/')}{COMPLETION_PATH}?{params}"
