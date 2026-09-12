"""W9I-B.1 — the canonical phone release lifecycle.

THE DEFECT THIS PINS
W9I-B made phone_registry the one writer that records a provisioned number, but
shipped no way to un-record one. release_tenant_number released the number at
Twilio, cleared the legacy scalar, and left the canonical row 'active'. Measured
live on 2026-09-12: the number 404'd at Twilio, the scalar was NULL, and
find_routable_by_e164 still resolved the row.

The expensive consequence was on the other side. reprovision_tenant_number
guarded on the scalar, so a tenant in that state passed the guard, BOUGHT a real
number, and was then refused by register_permanent -- because the stale row was
still a live permanent. The replacement was handed straight back and the customer
stayed without a line, one non-refundable monthly rental poorer per attempt
(USD 1.15 for a Canadian local number, measured during the W9I-B regression).

Both halves are pinned here: the transition must happen on proof, and must not
happen without it.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import phone_lifecycle as lifecycle, phone_registry, provisioning
from tests.canonical_phone_store import Store, canonical, row as canon_row
import db.supabase as _supabase_mod   # noqa: F401  (registers the dotted paths)
import db.phone_numbers as _phones_mod  # noqa: F401

NUM = "+14165550100"
SID = "PN_num1"
ACCT = "AC_sub"


def _tenant(**over):
    return {
        "id": "t1", "business_name": "Acme", "country": "CA",
        "twilio_phone_number": NUM,
        "twilio_subaccount_sid": ACCT, "twilio_auth_token": "tok",
        "vapi_phone_number_id": "vapi_pn_1", "vapi_assistant_id": "asst_1",
        "subscription_status": "none",
        **over,
    }


# ── 1. the transition itself ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_confirmed_release_moves_the_canonical_row_to_released():
    with canonical([canon_row()], {"t1": NUM}) as store, \
         patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=True)), \
         patch("services.telephony.release_number", new=AsyncMock(return_value=True)):
        res = await provisioning.release_tenant_number(_tenant())

    assert res["released"] is True and res["reason"] == ""
    assert res["steps"]["canonical_released"] is True
    assert store.rows[0]["status"] == lifecycle.STATUS_RELEASED
    assert store.rows[0]["released_at"]


@pytest.mark.asyncio
async def test_the_scalar_is_cleared_only_when_it_still_names_that_number():
    """A release worker holding a stale view must not unlink a live replacement."""
    # The tenant has already been reprovisioned onto a different number.
    with canonical([canon_row()], {"t1": "+14165559999"}) as store, \
         patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=True)), \
         patch("services.telephony.release_number", new=AsyncMock(return_value=True)):
        res = await provisioning.release_tenant_number(_tenant())

    assert res["released"] is True
    assert store.rows[0]["status"] == lifecycle.STATUS_RELEASED   # old row retired
    assert store.scalars["t1"] == "+14165559999"                  # replacement untouched
    assert res["steps"]["tenant_cleared"] is False


@pytest.mark.asyncio
async def test_a_released_row_is_not_routable():
    released = canon_row(status=lifecycle.STATUS_RELEASED)
    assert lifecycle.is_routable(released) is False
    assert lifecycle.STATUS_RELEASED not in lifecycle.ROUTABLE_STATUSES
    assert lifecycle.STATUS_FAILED not in lifecycle.ROUTABLE_STATUSES


@pytest.mark.asyncio
async def test_a_released_predecessor_does_not_block_a_new_permanent():
    """The whole point. A released row is history, not a live permanent."""
    history = canon_row(status=lifecycle.STATUS_RELEASED)
    candidate = {"purpose": lifecycle.PURPOSE_PERMANENT,
                 "status": lifecycle.STATUS_PROVISIONING, "e164": "+14165559999"}
    assert lifecycle.live_conflict([history], candidate) == ""
    # ... whereas the pre-fix state (row left 'active') does block it, which is
    # exactly the failure that burned a number rental per retry.
    stale = canon_row(status=lifecycle.STATUS_ACTIVE)
    assert lifecycle.live_conflict([stale], candidate) == "tpn_one_current_permanent"


@pytest.mark.asyncio
async def test_reprovision_succeeds_after_a_release():
    store = Store([canon_row(status=lifecycle.STATUS_RELEASED)], {"t1": None})
    with patch("db.phone_numbers.get_current_permanent", new=store.get_current_permanent), \
         patch("services.telephony.find_available_number", new=AsyncMock(return_value="+14165559999")), \
         patch("services.telephony.purchase_number_with_sid",
               new=AsyncMock(return_value=("+14165559999", "PN_num2"))), \
         patch("services.vapi.import_twilio_number", new=AsyncMock(return_value="vapi_pn_2")), \
         patch("services.phone_registry.register_permanent",
               new=AsyncMock(return_value={"status": "ok", "row": {"id": "row2"}, "created": True})), \
         patch("services.phone_registry.mark_active",
               new=AsyncMock(return_value={"status": "ok", "row": {}})), \
         patch("db.supabase.update_tenant", new=AsyncMock()):
        res = await provisioning.reprovision_tenant_number(_tenant(twilio_phone_number=None))

    assert res["provisioned"] is True and res["number"] == "+14165559999"


# ── 2. idempotency and concurrency ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_release_is_idempotent():
    store = Store([canon_row()], {"t1": NUM})
    with patch("db.phone_numbers.get_by_id", new=store.get_by_id), \
         patch("db.phone_numbers.release_number_cas", new=store.release_number_cas), \
         patch("db.supabase.clear_tenant_number_fenced", new=store.clear_tenant_number_fenced):
        first = await phone_registry.mark_released(
            tenant_id="t1", number_row_id="row1", expected_e164=NUM,
            expected_provider_sid=SID, expected_provider_account_sid=ACCT)
        stamped = store.rows[0]["released_at"]
        second = await phone_registry.mark_released(
            tenant_id="t1", number_row_id="row1", expected_e164=NUM,
            expected_provider_sid=SID, expected_provider_account_sid=ACCT)

    assert first["released"] is True and first["idempotent"] is False
    assert second["released"] is True and second["idempotent"] is True
    # The second call must not restamp history.
    assert store.rows[0]["released_at"] == stamped


@pytest.mark.asyncio
async def test_concurrent_release_transitions_the_row_once():
    import asyncio
    store = Store([canon_row()], {"t1": NUM})
    with patch("db.phone_numbers.get_by_id", new=store.get_by_id), \
         patch("db.phone_numbers.release_number_cas", new=store.release_number_cas), \
         patch("db.supabase.clear_tenant_number_fenced", new=store.clear_tenant_number_fenced):
        results = await asyncio.gather(*[
            phone_registry.mark_released(
                tenant_id="t1", number_row_id="row1", expected_e164=NUM,
                expected_provider_sid=SID, expected_provider_account_sid=ACCT)
            for _ in range(4)])

    assert all(r["released"] for r in results)
    # Exactly one did the work; the rest recognised an already-released row.
    assert sum(1 for r in results if not r["idempotent"]) == 1
    assert sum(1 for r in results if r["idempotent"]) == 3
    assert store.rows[0]["status"] == lifecycle.STATUS_RELEASED
    # One scalar clear, not four.
    assert len(store.cleared) == 1


@pytest.mark.asyncio
async def test_a_stale_worker_cannot_release_the_replacement():
    """The failure the fence exists for: a worker that began releasing number A,
    stalled, and woke up after the row was reprovisioned onto number B."""
    # Same row id, different number and SID — the replacement.
    store = Store([canon_row(e164="+14165559999", provider_sid="PN_num2")],
                  {"t1": "+14165559999"})
    with patch("db.phone_numbers.get_by_id", new=store.get_by_id), \
         patch("db.phone_numbers.release_number_cas", new=store.release_number_cas), \
         patch("db.supabase.clear_tenant_number_fenced", new=store.clear_tenant_number_fenced):
        res = await phone_registry.mark_released(
            tenant_id="t1", number_row_id="row1", expected_e164=NUM,
            expected_provider_sid=SID, expected_provider_account_sid=ACCT)

    assert res["status"] == phone_registry.STALE
    assert res["released"] is False and res["detail"] == "identity_mismatch"
    assert store.rows[0]["status"] == lifecycle.STATUS_ACTIVE   # B still rings
    assert store.scalars["t1"] == "+14165559999"                # and is still linked


@pytest.mark.asyncio
async def test_a_missing_row_fails_closed():
    store = Store([], {"t1": NUM})
    with patch("db.phone_numbers.get_by_id", new=store.get_by_id), \
         patch("db.phone_numbers.release_number_cas", new=store.release_number_cas), \
         patch("db.supabase.clear_tenant_number_fenced", new=store.clear_tenant_number_fenced):
        res = await phone_registry.mark_released(
            tenant_id="t1", number_row_id="row1", expected_e164=NUM,
            expected_provider_sid=SID, expected_provider_account_sid=ACCT)
    assert res["status"] == phone_registry.STALE and res["detail"] == "row_missing"
    assert store.scalars["t1"] == NUM     # nothing cleared on an unproven release


# ── 3. every unknown provider outcome leaves the row live ───────────────────

@pytest.mark.parametrize("failure", [
    pytest.param(TimeoutError("read timed out"), id="timeout"),
    pytest.param(RuntimeError("HTTP 401 Unauthorized"), id="401"),
    pytest.param(RuntimeError("HTTP 403 Forbidden"), id="403"),
    pytest.param(RuntimeError("HTTP 429 Too Many Requests"), id="429"),
    pytest.param(RuntimeError("HTTP 500 Internal Server Error"), id="500"),
    pytest.param(RuntimeError("HTTP 503 Service Unavailable"), id="503"),
    pytest.param(ValueError("Expecting value: line 1 column 1"), id="malformed_body"),
    pytest.param(ConnectionResetError("connection reset by peer"), id="transport"),
])
@pytest.mark.asyncio
async def test_an_unknown_provider_outcome_never_marks_the_row_released(failure):
    """Only a confirmed delete is proof. Everything else means the number may
    still be ours and still billing, and a row marked released on that basis is
    invisible to every reconciliation path we have."""
    with canonical([canon_row()], {"t1": NUM}) as store, \
         patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=True)), \
         patch("services.telephony.release_number", new=AsyncMock(side_effect=failure)):
        res = await provisioning.release_tenant_number(_tenant())

    assert res["released"] is False and res["reason"] == "twilio_release_failed"
    assert store.rows[0]["status"] == lifecycle.STATUS_ACTIVE
    assert store.rows[0]["released_at"] is None
    assert store.scalars["t1"] == NUM


@pytest.mark.asyncio
async def test_a_number_absent_from_the_subaccount_is_not_proof_of_release():
    """An empty list proves the number is not on THIS account — not that we do
    not own it. Wrong credentials look identical. Proving org-wide absence is
    stale_phone_cleanup's job, and it scans every account to do it."""
    with canonical([canon_row()], {"t1": NUM}) as store, \
         patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=True)), \
         patch("services.telephony.release_number", new=AsyncMock(return_value=False)):
        res = await provisioning.release_tenant_number(_tenant())

    assert res["reason"] == "twilio_number_not_found"
    assert store.rows[0]["status"] == lifecycle.STATUS_ACTIVE


