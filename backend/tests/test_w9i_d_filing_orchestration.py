"""W9I-D — the provider filing lifecycle.

THREE THINGS THIS SUITE DEFENDS

1. GATE 1 AND GATE 2. No provider identity exists without a live authorisation
   covering the exact current facts, and the question is asked AGAIN immediately
   before submission -- because an arbitrary amount of time passes between
   building a Bundle and filing it, and consent can be withdrawn inside it.

2. SUBMISSION IS NOT REPEATABLE. A Bundle the provider already holds must never be
   filed twice. The case that matters is the one where OUR view is unreliable: the
   submit call errored, and we do not know whether the provider took it. The old
   code rolled back and invited a retry; it now asks the provider.

3. A PROVIDER FAILURE IS NOT A REJECTION. 401, 403, 429, 5xx, a malformed body --
   none of them is the regulator saying no, and a customer told they were rejected
   when Twilio was merely unreachable will start editing correct data.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import regulatory_engine as engine
from services import regulatory_filing as filing
from services import regulatory_reconcile as rec
from services import regulatory_state as st
from tests.module_identifiers import identifiers

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
ADDR = "33333333-3333-3333-3333-333333333333"
PROFILE = "44444444-4444-4444-4444-444444444444"
BUNDLE = "BU" + "a" * 32


def _profile(**over):
    return {"id": PROFILE, "tenant_id": TENANT, "iso_country": "IE",
            "number_type": "local", "end_user_type": "business",
            "regulatory_address_id": ADDR, "provider_account_sid": "ACsub",
            "bundle_sid": BUNDLE, "state": st.READY_TO_SUBMIT,
            "bundle_status": "draft", "requirements_fingerprint": "f" * 64,
            "regulation_sid": "RNqa", "end_user_sid": "BU_eu",
            "authorization_id": "auth1", **over}


# ═══ 1. Gate 1 — nothing provider-side without a live authorisation ════════

GATE1_REFUSALS = [
    (engine.AUTHORIZATION_NOT_RECORDED, "no authorisation on file"),
    (engine.AUTHORIZATION_REVOKED, "authorisation withdrawn"),
    (engine.AUTHORIZATION_STALE, "facts edited since consent"),
    (engine.AUTHORIZATION_WRONG_SCOPE, "consent was for another premises"),
]


@pytest.mark.parametrize("status,why", GATE1_REFUSALS)
@pytest.mark.asyncio
async def test_gate_1_blocks_every_provider_identity(status, why):
    """The EndUser is the first thing that exists at Twilio under a customer's
    name. None of these four may produce one."""
    calls = []

    async def check(*a, **k):
        return {"ok": False, "status": status, "detail": why}

    async def spy(name):
        async def inner(*a, **k):
            calls.append(name)
            return {"ok": True, "status": engine.OK}
        return inner

    with patch.object(engine, "check_authorization", new=check), \
         patch.object(engine, "resolve_end_user", new=await spy("end_user")), \
         patch.object(engine, "ensure_supporting_document", new=await spy("document")), \
         patch.object(engine, "ensure_bundle", new=await spy("bundle")):
        out = await _prepare_with_everything_else_ready()

    assert out["status"] == status
    assert calls == [], f"{why} still reached the provider: {calls}"


@pytest.mark.asyncio
async def test_changed_requirements_block_the_filing():
    """A regulation whose required fields moved must not be filed against the
    answers collected for the old shape."""
    out = await engine.submit_profile(
        _tenant_row(), profile=_profile(requirements_fingerprint="a" * 64))
    assert out["status"] == engine.REQUIREMENTS_CHANGED


async def _prepare_with_everything_else_ready():
    """prepare_profile with every step before Gate 1 satisfied, so the ONLY thing
    under test is the authorisation gate."""
    from services import regulatory_ireland as ie_ux

    class Reqs:
        regulation_sid, friendly_name = "RNqa", "IE local business"
        iso_country, number_type, end_user_type = "IE", "local", "business"
        end_user_field_names = ("business_name",)
        documents: list = []
        def fingerprint(self): return "f" * 64

    found = type("F", (), {"ok": True, "requirements": Reqs(), "status": "ok",
                           "detail": ""})()
    with patch.object(engine.rq, "discover_regulation", new=AsyncMock(return_value=found)), \
         patch.object(engine.db_reg, "unstorable_fields", return_value=[]), \
         patch.object(engine.db_reg, "upsert_business_details",
                      new=AsyncMock(return_value={"business_name": "Acme"})), \
         patch.object(engine.db_reg, "attributes_from_details",
                      return_value={"business_name": "Acme"}), \
         patch.object(engine.db_reg, "find_address",
                      new=AsyncMock(return_value={"id": ADDR, "address_sid": "ADx",
                                                  "validated": True})), \
         patch.object(ie_ux, "invalid_enum_fields", return_value=[]), \
         patch.object(ie_ux, "unresolved_declarations", return_value=[]), \
         patch.object(ie_ux, "missing_fields", return_value=[]), \
         patch.object(engine, "_resolve_declaration",
                      new=AsyncMock(return_value={"ok": True, "attributes": {},
                                                  "source": "persisted"})), \
         patch.object(engine, "_ensure_draft_profile",
                      new=AsyncMock(return_value=_profile())), \
         patch.object(engine, "_tenant_client", return_value=(object(), "ACsub")):
        return await engine.prepare_profile(_tenant_row(), attributes={})


def _tenant_row():
    return {"id": TENANT, "business_country_code": "IE",
            "twilio_subaccount_sid": "ACsub", "twilio_auth_token": "tok"}


# ═══ 2. Gate 2 — re-checked immediately before the provider call ═══════════

class _Bundles:
    """A Twilio bundles resource that records what it was asked to do."""

    def __init__(self, status="draft", on_update=None, on_fetch=None):
        self.status, self.updates = status, []
        self.on_update, self.on_fetch = on_update, on_fetch

    def __call__(self, sid):
        return self

    def update(self, status=None, **k):
        self.updates.append(status)
        if self.on_update:
            return self.on_update(status)
        self.status = status
        return type("B", (), {"status": status})()

    def fetch(self):
        if self.on_fetch:
            return self.on_fetch()
        return type("B", (), {"status": self.status})()


def _client(bundles):
    rc = type("RC", (), {"bundles": bundles})()
    return type("C", (), {"numbers": type("N", (), {
        "v2": type("V", (), {"regulatory_compliance": rc})()})()})()


def _submit_ready(bundles, *, authorized=True, auth_status=engine.AUTHORIZATION_STALE,
                  transition_ok=True):
    """Everything submit_profile needs, with the authorisation answer under test."""
    class Reqs:
        regulation_sid = "RNqa"
        end_user_field_names = ("business_name",)
        def fingerprint(self): return "f" * 64

    found = type("F", (), {"ok": True, "requirements": Reqs(), "status": "ok",
                           "detail": ""})()
    auth = ({"ok": True, "status": engine.OK, "authorization": {"id": "auth1"}}
            if authorized else {"ok": False, "status": auth_status})
    return [
        patch.object(engine, "_tenant_client", return_value=(_client(bundles), "ACsub")),
        patch.object(engine.rq, "discover_regulation", new=AsyncMock(return_value=found)),
        patch.object(engine.db_reg, "get_address",
                     new=AsyncMock(return_value={"id": ADDR, "validated": True})),
        patch.object(engine.db_reg, "get_business_details",
                     new=AsyncMock(return_value={"business_name": "Acme"})),
        patch.object(engine.db_reg, "attributes_from_details",
                     return_value={"business_name": "Acme"}),
        patch.object(engine, "submission_blockers", return_value=[]),
        patch.object(engine, "check_authorization", new=AsyncMock(return_value=auth)),
        patch.object(engine.db_reg, "transition_profile",
                     new=AsyncMock(return_value=transition_ok and _profile())),
        patch.object(engine.db_reg, "update_profile", new=AsyncMock(return_value=_profile())),
    ]


def _with(patches):
    import contextlib
    stack = contextlib.ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


@pytest.mark.parametrize("status", [
    engine.AUTHORIZATION_REVOKED, engine.AUTHORIZATION_STALE,
    engine.AUTHORIZATION_NOT_RECORDED, engine.AUTHORIZATION_WRONG_SCOPE,
])
@pytest.mark.asyncio
async def test_gate_2_blocks_submission_after_the_resources_were_built(status):
    """The resources already exist. Consent moved anyway -- so the filing stops."""
    bundles = _Bundles()
    with _with(_submit_ready(bundles, authorized=False, auth_status=status)):
        out = await engine.submit_profile(_tenant_row(), profile=_profile())
    assert out["status"] == status
    assert bundles.updates == [], "a refused filing still called the provider"


@pytest.mark.asyncio
async def test_gate_2_runs_after_the_requirements_check_not_before_it():
    """Placement matters: a check that runs before the drift check would pass a
    filing whose regulation had changed underneath it."""
    import inspect
    src = inspect.getsource(engine.submit_profile)
    fp_check = src.index("stored_fp != reqs.fingerprint()")
    auth_check = src.index("authorized = await check_authorization")
    provider_call = src.index('update(status="pending-review")')
    assert fp_check < auth_check < provider_call


# ═══ 3. submission idempotency and the unknown outcome ════════════════════

@pytest.mark.asyncio
async def test_an_already_submitted_profile_is_not_submitted_again():
    bundles = _Bundles()
    with _with(_submit_ready(bundles)):
        out = await engine.submit_profile(
            _tenant_row(), profile=_profile(state=st.PENDING_REVIEW))
    assert out["ok"] and out["already_submitted"] is True
    assert bundles.updates == []


@pytest.mark.parametrize("state", [st.APPROVED, st.REJECTED, st.ACTIVE,
                                   st.NUMBER_PROVISIONING])
@pytest.mark.asyncio
async def test_a_decided_filing_is_never_resubmitted(state):
    """The state machine is the fence: none of these has a legal edge to
    SUBMITTING, so no path can file them a second time."""
    assert st.transition(state, st.SUBMITTING)[0] == st.ILLEGAL
    bundles = _Bundles()
    with _with(_submit_ready(bundles)):
        out = await engine.submit_profile(_tenant_row(), profile=_profile(state=state))
    assert not out["ok"]
    assert bundles.updates == []


@pytest.mark.asyncio
async def test_losing_the_race_to_another_submitter_does_not_submit():
    bundles = _Bundles()
    with _with(_submit_ready(bundles, transition_ok=False)):
        out = await engine.submit_profile(_tenant_row(), profile=_profile())
    assert out["status"] == engine.NOT_READY
    assert "lost_race_to_another_submitter" in out["blockers"]
    assert bundles.updates == []


@pytest.mark.asyncio
async def test_an_unknown_outcome_that_the_provider_accepted_is_recorded_not_retried():
    """THE defect this gate fixes. The submit call errored; Twilio took it anyway.
    Rolling back would invite a second filing of a regulated identity."""
    def boom(status):
        raise TimeoutError("read timed out")

    # The provider reports the bundle as filed when we go and look.
    bundles = _Bundles(on_update=boom,
                       on_fetch=lambda: type("B", (), {"status": "pending-review"})())
    transitions = []

    async def record(pid, *, expected_state, new_state, patch=None):
        transitions.append((expected_state, new_state))
        return _profile(state=new_state)

    patches = _submit_ready(bundles)
    patches = [p for p in patches if "transition_profile" not in str(p)]
    with _with(patches), \
         patch.object(engine.db_reg, "transition_profile", new=record):
        out = await engine.submit_profile(_tenant_row(), profile=_profile())

    assert out["ok"] and out["recovered_from_unknown"] is True
    assert out["state"] == st.PENDING_REVIEW
    # It must NOT have been rolled back to a resubmittable state.
    assert (st.SUBMITTING, st.READY_TO_SUBMIT) not in transitions
    assert (st.SUBMITTING, st.PENDING_REVIEW) in transitions
    assert bundles.updates == ["pending-review"], "submitted more than once"


@pytest.mark.asyncio
async def test_an_unknown_outcome_the_provider_did_not_take_rolls_back_for_retry():
    def boom(status):
        raise TimeoutError("read timed out")

    bundles = _Bundles(on_update=boom,
                       on_fetch=lambda: type("B", (), {"status": "draft"})())
    transitions = []

    async def record(pid, *, expected_state, new_state, patch=None):
        transitions.append((expected_state, new_state))
        return _profile(state=new_state)

    patches = [p for p in _submit_ready(bundles) if "transition_profile" not in str(p)]
    with _with(patches), patch.object(engine.db_reg, "transition_profile", new=record):
        out = await engine.submit_profile(_tenant_row(), profile=_profile())

    assert out["status"] == engine.PROVIDER_UNAVAILABLE
    assert (st.SUBMITTING, st.READY_TO_SUBMIT) in transitions


@pytest.mark.asyncio
async def test_an_unreachable_provider_leaves_the_filing_for_reconciliation():
    """We cannot find out whether it landed. Staying in SUBMITTING is the safe
    answer: that state is non-terminal, so the sweep resolves it -- and nobody
    resubmits on a guess."""
    def boom(status):
        raise TimeoutError("read timed out")

    def also_boom():
        raise ConnectionResetError("connection reset")

    bundles = _Bundles(on_update=boom, on_fetch=also_boom)
    transitions = []

    async def record(pid, *, expected_state, new_state, patch=None):
        transitions.append((expected_state, new_state))
        return _profile(state=new_state)

    patches = [p for p in _submit_ready(bundles) if "transition_profile" not in str(p)]
    with _with(patches), patch.object(engine.db_reg, "transition_profile", new=record):
        out = await engine.submit_profile(_tenant_row(), profile=_profile())

    assert out["status"] == engine.SUBMISSION_OUTCOME_UNKNOWN
    assert out["state"] == st.SUBMITTING
    assert transitions == [(st.READY_TO_SUBMIT, st.SUBMITTING)]
    assert st.SUBMITTING in st.NONTERMINAL_STATES   # the sweep will resolve it


@pytest.mark.parametrize("provider_status,filed", [
    ("pending-review", True), ("in-review", True), ("twilio-approved", True),
    ("twilio-rejected", True), ("provisionally-approved", True), ("draft", False),
])
def test_the_filed_vocabulary_matches_the_state_map(provider_status, filed):
    """A status this set calls 'filed' but the state map cannot translate would
    strand a profile; one it calls draft but the provider has filed would double
    submit."""
    assert (provider_status in engine.FILED_BUNDLE_STATUSES) is filed
    if filed:
        assert st.state_for_provider_status(provider_status)[0] is not None


# ═══ 4. a provider failure is never a rejection ═══════════════════════════

@pytest.mark.parametrize("failure", [
    pytest.param(RuntimeError("HTTP 401 Unauthorized"), id="401"),
    pytest.param(RuntimeError("HTTP 403 Forbidden"), id="403"),
    pytest.param(RuntimeError("HTTP 429 Too Many Requests"), id="429"),
    pytest.param(RuntimeError("HTTP 500 Internal Server Error"), id="500"),
    pytest.param(RuntimeError("HTTP 503 Service Unavailable"), id="503"),
    pytest.param(ValueError("Expecting value: line 1 column 1"), id="malformed"),
    pytest.param(TimeoutError("read timed out"), id="timeout"),
])
@pytest.mark.asyncio
async def test_a_provider_failure_never_becomes_a_rejection(failure):
    """Told they were rejected, a customer starts editing correct data."""
    class Evals:
        def create(self): raise failure

    class B:
        def __call__(self, sid): return self
        evaluations = Evals()

    out = await engine.evaluate(bundle_sid=BUNDLE, client=_client(B()))
    assert out["status"] == engine.PROVIDER_UNAVAILABLE
    assert out.get("evaluation_status") != "noncompliant"
    assert out.get("compliant") is not False or "compliant" not in out


@pytest.mark.asyncio
async def test_an_evaluation_failure_leaves_the_stored_verdict_untouched():
    patched = {}

    async def upd(pid, patch):
        patched.update(patch)
        return _profile()

    with patch.object(engine, "_tenant_client", return_value=(object(), "ACsub")), \
         patch.object(engine, "evaluate",
                      new=AsyncMock(return_value={"ok": False,
                                                  "status": engine.PROVIDER_UNAVAILABLE})), \
         patch.object(engine.db_reg, "update_profile", new=upd):
        out = await engine.evaluate_profile(_tenant_row(), profile=_profile())
    assert out["status"] == engine.PROVIDER_UNAVAILABLE
    assert patched == {}, "a provider outage wrote an evaluation verdict"


@pytest.mark.parametrize("provider_status", ["", "some-new-status-twilio-added"])
def test_an_unmapped_provider_status_causes_no_transition(provider_status):
    target, reason = st.state_for_provider_status(provider_status)
    assert target is None and reason


# ═══ 5. the orchestrator ═════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_orchestrator_never_forwards_caller_attributes():
    """The load-bearing property: the filing is built from the facts the customer
    authorised, and no request payload can put a different value in front of the
    provider."""
    seen = {}

    async def prep(tenant, *, attributes, tenant_location_id=None, **kw):
        seen["attributes"] = attributes
        return {"ok": False, "status": engine.NOT_READY}

    with patch.object(filing, "_tenant", new=AsyncMock(return_value=_tenant_row())), \
         patch.object(filing, "_resolve_address",
                      new=AsyncMock(return_value={"id": ADDR, "validated": True,
                                                  "tenant_location_id": None})), \
         patch.object(filing.engine, "prepare_profile", new=prep):
        await filing.advance(TENANT)
    assert seen["attributes"] == {}


@pytest.mark.asyncio
async def test_the_orchestrator_does_not_submit_unless_asked():
    """Preparing and FILING are different acts. The second puts a business in
    front of a regulator, so it is never a default."""
    with patch.object(filing, "_tenant", new=AsyncMock(return_value=_tenant_row())), \
         patch.object(filing, "_resolve_address",
                      new=AsyncMock(return_value={"id": ADDR, "validated": True,
                                                  "tenant_location_id": None})), \
         patch.object(filing.engine, "prepare_profile",
                      new=AsyncMock(return_value={"ok": True, "status": engine.OK,
                                                  "profile": _profile()})), \
         patch.object(filing.engine, "evaluate_profile",
                      new=AsyncMock(return_value={"ok": True, "status": engine.OK,
                                                  "compliant": True,
                                                  "state": st.READY_TO_SUBMIT})), \
         patch.object(filing.engine, "submit_profile", new=AsyncMock()) as sub:
        out = await filing.advance(TENANT)
    assert out["reached"] == filing.EVALUATED
    sub.assert_not_called()


@pytest.mark.asyncio
async def test_a_noncompliant_evaluation_stops_before_submission():
    """Filing something we already know is incomplete spends a real regulatory
    review to be told so."""
    with patch.object(filing, "_tenant", new=AsyncMock(return_value=_tenant_row())), \
         patch.object(filing, "_resolve_address",
                      new=AsyncMock(return_value={"id": ADDR, "validated": True,
                                                  "tenant_location_id": None})), \
         patch.object(filing.engine, "prepare_profile",
                      new=AsyncMock(return_value={"ok": True, "status": engine.OK,
                                                  "profile": _profile()})), \
         patch.object(filing.engine, "evaluate_profile",
                      new=AsyncMock(return_value={"ok": True, "status": engine.OK,
                                                  "compliant": False,
                                                  "failed_requirements": ["x"]})), \
         patch.object(filing.engine, "submit_profile", new=AsyncMock()) as sub:
        out = await filing.advance(TENANT, submit=True)
    assert not out["ok"] and out["reached"] == filing.EVALUATED
    sub.assert_not_called()


@pytest.mark.asyncio
async def test_a_gate_1_refusal_stops_the_orchestrator_before_evaluation():
    with patch.object(filing, "_tenant", new=AsyncMock(return_value=_tenant_row())), \
         patch.object(filing, "_resolve_address",
                      new=AsyncMock(return_value={"id": ADDR, "validated": True,
                                                  "tenant_location_id": None})), \
         patch.object(filing.engine, "prepare_profile",
                      new=AsyncMock(return_value={"ok": False,
                                                  "status": engine.AUTHORIZATION_REVOKED})), \
         patch.object(filing.engine, "evaluate_profile", new=AsyncMock()) as ev, \
         patch.object(filing.engine, "submit_profile", new=AsyncMock()) as sub:
        out = await filing.advance(TENANT, submit=True)
    assert out["status"] == engine.AUTHORIZATION_REVOKED
    ev.assert_not_called(); sub.assert_not_called()


@pytest.mark.asyncio
async def test_another_tenants_address_cannot_be_advanced():
    """get_address is tenant-scoped, so a foreign id is absent rather than usable."""
    async def scoped(tenant_id, address_id):
        return None

    with patch.object(filing, "_tenant", new=AsyncMock(return_value=_tenant_row())), \
         patch.object(filing.db_reg, "get_address", new=scoped), \
         patch.object(filing.engine, "prepare_profile", new=AsyncMock()) as prep:
        out = await filing.advance(TENANT, regulatory_address_id=ADDR)
    assert out["status"] == engine.NOT_READY
    assert out["detail"] == "address_not_on_this_account"
    prep.assert_not_called()


@pytest.mark.asyncio
async def test_a_multi_location_tenant_must_name_the_premises():
    """Picking one on their behalf would file a premises nobody chose."""
    rows = [{"id": ADDR, "validated": True}, {"id": "other", "validated": True}]

    class QB:
        def __init__(self): pass
        def table(self, n): return self
        def select(self, *a): return self
        def eq(self, *a): return self
        def order(self, *a): return self
        def execute(self): return type("R", (), {"data": rows})()

    with patch.object(filing, "get_client", return_value=QB()):
        got = await filing._resolve_address(TENANT, "IE", "")
    assert got is None


# ═══ 6. the customer-safe status contract ════════════════════════════════

def test_every_profile_state_has_a_customer_view():
    for state in st.ALL_STATES:
        assert filing.is_mapped(state), state
        view = filing.customer_status({"state": state})
        assert view["message"] and isinstance(view["action_required"], bool)


@pytest.mark.parametrize("state,expected", [
    (st.DETAILS_REQUIRED, filing.ACTION_REQUIRED),
    (st.READY_TO_SUBMIT, filing.READY_FOR_SUBMISSION),
    (st.PENDING_REVIEW, filing.UNDER_REVIEW),
    (st.MORE_INFORMATION_REQUIRED, filing.ACTION_REQUIRED),
    (st.REJECTED, filing.ACTION_REQUIRED),
    (st.APPROVED, filing.APPROVED),
])
def test_provider_outcomes_map_to_safe_customer_states(state, expected):
    assert filing.customer_status({"state": state})["status"] == expected


def test_the_customer_view_leaks_no_provider_detail():
    """failure_reason is excluded even though it is often the most useful field:
    Twilio's rejection text can quote the submitted identity back."""
    view = filing.customer_status(_profile(
        state=st.REJECTED, bundle_status="twilio-rejected",
        failure_reason="EndUser BUxxxx business_name did not match CRO record",
        failure_code="noncompliant"))
    blob = str(view)
    for leak in ("BU", "twilio", "EndUser", "bundle_status", "failure_reason",
                 "ACsub", "RNqa", BUNDLE):
        assert leak not in blob, leak


