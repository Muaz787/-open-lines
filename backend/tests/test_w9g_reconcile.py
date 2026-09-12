"""W9G — reconciliation, because the callback is incomplete.

Twilio documents that the status callback fires on every Bundle status change EXCEPT
pending-review -> in-review. So a bundle can sit in review with our record still
saying pending-review and no delivery ever arriving. Callbacks are the fast path;
this is the recovery path.
"""
import pytest

from services import regulatory_reconcile as rec
from services import regulatory_state as st

TENANT = "11111111-1111-1111-1111-111111111111"
SUB = "ACsub00000000000000000000000000001"
WRONG_SUB = "ACwrong0000000000000000000000001"
BUNDLE = "BU00000000000000000000000000000001"


class _Obj:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class FakeTwilio:
    def __init__(self, status="in-review", error=None):
        self.status, self.error = status, error
        self.fetches = 0
        self.numbers = self
        self.v2 = self
        self.regulatory_compliance = self

    def bundles(self, sid):
        outer = self
        class _Ctx:
            def fetch(self):
                outer.fetches += 1
                if outer.error:
                    raise outer.error
                return _Obj(sid=sid, status=outer.status)
        return _Ctx()


def profile(**over):
    base = {"id": "p1", "tenant_id": TENANT, "bundle_sid": BUNDLE,
            "provider_account_sid": SUB, "state": st.PENDING_REVIEW,
            "bundle_status": "pending-review"}
    base.update(over)
    return base


@pytest.fixture
def world(monkeypatch):
    state = {"twilio": FakeTwilio(), "profiles": [profile()],
             "tenants": [{"id": TENANT, "twilio_subaccount_sid": SUB,
                          "twilio_auth_token": "tok"}], "writes": []}

    class FakeQB:
        def __init__(self, table): self.table, self.filters = table, {}
        def select(self, *a, **k): return self
        def eq(self, c, v): self.filters[c] = v; return self
        def limit(self, *a, **k): return self
        def execute(self):
            rows = state["tenants"] if self.table == "tenants" else []
            for c, v in self.filters.items():
                rows = [r for r in rows if str(r.get(c)) == str(v)]
            class R: data = rows
            return R()

    monkeypatch.setattr(rec, "get_client", lambda: type("C", (), {"table": lambda s, n: FakeQB(n)})())
    monkeypatch.setattr(rec.telephony, "_sub_client", lambda s, t: state["twilio"])

    async def list_nonterminal(states, limit=200):
        return [p for p in state["profiles"] if p["state"] in states]
    async def update_profile(pid, patch):
        state["writes"].append((pid, dict(patch)))
        for p in state["profiles"]:
            if p["id"] == pid:
                p.update(patch); return p
        return None
    async def transition_profile(pid, *, expected_state, new_state, patch=None):
        for p in state["profiles"]:
            if p["id"] == pid and p["state"] == expected_state:
                p.update(patch or {}); p["state"] = new_state
                return True
        return False
    monkeypatch.setattr(rec.db_reg, "list_nonterminal_profiles", list_nonterminal)
    monkeypatch.setattr(rec.db_reg, "update_profile", update_profile)
    monkeypatch.setattr(rec.db_reg, "transition_profile", transition_profile)
    monkeypatch.setattr(rec.cb.db_reg, "update_profile", update_profile)
    monkeypatch.setattr(rec.cb.db_reg, "transition_profile", transition_profile)
    return state


# ── the callback-missed case ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_pending_profile_is_fetched_and_the_missed_in_review_is_discovered(world):
    """The exact gap Twilio documents: no callback for pending-review -> in-review."""
    world["twilio"].status = "in-review"
    r = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert world["twilio"].fetches == 1
    assert r["provider_status"] == "in-review"
    # in-review maps onto our pending_review, so the state is already correct and the
    # value is what gets refreshed.
    assert world["profiles"][0]["bundle_status"] == "in-review"