@pytest.mark.asyncio
async def test_a_failed_vapi_delete_stops_before_the_number_is_given_away():
    with canonical([canon_row()], {"t1": NUM}) as store, \
         patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=False)), \
         patch("services.telephony.release_number", new=AsyncMock()) as twilio:
        res = await provisioning.release_tenant_number(_tenant())

    assert res["reason"] == "vapi_delete_failed"
    twilio.assert_not_called()
    assert store.rows[0]["status"] == lifecycle.STATUS_ACTIVE


@pytest.mark.asyncio
async def test_a_db_failure_after_the_provider_release_is_reported_not_swallowed():
    """The number IS gone. Saying otherwise would send a reconciliation sweep
    looking for a number Twilio no longer has — but the books are now wrong, and
    that has to be loud."""
    async def _boom(**kw):
        raise RuntimeError("postgrest unavailable")

    with canonical([canon_row()], {"t1": NUM}), \
         patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=True)), \
         patch("services.telephony.release_number", new=AsyncMock(return_value=True)), \
         patch("services.phone_registry.mark_released", new=_boom):
        res = await provisioning.release_tenant_number(_tenant())

    assert res["released"] is True                      # the provider truth
    assert res["reason"] == "canonical_update_failed"   # and the books' truth
    assert res["steps"]["canonical_released"] is False