def test_nothing_reads_as_submitted_before_it_is_filed():
    for state in (st.NOT_STARTED, st.DETAILS_REQUIRED, st.READY_TO_SUBMIT,
                  st.ADDRESS_VALIDATION_FAILED):
        assert filing.customer_status({"state": state})["submitted"] is False
    for state in (st.PENDING_REVIEW, st.APPROVED, st.REJECTED):
        assert filing.customer_status({"state": state})["submitted"] is True


def test_only_a_real_approval_reads_as_approved():
    """provisionally-approved maps to pending_review, so it must not read as
    approved here either -- W9C measured a purchase refused on exactly that."""
    assert st.PROVIDER_STATUS_MAP["provisionally-approved"] == st.PENDING_REVIEW
    assert filing.customer_status({"state": st.PENDING_REVIEW})["approved"] is False
    assert filing.customer_status({"state": st.APPROVED})["approved"] is True


# ═══ 7. scheduled reconciliation ═════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_scheduled_pass_is_dry_run_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv(rec.APPLY_ENV, raising=False)
    assert rec.scheduled_apply_enabled() is False
    with patch.object(rec, "reconcile_all",
                      new=AsyncMock(return_value={"inspected": 0, "counts": {},
                                                  "results": []})) as ra:
        out = await rec.run_scheduled()
    assert out["dry_run"] is True
    assert ra.call_args.kwargs["dry_run"] is True


