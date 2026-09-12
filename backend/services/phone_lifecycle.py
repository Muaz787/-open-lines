"""Lifecycle vocabulary for tenant_phone_numbers (W9D).

WHY THIS MODULE EXISTS
Migration 027 encodes three invariants as partial unique indexes, and the
application has to make the same decisions before it writes — "may I insert this
row", "does this number route". If those predicates are spelled out twice, in SQL
and again in Python, they drift, and the drift surfaces as a 23505 in production
rather than as a refusal in code.

So the predicates live here once, as data, and two things answer to them:
  * the application, which calls the helpers below
  * migration 027, which tests/test_migration_027_contract.py asserts declares
    exactly these status sets in exactly these index predicates

The repository has no test database, so a partial unique index cannot be exercised
against real Postgres here. Cross-checking the DDL against the constants the code
uses is the strongest available substitute: a rewrite that widens an index
predicate without widening the code (or vice versa) fails the contract test.

NOTHING HERE TOUCHES THE PROVIDER. These are set-membership rules only.
"""
from __future__ import annotations

# ── purpose ────────────────────────────────────────────────────────────────
PURPOSE_TEMPORARY = "temporary_test"
PURPOSE_PERMANENT = "permanent"
PURPOSES = (PURPOSE_TEMPORARY, PURPOSE_PERMANENT)

# ── status ─────────────────────────────────────────────────────────────────
STATUS_PROVISIONING = "provisioning"
STATUS_ACTIVE = "active"
STATUS_RETIRING = "retiring"
STATUS_RELEASED = "released"
STATUS_FAILED = "failed"
STATUSES = (STATUS_PROVISIONING, STATUS_ACTIVE, STATUS_RETIRING,
            STATUS_RELEASED, STATUS_FAILED)

# ── the three index predicates, verbatim ───────────────────────────────────

#: A number that may receive an inbound call. 'provisioning' is EXCLUDED: the
#: webhook is not configured yet, so routing a caller there would ring nothing.
ROUTABLE_STATUSES = (STATUS_ACTIVE, STATUS_RETIRING)

#: tpn_one_current_permanent. A retiring predecessor may coexist with the current
#: one, because replacing a number requires the old one to keep ringing.
#: 'provisioning' is INCLUDED, which is what makes a retried promotion idempotent.
CURRENT_PERMANENT_STATUSES = (STATUS_PROVISIONING, STATUS_ACTIVE)

#: tpn_one_live_temporary. Stricter than the permanent rule on purpose: a test
#: number has no replacement story, so a second one alongside a retiring one is a
#: billing leak, not a migration.
LIVE_TEMPORARY_STATUSES = (STATUS_PROVISIONING, STATUS_ACTIVE, STATUS_RETIRING)

#: tpn_owned_e164_key. A number we currently hold. 'released' and 'failed' are
#: excluded so a released number is re-purchasable and a failed purchase never
#: squats an E.164 we never owned.
OWNED_E164_STATUSES = (STATUS_PROVISIONING, STATUS_ACTIVE, STATUS_RETIRING)

#: Statuses a release may transition OUT of. Identical in membership to
#: OWNED_E164_STATUSES today and deliberately spelled separately: that set
#: answers "do we hold this E.164", this one answers "may this row be released".
#: They would diverge the moment a status is added that we own but must not
#: release, and a shared constant would hide that.
RELEASABLE_STATUSES = (STATUS_PROVISIONING, STATUS_ACTIVE, STATUS_RETIRING)

#: End states. A row here is history: not routable, not a uniqueness conflict,
#: and never transitioned again. 'failed' is terminal for a purchase that never
#: completed; 'released' for a number we held and gave back.
TERMINAL_STATUSES = (STATUS_RELEASED, STATUS_FAILED)

#: Which statuses each purpose is allowed at most one of, per tenant.
LIVE_STATUSES_BY_PURPOSE = {
    PURPOSE_PERMANENT: CURRENT_PERMANENT_STATUSES,
    PURPOSE_TEMPORARY: LIVE_TEMPORARY_STATUSES,
}

#: Permitted provenance for activated_at. 'tenant_created_at' is deliberately
#: absent: tenant creation is not phone activation, so the backfill writes NULL
#: rather than inventing history.
ACTIVATED_AT_SOURCES = ("provider_date_created", "promotion")


def is_routable(row: dict) -> bool:
    """Would an inbound call to this row's number reach this tenant?"""
    return str(row.get("status") or "") in ROUTABLE_STATUSES


def live_conflict(rows: list[dict], candidate: dict) -> str:
    """Name the uniqueness invariant `candidate` would breach against `rows`, or ''.

    This is the application-side mirror of the three partial unique indexes. It
    exists so a caller can refuse cleanly instead of discovering the constraint as
    a 23505 mid-provisioning — the database remains the enforcer of last resort.

    `rows` are the tenant's existing rows. `candidate` is not yet inserted.
    """
    purpose = str(candidate.get("purpose") or "")
    status = str(candidate.get("status") or "")
    e164 = str(candidate.get("e164") or "")
    cid = candidate.get("id")

    others = [r for r in rows if r.get("id") is None or r.get("id") != cid]

    live = LIVE_STATUSES_BY_PURPOSE.get(purpose, ())
    if status in live:
        for r in others:
            if str(r.get("purpose") or "") == purpose and str(r.get("status") or "") in live:
                return ("tpn_one_live_temporary" if purpose == PURPOSE_TEMPORARY
                        else "tpn_one_current_permanent")

    if status in OWNED_E164_STATUSES and e164:
        for r in others:
            if str(r.get("e164") or "") == e164 and str(r.get("status") or "") in OWNED_E164_STATUSES:
                return "tpn_owned_e164_key"

    return ""


def is_released(row: dict) -> bool:
    """Has this row been given back to the provider?

    Distinct from `not is_routable(row)`: a 'provisioning' row is not routable
    but is still very much ours and still occupies the uniqueness indexes.
    """
    return str(row.get("status") or "") == STATUS_RELEASED


def is_terminal(row: dict) -> bool:
    """Is this row history — neither routable nor a uniqueness conflict?"""
    return str(row.get("status") or "") in TERMINAL_STATUSES