# ── 4. spend safety ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_live_canonical_permanent_is_refused_before_any_purchase():
    """THE measured regression: the guard read the scalar, so this tenant used to
    reach Twilio, buy a number and be refused afterwards."""
    store = Store([canon_row()], {"t1": None})
    with patch("db.phone_numbers.get_current_permanent", new=store.get_current_permanent), \
         patch("services.telephony.find_available_number", new=AsyncMock()) as find, \
         patch("services.telephony.purchase_number_with_sid", new=AsyncMock()) as buy:
        res = await provisioning.reprovision_tenant_number(_tenant(twilio_phone_number=None))

    assert res["provisioned"] is False
    assert res["reason"] == "canonical_permanent_still_live"
    find.assert_not_called()
    buy.assert_not_called()       # no money spent


@pytest.mark.asyncio
async def test_an_unreadable_canonical_model_refuses_rather_than_spends():
    async def _boom(tenant_id):
        raise RuntimeError("postgrest unavailable")

    with patch("db.phone_numbers.get_current_permanent", new=_boom), \
         patch("services.telephony.purchase_number_with_sid", new=AsyncMock()) as buy:
        res = await provisioning.reprovision_tenant_number(_tenant(twilio_phone_number=None))

    assert res["reason"] == "canonical_preflight_failed"
    buy.assert_not_called()


