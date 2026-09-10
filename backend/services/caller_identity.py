"""
W5.2 — a caller's name is something they told us, not something the model produced.

A live call booked correctly and still wrote the wrong thing down. The caller was
recognised but their lead row had no name, so the assistant-request prompt said
"RETURNING CALLER (name not captured yet)" — and the model, asked for a
caller_name, handed back the phrase it had just read: "Returning Caller". That
string became a real Square customer record and the appointment row.

The phrase is conversational state describing WHO IS SPEAKING. It is not their
name. Persisting it produces a customer file nobody can search, a confirmation
addressed to "Returning Caller", and a record that looks like data but is an echo
of our own prompt.

The rule this module encodes: a name is persisted only if a human supplied it, or
if we already held one from trusted history. Otherwise we hold no name at all —
the phone number is the identity key, and an absent name is honest where an
invented one is not.

Deliberately a short list, not a heuristic. Guessing at what "sounds like a real
name" would eventually discard somebody's actual name, which is a worse failure
than storing one placeholder we did not anticipate.
"""
from __future__ import annotations

import re

# Lowercase, punctuation-free forms. Matching is exact against the whole
# normalized string — never a substring, so "Mark Guest" and "Anonymous Achebe"
# are untouched.
PLACEHOLDER_NAMES = frozenset({
    "returning caller",
    "caller",
    "customer",
    "unknown",
    "unknown caller",
    "guest",
    "anonymous",
    "not provided",
    "na",              # covers "N/A" and "n.a." once punctuation is stripped
    "none",
    "new caller",
    "test",
})

_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def _normalize(name: str) -> str:
    """Casefold, drop punctuation, collapse whitespace. 'N/A ' -> 'na'."""
    if not name:
        return ""
    return _SPACE.sub(" ", _PUNCT.sub("", str(name))).strip().casefold()


def is_placeholder_name(name: str | None) -> bool:
    """True when this is conversational filler rather than an identity.

    Empty is also 'not an identity' — callers of this module should treat both the
    same way, since neither is safe to write down.
    """
    return _normalize(name or "") in PLACEHOLDER_NAMES or not (name or "").strip()


def resolve_caller_name(supplied: str | None, persisted: str | None = None) -> str:
    """The trust ladder, in order. Returns '' when nothing is trustworthy.

    1. A real name the caller gave on this call.
    2. A real name we already stored for them.
    3. Nothing.

    There is deliberately no fourth step. A name is never derived from the phone
    number, the business name, the greeting, or anything the model inferred — each
    of those produces a plausible string that is not the person's name.
    """
    if not is_placeholder_name(supplied):
        return (supplied or "").strip()
    if not is_placeholder_name(persisted):
        return (persisted or "").strip()
    return ""