@pytest.mark.asyncio
async def test_the_scheduled_pass_is_bounded(monkeypatch):
    monkeypatch.delenv(rec.APPLY_ENV, raising=False)
    with patch.object(rec, "reconcile_all",
                      new=AsyncMock(return_value={"inspected": 0, "counts": {},
                                                  "results": []})) as ra:
        await rec.run_scheduled()
    assert ra.call_args.kwargs["limit"] == rec.SCHEDULED_BATCH
    assert rec.SCHEDULED_BATCH <= 100


@pytest.mark.asyncio
async def test_the_scheduled_pass_never_raises_into_the_cron(monkeypatch):
    """It shares a process with the retention purge and the trial reminders."""
    monkeypatch.delenv(rec.APPLY_ENV, raising=False)
    with patch.object(rec, "reconcile_all",
                      new=AsyncMock(side_effect=RuntimeError("postgrest down"))):
        out = await rec.run_scheduled()
    assert out["ok"] is False and "error" in out


@pytest.mark.asyncio
async def test_a_dry_run_mutates_nothing():
    profile = _profile(state=st.PENDING_REVIEW)
    live = type("B", (), {"status": "twilio-approved"})()

    class B:
        def __call__(self, sid): return self
        def fetch(self): return live

    with patch.object(rec, "get_client",
                      return_value=type("C", (), {"table": lambda s, n: _Rows(
                          [{"id": TENANT, "twilio_subaccount_sid": "ACsub",
                            "twilio_auth_token": "tok"}])})()), \
         patch.object(rec.telephony, "_sub_client", return_value=_client(B())), \
         patch.object(rec.cb, "apply_status", new=AsyncMock()) as apply_, \
         patch.object(rec.db_reg, "update_profile", new=AsyncMock()) as upd:
        out = await rec.reconcile_profile(profile, dry_run=True)

    assert out["would_change"] is True and out["target_state"] == st.APPROVED
    apply_.assert_not_called()
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_reconciliation_never_advances_a_terminal_profile():
    for state in st.TERMINAL_STATES:
        out = await rec.reconcile_profile(_profile(state=state), dry_run=False)
        assert out["outcome"] == rec.SKIPPED_TERMINAL