@pytest.mark.asyncio
async def test_a_tenant_with_no_scalar_but_a_live_row_refuses_to_release():
    """The exact production shape this gate found: scalar NULL, canonical live.
    Reporting 'already done' would leave the row live for ever."""
    with canonical([canon_row()], {"t1": None}):
        res = await provisioning.release_tenant_number(_tenant(twilio_phone_number=""))
    assert res["released"] is False
    assert res["reason"] == "canonical_row_without_scalar"


@pytest.mark.asyncio
async def test_a_number_canonically_owned_by_another_tenant_is_refused():
    with canonical([canon_row(tenant_id="t2")], {"t1": NUM}) as store, \
         patch("services.telephony.release_number", new=AsyncMock()) as twilio:
        res = await provisioning.release_tenant_number(_tenant())
    assert res["reason"] == "canonical_owner_mismatch"
    twilio.assert_not_called()
    assert store.rows[0]["status"] == lifecycle.STATUS_ACTIVE


# ── 5. the vocabulary the indexes depend on ─────────────────────────────────

def test_release_vocabulary_matches_the_index_predicates():
    """These tuples are the application's copy of 027's partial index predicates.
    A release that transitions out of a status the indexes still count would
    leave the row live in the database's eyes and released in ours."""
    assert lifecycle.RELEASABLE_STATUSES == ("provisioning", "active", "retiring")
    assert lifecycle.STATUS_RELEASED not in lifecycle.CURRENT_PERMANENT_STATUSES
    assert lifecycle.STATUS_RELEASED not in lifecycle.LIVE_TEMPORARY_STATUSES
    assert lifecycle.STATUS_RELEASED not in lifecycle.OWNED_E164_STATUSES
    assert lifecycle.STATUS_RELEASED not in lifecycle.ROUTABLE_STATUSES
    assert lifecycle.TERMINAL_STATUSES == ("released", "failed")


# ── 6. routing cannot resurrect a released number ───────────────────────────

class _RoutingClient:
    """Answers the two routing queries out of an explicit row list, applying the
    same status filters PostgREST would. Nothing else."""

    def __init__(self, rows, tenants):
        self.rows, self.tenants = rows, tenants
        self._tbl = None
        self._filters = {}
        self._in = None

    def table(self, name):
        self._tbl, self._filters, self._in = name, {}, None
        return self

    def select(self, *a, **k): return self
    def limit(self, n): return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._in = (col, list(vals))
        return self

    def execute(self):
        class R: pass
        r = R()
        if self._tbl == "tenant_phone_numbers":
            out = [x for x in self.rows
                   if all(x.get(c) == v for c, v in self._filters.items())]
            if self._in:
                col, vals = self._in
                out = [x for x in out if x.get(col) in vals]
        else:
            out = [t for t in self.tenants
                   if all(t.get(c) == v for c, v in self._filters.items())]
        r.data = out
        return r


@pytest.mark.parametrize("status", ["released", "failed"])
@pytest.mark.asyncio
async def test_a_non_live_row_is_not_routable(status):
    from db import phone_numbers as dbp, supabase as dbs
    client = _RoutingClient([canon_row(status=status)], [{"id": "t1"}])
    with patch("db.phone_numbers.get_client", return_value=client):
        assert await dbp.find_routable_by_e164(NUM) is None
    with patch("db.phone_numbers.get_client", return_value=client), \
         patch("db.supabase.get_client", return_value=client):
        # No canonical row AND no scalar naming it: nothing resolves.
        assert await dbs.get_tenant_by_phone(NUM) is None


@pytest.mark.asyncio
async def test_ownership_excludes_released_so_the_number_is_repurchasable():
    from db import phone_numbers as dbp
    client = _RoutingClient([canon_row(status="released")], [])
    with patch("db.phone_numbers.get_client", return_value=client):
        assert await dbp.find_owned_by_e164(NUM) is None


