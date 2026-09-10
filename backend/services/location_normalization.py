"""
The single definition of how a location name is normalised.

Adoption derives a slug from a Square name; the resolver matches what a caller
said against slugs, names and aliases. Those must agree on what "Dani Cork", "the
Cork shop" and "Cork" reduce to — two subtly different answers would mean a
location adopted under one spelling and unreachable under another.

PURE. No database, no HTTP, no Square, no provider concepts. Everything here is a
string in, a string out, so both callers can be tested without a fixture.
"""
from __future__ import annotations

import re

# Words a caller adds that carry no location meaning. Stripped from BOTH sides of
# a comparison, so "the Cork shop" and "Cork" reduce to the same token.
NOISE_TOKENS: frozenset[str] = frozenset({
    "the", "a", "an", "at", "in", "of", "our", "your", "my", "please",
    "location", "locations", "store", "shop", "branch", "showroom", "showrooms",
    "office", "clinic", "studio", "salon", "site", "place", "one",
})


def slugify(value: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace to single hyphens."""
    slug = (value or "").lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def tokens(value: str) -> list[str]:
    """Slug tokens, in order, empties dropped."""
    return [t for t in slugify(value).split("-") if t]


def meaningful_tokens(value: str, business_name: str = "") -> list[str]:
    """Tokens with noise words and the business's own name removed.

    The business name is stripped because it repeats across every location and so
    distinguishes nothing: for a tenant called DANI, "Dani Cork" and "Dani Dublin"
    are told apart by the second word alone.
    """
    biz = set(tokens(business_name))
    return [t for t in tokens(value) if t not in biz and t not in NOISE_TOKENS]


def normalize(value: str, business_name: str = "") -> str:
    """The canonical comparison form. '' when nothing meaningful survives."""
    return "-".join(meaningful_tokens(value, business_name))


def derive_slug(provider_name: str, business_name: str = "") -> str:
    """'Dani Cork' for a tenant called 'DANI' -> 'cork'.

    Falls back to the full slug when stripping leaves nothing, so a location whose
    entire name IS the business name still gets a usable key instead of ''.
    """
    return normalize(provider_name, business_name) or slugify(provider_name)