@pytest.mark.asyncio
async def test_reconciliation_refuses_a_bundle_on_the_wrong_account():
    with patch.object(rec, "get_client",
                      return_value=type("C", (), {"table": lambda s, n: _Rows(
                          [{"id": TENANT, "twilio_subaccount_sid": "ACother",
                            "twilio_auth_token": "tok"}])})()):
        out = await rec.reconcile_profile(_profile(state=st.PENDING_REVIEW),
                                          dry_run=False)
    assert out["outcome"] == rec.OWNERSHIP_CONFLICT


@pytest.mark.asyncio
async def test_a_provider_outage_during_reconciliation_is_not_a_decision():
    class B:
        def __call__(self, sid): return self
        def fetch(self): raise TimeoutError("read timed out")

    with patch.object(rec, "get_client",
                      return_value=type("C", (), {"table": lambda s, n: _Rows(
                          [{"id": TENANT, "twilio_subaccount_sid": "ACsub",
                            "twilio_auth_token": "tok"}])})()), \
         patch.object(rec.telephony, "_sub_client", return_value=_client(B())), \
         patch.object(rec.cb, "apply_status", new=AsyncMock()) as apply_:
        out = await rec.reconcile_profile(_profile(state=st.PENDING_REVIEW),
                                          dry_run=False)
    assert out["outcome"] == rec.PROVIDER_UNAVAILABLE
    apply_.assert_not_called()