@pytest.mark.asyncio
async def test_a_stranded_scalar_can_still_resurrect_a_released_number():
    """Backward compatibility has a cost, and this names it. get_tenant_by_phone
    falls back to the legacy scalar for tenants that predate the canonical model,
    so a released row next to a scalar that still names the number resolves via
    the scalar. mark_released clears them together and fences the clear, which is
    what keeps that pair from occurring -- the fallback itself stays, because
    removing it would strand every pre-027 tenant."""
    from db import supabase as dbs
    client = _RoutingClient([canon_row(status="released")],
                            [{"id": "t1", "twilio_phone_number": NUM}])
    with patch("db.phone_numbers.get_client", return_value=client), \
         patch("db.supabase.get_client", return_value=client):
        got = await dbs.get_tenant_by_phone(NUM)
    assert got is not None and got["id"] == "t1"


# ── 7. a rolled-back signup leaves no live row behind ───────────────────────

@pytest.mark.asyncio
async def test_provisioning_rollback_retires_a_canonical_row_it_created():
    """Step 13 can insert the row and a later step can still fail. Left behind as
    'provisioning' it is a live permanent by tpn_one_current_permanent and owns
    the E.164 by tpn_owned_e164_key -- so this tenant could never be provisioned
    again. The same divergence as the release path, reached from the other side."""
    store = Store([canon_row(status=lifecycle.STATUS_PROVISIONING)], {"t1": None})
    with patch("db.phone_numbers.find_owned_by_e164", new=store.find_owned_by_e164), \
         patch("db.phone_numbers.get_by_id", new=store.get_by_id), \
         patch("db.phone_numbers.release_number_cas", new=store.release_number_cas), \
         patch("db.supabase.clear_tenant_number_fenced", new=store.clear_tenant_number_fenced):
        await provisioning._rollback_canonical_row("t1", NUM, ACCT, SID)
    assert store.rows[0]["status"] == lifecycle.STATUS_RELEASED


@pytest.mark.asyncio
async def test_the_rollback_never_touches_another_tenants_row():
    store = Store([canon_row(tenant_id="t2")], {})
    with patch("db.phone_numbers.find_owned_by_e164", new=store.find_owned_by_e164), \
         patch("db.phone_numbers.get_by_id", new=store.get_by_id), \
         patch("db.phone_numbers.release_number_cas", new=store.release_number_cas), \
         patch("db.supabase.clear_tenant_number_fenced", new=store.clear_tenant_number_fenced):
        await provisioning._rollback_canonical_row("t1", NUM, ACCT, SID)
    assert store.rows[0]["status"] == lifecycle.STATUS_ACTIVE


@pytest.mark.asyncio
async def test_the_rollback_never_raises_over_the_original_failure():
    async def _boom(e164):
        raise RuntimeError("postgrest unavailable")
    with patch("db.phone_numbers.find_owned_by_e164", new=_boom):
        await provisioning._rollback_canonical_row("t1", NUM, ACCT, SID)   # must not raise


# ── 8. the real queries, not a fake standing in for them ────────────────────
#
# Sections 1–7 patch the repository layer so the SERVICE logic can be tested in
# isolation. That leaves the repository layer itself untested: a fence deleted
# from db/phone_numbers.py breaks nothing above, because those tests never call
# it. Mutation testing found exactly that -- removing the identity fence left
# every service test green.
#
# So these drive the REAL functions against a client that records the query it
# was asked to build. They assert the WHERE clause, which is the entire security
# property: an update fenced on the row id alone retires whatever now occupies
# that id, including a live replacement.

class _RecordingClient:
    """Records the filters a query was built from and returns `result`."""

    def __init__(self, result=None):
        self.result = result if result is not None else []
        self.calls = []
        self._cur = None

    def table(self, name):
        self._cur = {"table": name, "eq": {}, "in": {}, "patch": None}
        self.calls.append(self._cur)
        return self

    def update(self, patch):
        self._cur["patch"] = patch
        return self

    def select(self, *a, **k): return self
    def limit(self, n): return self

    def eq(self, col, val):
        self._cur["eq"][col] = val
        return self

    def in_(self, col, vals):
        self._cur["in"][col] = list(vals)
        return self

    def execute(self):
        class R: pass
        r = R(); r.data = self.result
        return r


