"""
W4 — authoritative per-call location state, and the legacy/multi cutover.

THE CUTOVER RULE, WHICH IS TEMPORARY AND MUST BE RETIRED
--------------------------------------------------------
A tenant is in multi-location mode when it has >= 2 ACTIVE ADOPTED locations —
active rows that carry a provider binding. Everyone else stays on the legacy path,
reading tenants.square_location_id exactly as before.

This is deliberate transitional compatibility, not a permanent design. Today every
production tenant has exactly one backfilled location, so every tenant is legacy
and W4 changes nothing for them. The rule exists so the new path can be proven on
a pilot tenant without a data migration for everybody else.

RETIREMENT: when tenants.square_location_id stops being authoritative (the runtime
cutover phase), delete is_multi_location() and make the location-scoped path the
only path. Until then, any behaviour that depends on this function is by definition
transitional. Tests reference this docstring so the rule cannot become permanent by
being forgotten.

Postgres holds the state, never process memory: uvicorn runs with no pinned worker
count and a redeploy clears memory mid-call.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from db import locations as db_loc
from services import location_resolver as resolver
from services.location_sync import SQUARE, STATUS_MISSING

logger = logging.getLogger(__name__)

# Generous enough to outlive any real call, short enough that an orphan is gone
# within a day. Cleanup is normally the end-of-call delete; this is the backstop.
STATE_TTL_HOURS = 6

SOURCE_UNKNOWN = "unknown"
SOURCE_PHONE = "phone_number"
SOURCE_CALLER = "caller_selected"
SOURCE_SOLE = "sole_location"
SOURCE_LEGACY = "legacy_single_location"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

def binding_is_usable(binding: dict | None) -> bool:
    """A binding can be booked against only if it still points somewhere real."""
    if not binding:
        return False
    if binding.get("provider_status") == STATUS_MISSING:
        return False
    return bool((binding.get("provider_location_id") or "").strip())


async def adopted_locations(tenant_id: str) -> list[dict]:
    """Active locations that carry a usable provider binding, each annotated with
    its binding. This is what "adopted" means for the cutover rule."""
    locs = await db_loc.list_locations(tenant_id, active_only=True)
    if not locs:
        return []
    bindings = {str(b.get("tenant_location_id")): b
                for b in await db_loc.list_bindings(tenant_id, provider=SQUARE)
                if b.get("tenant_location_id")}
    out = []
    for loc in locs:
        binding = bindings.get(str(loc.get("id")))
        if binding_is_usable(binding):
            out.append({**loc, "_binding": binding})
    return out


async def is_multi_location(tenant_id: str) -> tuple[bool, list[dict]]:
    """(multi_location_mode, adopted_locations). See the cutover note above."""
    adopted = await adopted_locations(tenant_id)
    return (len(adopted) >= 2), adopted


def eligible_for_availability(locations: list[dict]) -> list[dict]:
    """Adopted AND switched on. A location the operator has not activated is not
    offered to a caller, and is not a clarification candidate either — offering
    somewhere we cannot serve is worse than not mentioning it."""
    return [l for l in locations if l.get("booking_enabled")]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

async def get_or_create(vapi_call_id: str, tenant_id: str,
                        called_number: str = "") -> dict | None:
    """Lazily create this call's state. Idempotent and concurrency-safe.

    Returns None when there is no call id — the caller must then fail closed
    rather than fall back to some anonymous shared row.
    """
    if not vapi_call_id or not tenant_id:
        return None

    existing = await db_loc.get_call_state(vapi_call_id)
    if existing:
        # A call id belongs to exactly one tenant. A mismatch means either a
        # collision or a crossed wire; either way refuse rather than serve it.
        if str(existing.get("tenant_id")) != str(tenant_id):
            logger.error("call_location: call %s belongs to tenant %s, not %s — refusing",
                         vapi_call_id, existing.get("tenant_id"), tenant_id)
            return None
        return existing

    row = {
        "vapi_call_id": vapi_call_id,
        "tenant_id": tenant_id,
        "called_number": called_number or None,
        "initial_location_id": None,
        "active_location_id": None,
        "location_source": SOURCE_UNKNOWN,
        "switch_count": 0,
        "expires_at": (_now() + timedelta(hours=STATE_TTL_HOURS)).isoformat(),
    }
    try:
        created = await db_loc.insert_call_state(row)
        if created:
            return created
    except Exception as e:
        # Two tool calls can race on the first turn. The primary key settles it;
        # whoever lost simply reads the winner's row.
        logger.info("call_location: create raced for %s (%s) — reading existing",
                    vapi_call_id, str(e)[:120])
    return await db_loc.get_call_state(vapi_call_id)


async def set_active_location(state: dict, location: dict, source: str) -> dict:
    """Point the call at a location. switch_count moves only on a real change, so
    it measures the caller changing their mind, not tool-call volume."""
    location_id = str(location.get("id"))
    previous = str(state.get("active_location_id") or "")
    if previous == location_id:
        return state

    update = {"active_location_id": location_id, "location_source": source}
    if previous:
        update["switch_count"] = int(state.get("switch_count") or 0) + 1
    if not state.get("initial_location_id"):
        update["initial_location_id"] = location_id

    await db_loc.update_call_state(state["vapi_call_id"], state["tenant_id"], update)
    logger.info("call_location: call %s active location %s -> %s (%s)",
                state["vapi_call_id"], previous or "none", location_id, source)
    return {**state, **update}


async def clear(vapi_call_id: str) -> None:
    """End-of-call cleanup. Best effort — never let this affect call completion."""
    try:
        await db_loc.delete_call_state(vapi_call_id)
    except Exception as e:
        logger.warning("call_location: cleanup failed for %s: %s", vapi_call_id, e)


async def purge_expired() -> int:
    """TTL backstop for calls whose end-of-call-report never arrived. Idempotent."""
    try:
        return await db_loc.purge_expired_call_state(_now().isoformat())
    except Exception as e:
        logger.error("call_location: TTL purge failed: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------

async def resolve_active_location(
    state: dict, spoken: str, eligible: list[dict], business_name: str = "",
) -> tuple[dict | None, resolver.Resolution | None, dict]:
    """Decide which location this request is for.

    Precedence, exactly:
      1. a valid explicit human-readable argument (may switch the active location)
      2. the call's existing active_location_id
      3. otherwise unresolved -> clarification

    is_default is never consulted, and neither is tenants.square_location_id. A
    multi-location tenant has no safe default: picking one would be guessing which
    city the caller meant.

    An invalid or ambiguous explicit argument NEVER destroys a previously resolved
    location — the caller mumbled, they did not un-choose Cork.
    """
    if (spoken or "").strip():
        provider_ids = {(l.get("_binding") or {}).get("provider_location_id")
                        for l in eligible}
        res = resolver.resolve(spoken, eligible, business_name=business_name,
                               provider_ids={p for p in provider_ids if p})
        if res.ok:
            state = await set_active_location(state, res.location, SOURCE_CALLER)
            return res.location, res, state
        return None, res, state

    active_id = str(state.get("active_location_id") or "")
    if active_id:
        current = next((l for l in eligible if str(l.get("id")) == active_id), None)
        if current:
            return current, None, state
        # It was eligible earlier and is not now — deactivated or disabled
        # mid-call. Fail closed rather than serve a stale location.
        logger.warning("call_location: active location %s no longer eligible for call %s",
                       active_id, state.get("vapi_call_id"))

    return None, resolver.Resolution(resolver.UNRESOLVED, candidates=eligible,
                                     reason="no location established"), state


# ---------------------------------------------------------------------------
# Assistant context — human-readable names only
# ---------------------------------------------------------------------------

LOCATION_PROMPT_HEADER = "BUSINESS LOCATIONS"


def build_location_prompt_block(location_names: list[str]) -> str:
    """The multi-location block injected into the system prompt.

    Names only. No tenant_location UUIDs, no Square provider ids, no binding ids —
    anything the model can see, it can say out loud or pass back to a tool, and an
    id in either place is a bug.
    """
    if len(location_names) < 2:
        return ""
    listed = "\n".join(f"- {n}" for n in location_names)
    if len(location_names) == 2:
        spoken = f"{location_names[0]} or {location_names[1]}"
    else:
        spoken = ", ".join(location_names[:-1]) + f" or {location_names[-1]}"
    return (
        f"\n\n{LOCATION_PROMPT_HEADER}\n"
        f"This business has more than one location:\n{listed}\n"
        f"- Before checking appointment availability you MUST know which location the "
        f"caller wants. If they have not said, ask: \"Which location would you like "
        f"— {spoken}?\"\n"
        f"- Pass the location the caller names in the `location` argument of "
        f"check_availability, exactly as they said it.\n"
        f"- NEVER guess or assume a location, and never pick one because it is the "
        f"nearest or the busiest.\n"
        f"- If the caller changes to a different location later in the call, use the "
        f"new one from then on.\n"
        f"- General questions that do not depend on location — what you sell, "
        f"opening policy, whether you take walk-ins — do NOT require asking which "
        f"location first.\n"
        f"- Refer to locations only by these names. Never mention internal "
        f"identifiers or codes."
    )


async def location_prompt_block_for(tenant: dict) -> str:
    """Fetch names and build the block. Empty string for single-location tenants,
    so their prompt is byte-identical to today's."""
    tenant_id = str(tenant.get("id") or "")
    if not tenant_id:
        return ""
    try:
        multi, adopted = await is_multi_location(tenant_id)
        if not multi:
            return ""
        names = [l.get("name") for l in eligible_for_availability(adopted) if l.get("name")]
        return build_location_prompt_block(names)
    except Exception as e:
        logger.warning("call_location: prompt block failed for %s: %s", tenant_id, e)
        return ""