def test_reconciliation_never_submits_or_buys_anything():
    """A sweep that could resubmit would file a regulated identity on a schedule,
    with nobody present who consented to it happening then."""
    referenced = identifiers(rec)
    for forbidden in ("submit_profile", "purchase_number_with_sid", "purchase_number",
                      "prepare_profile", "resolve_end_user", "ensure_bundle",
                      "advance", "register_permanent"):
        assert forbidden not in referenced, forbidden


def test_the_daily_cron_calls_the_scheduled_pass():
    """Stage M: scheduling is a cron entry that exists, not a script that could
    be run. This asserts the wiring, so 'it is scheduled' is checkable."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "scripts" / "recrawl_cron.py"
    text = src.read_text()
    assert "regulatory_reconcile" in text
    assert "run_scheduled()" in text


class _Rows:
    def __init__(self, rows): self.rows = rows
    def select(self, *a): return self
    def eq(self, *a): return self
    def limit(self, *a): return self
    def execute(self): return type("R", (), {"data": self.rows})()


# ═══ 8. Stage J — one way to create a regulatory identity, not two ════════
#
# /details, /evaluate and /submit used to drive prepare_profile directly with a
# caller-supplied attribute bag, which meant a browser could put values in front
# of the provider that differed from the ones the customer authorised, and could
# run the resource-creation sequence in whatever order it liked. They are wrappers
# now. Mutation testing found this unpinned: reverting one of them to the old
# shape left every other test green.

from typing import Annotated                                    # noqa: E402
from fastapi import FastAPI, Header, HTTPException, Request     # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

from routers import regulatory as reg_router                    # noqa: E402


@pytest.fixture
def operator_client(monkeypatch):
    from services.security import require_tenant_owner

    async def fake_owner(request: Request,
                         authorization: Annotated[str | None, Header()] = None):
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        if token != request.path_params.get("tenant_id"):
            raise HTTPException(status_code=403, detail="Access denied")

    app = FastAPI()
    app.include_router(reg_router.router)
    app.dependency_overrides[require_tenant_owner] = fake_owner

    seen = {}

    async def advance(tenant_id, *, regulatory_address_id="", submit=False):
        seen["tenant_id"] = tenant_id
        seen["regulatory_address_id"] = regulatory_address_id
        seen["submit"] = submit
        return {"ok": True, "status": engine.OK, "reached": filing.EVALUATED,
                "profile": _profile(), "state": st.READY_TO_SUBMIT}

    monkeypatch.setattr(reg_router.filing, "advance", advance)
    return TestClient(app, raise_server_exceptions=False), seen


@pytest.mark.parametrize("path", ["details", "evaluate", "submit"])
def test_the_low_level_routes_go_through_the_orchestrator(operator_client, path):
    c, seen = operator_client
    r = c.post(f"/regulatory/{TENANT}/{path}",
               json={"regulatory_address_id": ADDR},
               headers={"Authorization": f"Bearer {TENANT}"})
    assert r.status_code == 200, r.text
    assert seen["tenant_id"] == TENANT
    assert seen["regulatory_address_id"] == ADDR
    # Only /submit files. The other two stop at ready-to-submit.
    assert seen["submit"] is (path == "submit")


@pytest.mark.parametrize("path", ["details", "evaluate", "submit"])
def test_a_caller_supplied_attribute_bag_reaches_nothing(operator_client, path):
    """The bag is ignored, not honoured. Whatever a client puts here, the filing
    is still built from the facts the customer authorised."""
    c, seen = operator_client
    with patch.object(engine, "prepare_profile", new=AsyncMock()) as prep:
        r = c.post(f"/regulatory/{TENANT}/{path}",
                   json={"attributes": {"business_name": "Somebody Else Ltd",
                                        "business_identity": "INDEPENDENT_SOFTWARE_VENDOR"},
                         "profile_id": "someone-elses-profile"},
                   headers={"Authorization": f"Bearer {TENANT}"})
    assert r.status_code == 200
    prep.assert_not_called()          # the route no longer calls it directly
    assert "attributes" not in seen


def test_the_operator_router_cannot_reach_a_provider_resource_directly():
    """Structural counterpart: there is ONE path to identity creation, and it is
    the orchestrator. A second one is how the two drift."""
    referenced = identifiers(reg_router)
    for forbidden in ("prepare_profile", "submit_profile", "resolve_end_user",
                      "ensure_supporting_document", "ensure_bundle",
                      "ensure_item_assignments", "recover_end_user"):
        assert forbidden not in referenced, forbidden
    # ...and the orchestrator IS what it reaches for.
    assert "advance" in referenced


def test_no_route_lets_a_caller_name_a_profile_by_id():
    """A caller-chosen profile_id let a client evaluate one filing and submit
    another. The orchestrator resolves the profile from tenant and premises."""
    referenced = identifiers(reg_router)
    assert "_owned_profile" not in referenced
    import inspect
    assert 'get("profile_id")' not in inspect.getsource(reg_router)


# ═══ 9. the callback is a wake-up signal, not an instruction ══════════════

from services import regulatory_callback as cb                  # noqa: E402


def test_the_callback_cannot_reach_a_purchase_or_an_orchestration():
    """W9I-F will buy a +353 on approval and must verify that approval against
    the provider directly. A callback is an unauthenticated-by-nature message
    that merely carried a valid signature; it must never be the thing that
    spends money or files anything."""
    referenced = identifiers(cb)
    for forbidden in ("purchase_number", "purchase_number_with_sid", "advance",
                      "prepare_profile", "submit_profile", "register_permanent",
                      "reprovision_tenant_number", "create_trial_subscription"):
        assert forbidden not in referenced, forbidden


@pytest.mark.asyncio
async def test_a_late_callback_cannot_walk_an_approved_filing_backwards():
    """Redelivery is normal. An approved profile dragged back into review would
    un-approve a business that is already being provisioned."""
    moved = []

    async def upd(pid, patch):
        moved.append(("update", patch.get("bundle_status")))
        return _profile()

    async def trans(pid, *, expected_state, new_state, patch=None):
        moved.append(("transition", new_state))
        return _profile(state=new_state)

    with patch.object(cb.db_reg, "update_profile", new=upd), \
         patch.object(cb.db_reg, "transition_profile", new=trans):
        out = await cb.apply_status(profile=_profile(state=st.APPROVED),
                                    provider_status="pending-review")
    assert out["outcome"] == st.ILLEGAL
    assert out["state"] == st.APPROVED
    assert ("transition", st.PENDING_REVIEW) not in moved


@pytest.mark.asyncio
async def test_a_redelivered_callback_is_idempotent_not_an_error():
    """Refusing would make Twilio retry forever."""
    with patch.object(cb.db_reg, "update_profile", new=AsyncMock(return_value=_profile())), \
         patch.object(cb.db_reg, "transition_profile", new=AsyncMock()) as trans:
        out = await cb.apply_status(profile=_profile(state=st.PENDING_REVIEW),
                                    provider_status="pending-review")
    assert out["outcome"] == st.NO_CHANGE
    trans.assert_not_called()


@pytest.mark.asyncio
async def test_an_unmapped_callback_status_moves_nothing():
    with patch.object(cb.db_reg, "update_profile", new=AsyncMock(return_value=_profile())) as upd, \
         patch.object(cb.db_reg, "transition_profile", new=AsyncMock()) as trans:
        out = await cb.apply_status(profile=_profile(state=st.PENDING_REVIEW),
                                    provider_status="some-status-twilio-added-later")
    assert out["outcome"] == "unmapped"
    trans.assert_not_called()
    upd.assert_called_once()          # recorded verbatim, acted on not at all


@pytest.mark.asyncio
async def test_a_callback_racing_a_reconciliation_cannot_double_apply():
    """Both paths go through the same CAS; the loser reports it rather than
    writing a second time."""
    async def lost(pid, *, expected_state, new_state, patch=None):
        return None                      # the fenced update matched no rows

    with patch.object(cb.db_reg, "update_profile", new=AsyncMock(return_value=_profile())), \
         patch.object(cb.db_reg, "transition_profile", new=lost):
        out = await cb.apply_status(profile=_profile(state=st.PENDING_REVIEW),
                                    provider_status="twilio-approved")
    assert out["outcome"] == "lost_race"
    assert out["state"] == st.PENDING_REVIEW


def test_approval_reaching_the_number_gate_requires_a_direct_provider_check():
    """Pins the boundary W9I-F depends on: APPROVED is the ONLY state with an
    edge to number provisioning, and nothing in the callback path may take it."""
    assert st.NUMBER_PROVISIONING in st.ALLOWED[st.APPROVED]
    for state in st.ALL_STATES:
        if state != st.APPROVED:
            assert st.NUMBER_PROVISIONING not in st.ALLOWED.get(state, ()), state