@pytest.mark.asyncio
async def test_the_release_update_is_fenced_on_the_full_provider_identity():
    """Every one of these five columns is load-bearing. Fenced on the row id
    alone, a stalled worker retires whichever number now occupies that row."""
    from db import phone_numbers as dbp
    client = _RecordingClient([canon_row(status="released")])
    with patch("db.phone_numbers.get_client", return_value=client):
        await dbp.release_number_cas(
            number_id="row1", tenant_id="t1", e164=NUM,
            provider_sid=SID, provider_account_sid=ACCT)

    q = client.calls[0]
    assert q["table"] == "tenant_phone_numbers"
    assert q["eq"] == {"id": "row1", "tenant_id": "t1", "e164": NUM,
                       "provider_account_sid": ACCT, "provider_sid": SID}
    # Only a releasable row may transition — an already-released one must match
    # zero rows rather than being restamped with a new released_at.
    assert q["in"] == {"status": list(lifecycle.RELEASABLE_STATUSES)}
    assert lifecycle.STATUS_RELEASED not in q["in"]["status"]
    assert q["patch"]["status"] == lifecycle.STATUS_RELEASED
    assert q["patch"]["released_at"]
    # The provider SID is history, not garbage: Twilio never reissues one, so
    # keeping it makes tpn_provider_object_key a truthful permanent record.
    assert "provider_sid" not in q["patch"]


@pytest.mark.asyncio
async def test_the_scalar_clear_is_fenced_on_the_number_being_released():
    from db import supabase as dbs
    client = _RecordingClient([{"id": "t1"}])
    with patch("db.supabase.get_client", return_value=client):
        await dbs.clear_tenant_number_fenced("t1", NUM, "2026-09-12T00:00:00+00:00")

    q = client.calls[0]
    assert q["table"] == "tenants"
    # WITHOUT the E.164 predicate this write unlinks whatever number the tenant
    # now has, which is how a stale release takes a live line down.
    assert q["eq"] == {"id": "t1", "twilio_phone_number": NUM}
    assert q["patch"]["twilio_phone_number"] is None
    assert q["patch"]["vapi_phone_number_id"] is None
    assert q["patch"]["number_released_at"] == "2026-09-12T00:00:00+00:00"


@pytest.mark.asyncio
async def test_the_ownership_and_routing_lookups_filter_on_status():
    from db import phone_numbers as dbp
    client = _RecordingClient([])
    with patch("db.phone_numbers.get_client", return_value=client):
        await dbp.find_routable_by_e164(NUM)
        await dbp.find_owned_by_e164(NUM)
    assert client.calls[0]["in"] == {"status": list(lifecycle.ROUTABLE_STATUSES)}
    assert client.calls[1]["in"] == {"status": list(lifecycle.OWNED_E164_STATUSES)}


@pytest.mark.asyncio
async def test_a_signup_that_fails_after_step_13_releases_its_canonical_row():
    """Drives the REAL rollback wiring, not the helper in isolation: a mutation
    that stops calling it must fail here."""
    from fastapi import HTTPException
    seen = {}

    async def _after_twilio(*a, **k):
        raise HTTPException(status_code=500, detail="Step 14 failed")

    async def _rollback(tenant_id, e164, sub, sid):
        seen.update({"tenant_id": tenant_id, "e164": e164, "sub": sub, "sid": sid})

    with patch("services.provisioning._provision_after_twilio", new=_after_twilio), \
         patch("services.provisioning._rollback_canonical_row", new=_rollback), \
         patch("services.telephony.release_number", new=AsyncMock(return_value=True)), \
         patch("services.provisioning._claim_or_resume_tenant",
               new=AsyncMock(return_value=({"id": "t1", "onboarding_state": "provisioning"}, False))), \
         patch("services.telephony.create_subaccount",
               new=AsyncMock(return_value={"sid": ACCT, "auth_token": "tok"})), \
         patch("services.telephony.find_available_number", new=AsyncMock(return_value=NUM)), \
         patch("services.telephony.purchase_number_with_sid",
               new=AsyncMock(return_value=(NUM, SID))), \
         patch("services.vapi.create_suborg", new=AsyncMock(return_value={})):
        with pytest.raises(HTTPException):
            await provisioning.provision_tenant(
                {"business_name": "Acme", "industry": "realtor", "country": "CA",
                 "owner_name": "O", "agent_name": "A", "website_url": ""})

    assert seen == {"tenant_id": "t1", "e164": NUM, "sub": ACCT, "sid": SID}
