"""
W4 — turn what a caller said into one of the tenant's locations, or refuse.

PURE. No database, no HTTP, no Square. It is handed a list of the tenant's
locations and returns a decision; the caller does the I/O and the enforcement.

The whole design goal is that it cannot quietly be wrong. Every ambiguous or
unrecognised input returns candidates for the assistant to ask about, and there is
no code path that picks a location the caller did not name.

WHY THE THRESHOLDS ARE HIGH
The existing spoken-name matchers elsewhere in the codebase use difflib at cutoff
0.5 and fall back to the first item when nothing matches. That is tolerable for a
service name — the caller hears the wrong service read back and corrects it. It is
not tolerable for a location: booking someone into the wrong city is not something
they notice until they arrive. Hence 0.82, a required gap to the runner-up, and no
fallback at all.
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field

from services import location_normalization as norm

logger = logging.getLogger(__name__)

FUZZY_MIN_SCORE = 0.82
FUZZY_MIN_GAP = 0.08

# Square location ids look like L0Q8GTAZCHD42. A caller never says one; a model
# that emits one is either hallucinating or has been fed an id it should never
# have seen. Either way it must not resolve.
_PROVIDER_ID_SHAPE = re.compile(r"^[A-Z0-9]{10,}$")

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
UNRESOLVED = "unresolved"
NO_CANDIDATES = "no_candidates"


@dataclass
class Resolution:
    status: str
    location: dict | None = None
    candidates: list[dict] = field(default_factory=list)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == RESOLVED

    def candidate_names(self) -> list[str]:
        return [c.get("name") or c.get("slug") or "" for c in self.candidates]


def looks_like_provider_id(value: str) -> bool:
    """Reject anything shaped like a provider identifier before matching."""
    return bool(_PROVIDER_ID_SHAPE.match((value or "").strip()))


def _score(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def resolve(
    spoken: str,
    locations: list[dict],
    *,
    business_name: str = "",
    provider_ids: set[str] | None = None,
) -> Resolution:
    """Match `spoken` against the tenant's locations.

    `locations` must already be filtered to what the caller may actually be sent
    to — this function does not know about active, booking_enabled or bindings,
    and deliberately cannot be used to reach a location the caller filtered out.
    """
    if not locations:
        return Resolution(NO_CANDIDATES, reason="tenant has no eligible locations")

    raw = (spoken or "").strip()
    if not raw:
        return Resolution(UNRESOLVED, candidates=locations, reason="empty input")

    # Security: an id must never be a shortcut past human-readable resolution,
    # whether it is one we know or merely shaped like one.
    if looks_like_provider_id(raw) or raw in (provider_ids or set()):
        logger.warning("location_resolver: refused provider-id-shaped input")
        return Resolution(UNRESOLVED, candidates=locations,
                          reason="provider identifiers are not accepted as location input")

    needle = norm.normalize(raw, business_name)
    if not needle:
        # e.g. the caller said only "the shop" — all noise, nothing to match on.
        return Resolution(UNRESOLVED, candidates=locations, reason="no meaningful tokens")

    # 1. exact slug
    hits = [l for l in locations if (l.get("slug") or "").lower() == needle]
    if len(hits) == 1:
        return Resolution(RESOLVED, hits[0], reason="slug")

    # 2. exact alias
    hits = [l for l in locations
            if any(norm.normalize(a, business_name) == needle for a in (l.get("aliases") or []))]
    if len(hits) == 1:
        return Resolution(RESOLVED, hits[0], reason="alias")
    if len(hits) > 1:
        return Resolution(AMBIGUOUS, candidates=hits, reason="alias matched several locations")

    # 3. exact normalized name
    hits = [l for l in locations if norm.normalize(l.get("name") or "", business_name) == needle]
    if len(hits) == 1:
        return Resolution(RESOLVED, hits[0], reason="name")
    if len(hits) > 1:
        return Resolution(AMBIGUOUS, candidates=hits, reason="name matched several locations")

    # 4. unique containment — "cork branch" contains "cork"
    def _haystacks(l: dict) -> list[str]:
        out = [(l.get("slug") or "").lower(),
               norm.normalize(l.get("name") or "", business_name)]
        out += [norm.normalize(a, business_name) for a in (l.get("aliases") or [])]
        return [h for h in out if h]

    hits = [l for l in locations
            if any(h and (h in needle or needle in h) for h in _haystacks(l))]
    if len(hits) == 1:
        return Resolution(RESOLVED, hits[0], reason="containment")
    if len(hits) > 1:
        return Resolution(AMBIGUOUS, candidates=hits, reason="matched several locations")

    # 5. conservative fuzzy — a clear winner, or nothing
    scored = sorted(
        ((max((_score(needle, h) for h in _haystacks(l)), default=0.0), l) for l in locations),
        key=lambda p: p[0], reverse=True)
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    if best_score >= FUZZY_MIN_SCORE and (best_score - runner_up) >= FUZZY_MIN_GAP:
        return Resolution(RESOLVED, best, reason=f"fuzzy {best_score:.2f}")
    if best_score >= FUZZY_MIN_SCORE:
        # Close to more than one. Two similar names is exactly when guessing is
        # most tempting and most wrong.
        return Resolution(AMBIGUOUS, candidates=[l for s, l in scored if s >= FUZZY_MIN_SCORE],
                          reason=f"no clear winner ({best_score:.2f} vs {runner_up:.2f})")
    return Resolution(UNRESOLVED, candidates=locations,
                      reason=f"best score {best_score:.2f} below {FUZZY_MIN_SCORE}")


def clarification_text(candidates: list[dict], *, lead: str = "") -> str:
    """'Cork, Dublin or Limerick' — names only, never ids."""
    names = [c.get("name") or c.get("slug") or "" for c in candidates if (c.get("name") or c.get("slug"))]
    if not names:
        return lead or "I'm not sure which location you meant."
    if len(names) == 1:
        listed = names[0]
    elif len(names) == 2:
        listed = f"{names[0]} or {names[1]}"
    else:
        listed = ", ".join(names[:-1]) + f" or {names[-1]}"
    return (lead or "Which location would you like") + f" — {listed}?"