@pytest.mark.asyncio
async def test_an_approval_missed_by_the_callback_is_applied(world):
    world["twilio"].status = "twilio-approved"
    r = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert r["outcome"] == rec.ADVANCED
    assert world["profiles"][0]["state"] == st.APPROVED


@pytest.mark.asyncio
async def test_a_dry_run_changes_nothing_but_reports_what_would_change(world):
    world["twilio"].status = "twilio-approved"
    r = await rec.reconcile_profile(world["profiles"][0], dry_run=True)
    assert r["would_change"] is True and r["outcome"] == rec.ADVANCED
    assert world["profiles"][0]["state"] == st.PENDING_REVIEW
    assert world["writes"] == []


# ── terminal profiles are left alone ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("state", [st.APPROVED, st.REJECTED, st.ACTIVE])
async def test_a_terminal_profile_is_never_polled(world, state):
    world["profiles"][0]["state"] = state
    r = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert r["outcome"] == rec.SKIPPED_TERMINAL
    assert world["twilio"].fetches == 0


@pytest.mark.asyncio
async def test_the_sweep_only_selects_nonterminal_profiles(world):
    world["profiles"] = [profile(id="a", state=st.PENDING_REVIEW),
                         profile(id="b", state=st.APPROVED),
                         profile(id="c", state=st.SUBMITTING)]
    summary = await rec.reconcile_all(dry_run=True)
    assert summary["inspected"] == 2
    assert {r["profile_id"] for r in summary["results"]} == {"a", "c"}


# ── ownership ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_profile_whose_account_is_not_the_tenants_subaccount_is_refused(world):
    world["profiles"][0]["provider_account_sid"] = WRONG_SUB
    r = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert r["outcome"] == rec.OWNERSHIP_CONFLICT
    assert world["twilio"].fetches == 0
    assert world["profiles"][0]["state"] == st.PENDING_REVIEW


@pytest.mark.asyncio
async def test_a_missing_tenant_is_refused(world):
    world["tenants"].clear()
    r = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert r["outcome"] == rec.OWNERSHIP_CONFLICT


@pytest.mark.asyncio
async def test_missing_subaccount_credentials_are_refused(world):
    world["tenants"][0]["twilio_auth_token"] = ""
    r = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert r["outcome"] == rec.MISSING_CREDENTIALS


@pytest.mark.asyncio
async def test_a_profile_with_no_bundle_is_skipped(world):
    world["profiles"][0]["bundle_sid"] = None
    r = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert r["outcome"] == rec.MISSING_BUNDLE


# ── provider outage ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_provider_outage_is_retryable_and_changes_nothing(world):
    class Boom(Exception):
        status = 503
        code = 20500
    world["twilio"].error = Boom("down")
    r = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert r["outcome"] == rec.PROVIDER_UNAVAILABLE
    assert "http=503" in r["detail"] and "down" not in r["detail"]
    assert world["profiles"][0]["state"] == st.PENDING_REVIEW


# ── idempotence ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconciliation_is_idempotent(world):
    world["twilio"].status = "twilio-approved"
    first = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert first["outcome"] == rec.ADVANCED
    second = await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert second["outcome"] == rec.SKIPPED_TERMINAL
    assert world["profiles"][0]["state"] == st.APPROVED


@pytest.mark.asyncio
async def test_provisionally_approved_does_not_become_approved_via_reconciliation(world):
    world["twilio"].status = "provisionally-approved"
    await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    p = world["profiles"][0]
    assert p["state"] == st.PENDING_REVIEW and p["state"] != st.APPROVED
    assert p["bundle_status"] == "provisionally-approved"


@pytest.mark.asyncio
async def test_an_unknown_provider_status_does_not_transition(world):
    world["twilio"].status = "twilio-brand-new"
    await rec.reconcile_profile(world["profiles"][0], dry_run=False)
    assert world["profiles"][0]["state"] == st.PENDING_REVIEW
    assert world["profiles"][0]["bundle_status"] == "twilio-brand-new"
