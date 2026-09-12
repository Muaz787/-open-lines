"""W9D — the phone-number lifecycle invariants, and the promotion sequence.

These drive services/phone_lifecycle.live_conflict(), which is the application-side
mirror of the three partial unique indexes in migration 027. The DDL is asserted to
declare exactly these status sets by tests/test_migration_027_contract.py, so a
change on either side that is not made on the other fails one of the two files.

WHAT THIS DOES NOT CLAIM. There is no test database here, so Postgres never
actually rejects a row in this suite. These tests prove the rules the code enforces
BEFORE writing; the indexes remain the enforcer of last resort.
"""
import pytest

from services import phone_lifecycle as lifecycle

L = lifecycle
TENANT = "t-1"
PERM = "+35316170000"
TEMP = "+447400000001"
OTHER = "+35321400000"


def row(e164, purpose, status, rid=None):
    return {"id": rid, "tenant_id": TENANT, "e164": e164,
            "purpose": purpose, "status": status}


# ── permanent: one current, a retiring predecessor allowed ─────────────────

def test_second_active_permanent_is_refused():
    existing = [row(PERM, L.PURPOSE_PERMANENT, L.STATUS_ACTIVE, "a")]
    clash = L.live_conflict(existing, row(OTHER, L.PURPOSE_PERMANENT, L.STATUS_ACTIVE))
    assert clash == "tpn_one_current_permanent"


def test_second_provisioning_permanent_is_refused():
    """This is the anti-double-purchase guarantee: a retried promotion cannot
    insert a second row, so it cannot buy or import a second number."""
    existing = [row(PERM, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING, "a")]
    clash = L.live_conflict(existing, row(OTHER, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING))
    assert clash == "tpn_one_current_permanent"


def test_provisioning_permanent_alongside_an_active_one_is_refused():
    existing = [row(PERM, L.PURPOSE_PERMANENT, L.STATUS_ACTIVE, "a")]
    clash = L.live_conflict(existing, row(OTHER, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING))
    assert clash == "tpn_one_current_permanent"


def test_retiring_permanent_plus_new_active_permanent_is_ALLOWED():
    """Required for safe replacement: the outgoing number must keep ringing."""
    existing = [row(PERM, L.PURPOSE_PERMANENT, L.STATUS_RETIRING, "old")]
    assert L.live_conflict(existing, row(OTHER, L.PURPOSE_PERMANENT, L.STATUS_ACTIVE)) == ""


def test_released_permanent_does_not_block_a_new_one():
    existing = [row(PERM, L.PURPOSE_PERMANENT, L.STATUS_RELEASED, "old")]
    assert L.live_conflict(existing, row(OTHER, L.PURPOSE_PERMANENT, L.STATUS_ACTIVE)) == ""


def test_failed_permanent_does_not_block_a_retry():
    existing = [row(PERM, L.PURPOSE_PERMANENT, L.STATUS_FAILED, "old")]
    assert L.live_conflict(existing, row(PERM, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING)) == ""


# ── temporary: stricter, retiring still blocks ─────────────────────────────

def test_second_active_temporary_is_refused():
    existing = [row(TEMP, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE, "a")]
    clash = L.live_conflict(existing, row(OTHER, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE))
    assert clash == "tpn_one_live_temporary"


def test_a_RETIRING_temporary_still_blocks_a_second_temporary():
    """THE POLICY DIFFERENCE FROM PERMANENT, DELIBERATE. A test number has no
    replacement story -- it exists until the permanent arrives, then retires and is
    released. Allowing a second one alongside a retiring one lets a tenant
    accumulate rented numbers for free, which is a billing leak dressed up as a
    lifecycle."""
    existing = [row(TEMP, L.PURPOSE_TEMPORARY, L.STATUS_RETIRING, "old")]
    clash = L.live_conflict(existing, row(OTHER, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE))
    assert clash == "tpn_one_live_temporary"


def test_a_released_temporary_permits_a_new_one():
    existing = [row(TEMP, L.PURPOSE_TEMPORARY, L.STATUS_RELEASED, "old")]
    assert L.live_conflict(existing, row(OTHER, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE)) == ""


def test_the_two_policies_are_genuinely_different():
    """Guards the regression where someone 'tidies' the two indexes into one."""
    assert L.STATUS_RETIRING in L.LIVE_TEMPORARY_STATUSES
    assert L.STATUS_RETIRING not in L.CURRENT_PERMANENT_STATUSES


# ── temporary and permanent coexist ────────────────────────────────────────

def test_temporary_active_and_permanent_provisioning_coexist():
    existing = [row(TEMP, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE, "tmp")]
    assert L.live_conflict(existing, row(PERM, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING)) == ""


def test_temporary_active_and_permanent_active_coexist():
    existing = [row(TEMP, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE, "tmp")]
    assert L.live_conflict(existing, row(PERM, L.PURPOSE_PERMANENT, L.STATUS_ACTIVE)) == ""


# ── E.164 identity ─────────────────────────────────────────────────────────

def test_the_same_owned_number_twice_is_refused():
    existing = [row(PERM, L.PURPOSE_PERMANENT, L.STATUS_ACTIVE, "a")]
    clash = L.live_conflict(existing, row(PERM, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE))
    assert clash == "tpn_owned_e164_key"


def test_a_released_number_can_be_taken_again():
    """A released number goes back to Twilio's pool; it must not be blocked for
    ever by our own history."""
    existing = [row(PERM, L.PURPOSE_PERMANENT, L.STATUS_RELEASED, "old")]
    assert L.live_conflict(existing, row(PERM, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING)) == ""


def test_a_failed_row_does_not_squat_an_e164_we_never_owned():
    existing = [row(PERM, L.PURPOSE_PERMANENT, L.STATUS_FAILED, "old")]
    assert L.live_conflict(existing, row(PERM, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING)) == ""


def test_a_row_does_not_conflict_with_itself():
    """An in-place status change must not be read as a second row."""
    r = row(PERM, L.PURPOSE_PERMANENT, L.STATUS_ACTIVE, "same")
    assert L.live_conflict([r], dict(r, status=L.STATUS_RETIRING)) == ""


# ── routability ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,expected", [
    (L.STATUS_PROVISIONING, False),
    (L.STATUS_ACTIVE, True),
    (L.STATUS_RETIRING, True),
    (L.STATUS_RELEASED, False),
    (L.STATUS_FAILED, False),
])
def test_only_active_and_retiring_are_routable(status, expected):
    assert L.is_routable(row(PERM, L.PURPOSE_PERMANENT, status)) is expected


def test_activated_at_can_never_be_sourced_from_tenant_creation():
    assert "tenant_created_at" not in L.ACTIVATED_AT_SOURCES
    assert set(L.ACTIVATED_AT_SOURCES) == {"provider_date_created", "promotion"}


# ── the promotion sequence, step by step ───────────────────────────────────

def test_the_full_promotion_and_grace_sequence_is_permitted():
    """T0 temporary active -> P1 permanent provisioning -> P1 active, T0 retiring ->
    T0 released. At every step the rules must permit the state, and exactly the
    right numbers must route."""
    rows: list[dict] = []

    # T0: the temporary test number the customer is already using.
    t0 = row(TEMP, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE, "T0")
    assert L.live_conflict(rows, t0) == ""
    rows.append(t0)
    assert [r["e164"] for r in rows if L.is_routable(r)] == [TEMP]

    # P1: the permanent number is being bought and configured.
    p1 = row(PERM, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING, "P1")
    assert L.live_conflict(rows, p1) == ""
    rows.append(p1)
    assert [r["e164"] for r in rows if L.is_routable(r)] == [TEMP], \
        "a provisioning number must not receive calls before its webhook exists"

    # A retry of the same promotion must not be able to add a second permanent.
    assert L.live_conflict(rows, row(OTHER, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING)) \
        == "tpn_one_current_permanent"

    # Promotion: P1 goes live, T0 starts its grace period. BOTH must route.
    p1["status"] = L.STATUS_ACTIVE
    t0["status"] = L.STATUS_RETIRING
    assert L.live_conflict(rows, p1) == ""
    assert L.live_conflict(rows, t0) == ""
    assert sorted(r["e164"] for r in rows if L.is_routable(r)) == sorted([TEMP, PERM])

    # While T0 retires, no second temporary may appear.
    assert L.live_conflict(rows, row(OTHER, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE)) \
        == "tpn_one_live_temporary"

    # Grace over: T0 released. Only the permanent number routes.
    t0["status"] = L.STATUS_RELEASED
    assert [r["e164"] for r in rows if L.is_routable(r)] == [PERM]

    # And now a fresh temporary is permitted again.
    assert L.live_conflict(rows, row(OTHER, L.PURPOSE_TEMPORARY, L.STATUS_PROVISIONING)) == ""


def test_the_scalar_mirror_tracks_the_current_permanent_through_promotion():
    """Legacy compatibility: tenants.twilio_phone_number mirrors the current
    permanent row, and the mirror is well defined at every step of the sequence --
    including while two numbers are live, which is exactly when the scalar alone is
    insufficient and the table has to answer."""
    rows = [row(TEMP, L.PURPOSE_TEMPORARY, L.STATUS_ACTIVE, "T0")]

    def mirror(rs):
        current = [r for r in rs if r["purpose"] == L.PURPOSE_PERMANENT
                   and r["status"] in L.CURRENT_PERMANENT_STATUSES]
        assert len(current) <= 1, "the mirror would be ambiguous"
        return current[0]["e164"] if current else None

    assert mirror(rows) is None            # temporary only: nothing to mirror yet
    p1 = row(PERM, L.PURPOSE_PERMANENT, L.STATUS_PROVISIONING, "P1")
    rows.append(p1)
    assert mirror(rows) == PERM
    p1["status"] = L.STATUS_ACTIVE
    rows[0]["status"] = L.STATUS_RETIRING
    assert mirror(rows) == PERM
    assert L.is_routable(rows[0]), "the mirror must not silence the retiring number"
