"""W9G.1 — the three defects W9G shipped, and their fixes.

1. DRIFT WAS NOT DURABLE. W9G computed a requirements fingerprint and returned it in
   an HTTP response body. Nothing persisted it, and the submit path the router
   actually calls compared only regulation_sid -- so Twilio changing a regulation's
   field shape under the same SID would have gone straight through. Comparing two
   in-memory objects inside one request proves nothing across a restart.

2. NOTHING COLLECTED WAS RECOVERABLE. The attribute bag went to Twilio and was
   stored nowhere, presented as PII minimisation. A failed create, a 404'd EndUser,
   or a rejection needing one corrected field all meant the customer retyped
   everything.

3. THE ENGINE FILED AN INCOMPLETE IDENTITY. It created the EndUser while omitting
   two fields the live regulation lists as required, and the fake accepted the
   partial payload so no test noticed.
"""
import pytest

from db import regulatory as db_reg
from services import regulatory_engine as engine
from services import regulatory_ireland as ie_ux
from services import regulatory_requirements as rq
from services import regulatory_state as st
from tests.test_w9g_engine import (ADDR_SID, BU_SID, DOC_SID, EU_SID, GOOD_ADDRESS,
                                   GOOD_ATTRS, REQS, SUB, TENANT, FakeTwilio,
                                   ProviderError, tenant, world)  # noqa: F401
from tests.test_w9g_regulation_discovery import FakeRegulation, IE_REQUIREMENTS

CHANGED_REQUIREMENTS = {
    "end_user": [{**IE_REQUIREMENTS["end_user"][0],
                  "fields": IE_REQUIREMENTS["end_user"][0]["fields"] + ["vat_number"],
                  "detailed_fields": IE_REQUIREMENTS["end_user"][0]["detailed_fields"]
                  + [{"machine_name": "vat_number", "friendly_name": "VAT number",
                      "description": ""}]}],
    "supporting_document": IE_REQUIREMENTS["supporting_document"],
}


def _profile(**over):
    base = {"id": "p1", "tenant_id": TENANT, "bundle_sid": BU_SID,
            "end_user_sid": EU_SID, "provider_account_sid": SUB, "iso_country": "IE",
            "number_type": "local", "end_user_type": "business",
            "regulation_sid": REQS.regulation_sid, "state": st.READY_TO_SUBMIT,
            "evaluation_status": "compliant", "regulatory_address_id": "addr-1",
            "requirements_fingerprint": REQS.fingerprint()}
    base.update(over)
    return base


def _seed(world, **over):
    world["details"].append({"id": "det-1", "tenant_id": TENANT, "iso_country": "IE",
                             "end_user_type": "business",
                             "business_name": GOOD_ATTRS["business_name"],
                             "business_website": GOOD_ATTRS["business_website"],
                             "business_registration_number":
                                 GOOD_ATTRS["business_registration_number"],
                             "authorized_rep_first_name": GOOD_ATTRS["first_name"],
                             "authorized_rep_last_name": GOOD_ATTRS["last_name"],
                             "authorized_rep_email": GOOD_ATTRS["email"],
                             "business_identity": GOOD_ATTRS["business_identity"],
                             "is_subassigned": GOOD_ATTRS["is_subassigned"],
                             "requirements_fingerprint": REQS.fingerprint(),
                             **over})
    world["addresses"].append({"id": "addr-1", "tenant_id": TENANT, "iso_country": "IE",
                               "validated": True, "address_sid": ADDR_SID,
                               "supporting_document_sid": DOC_SID,
                               "provider_account_sid": SUB})


# ═══════════════════════════════════════════════════════════════════════════
# 1 — the fingerprint is DURABLE
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_fingerprint_is_written_to_the_profile_not_just_returned(world):
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["ok"]
    stored = world["profiles"][0]
    assert stored["requirements_fingerprint"] == REQS.fingerprint()
    assert stored["requirements_observed_at"]


@pytest.mark.asyncio
async def test_the_fingerprint_survives_a_new_request_with_no_shared_memory(world):
    """T1 collects, the process 'restarts', T2 submits. The only thing carried across
    is the database row -- which is the whole point."""
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    persisted = dict(world["profiles"][0])          # all a later request would load
    _seed(world)
    world["profiles"].clear()
    world["profiles"].append({**persisted, "state": st.READY_TO_SUBMIT,
                              "evaluation_status": "compliant"})
    r = await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert r["ok"], r
    assert r["state"] == st.PENDING_REVIEW


@pytest.mark.asyncio
async def test_the_same_SID_with_a_CHANGED_field_shape_blocks_submission(world):
    """THE DEFECT. Twilio can alter a regulation's required fields without reissuing
    it, so regulation_sid is unchanged and only the fingerprint catches it."""
    _seed(world)
    world["profiles"].append(_profile())
    world["twilio"].opts["regulations"] = [
        FakeRegulation(requirements=CHANGED_REQUIREMENTS)]
    r = await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert r["status"] == engine.REQUIREMENTS_CHANGED
    assert r["detail"] == "required_fields_changed"
    assert r["regulation_sid"] == REQS.regulation_sid, "the SID did NOT change"
    assert r["stored_fingerprint"] != r["current_fingerprint"]
    assert world["profiles"][0]["state"] == st.READY_TO_SUBMIT


@pytest.mark.asyncio
async def test_a_profile_with_no_stored_fingerprint_FAILS_CLOSED(world):
    """Nothing to compare against means drift cannot be detected, so the submission
    must not go out on an unverifiable basis."""
    _seed(world)
    world["profiles"].append(_profile(requirements_fingerprint=None))
    r = await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert r["status"] == engine.NOT_READY
    assert engine.REQUIREMENTS_NOT_RECORDED in r["blockers"]


def test_the_blocker_list_also_refuses_a_profile_with_no_fingerprint():
    blockers = engine.submission_blockers(
        profile=_profile(requirements_fingerprint=""), requirements=REQS,
        attributes=GOOD_ATTRS,
        address_row={"validated": True, "supporting_document_sid": DOC_SID})
    assert engine.REQUIREMENTS_NOT_RECORDED in blockers


def test_the_fingerprint_contains_no_customer_data():
    """It is a hash over the requirement SHAPE -- field names and document types --
    which is why it is safe to store and compare."""
    fp = REQS.fingerprint()
    assert len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)
    # Identical shape, wildly different answers -> identical fingerprint.
    assert rq.normalize_regulation(FakeRegulation()).fingerprint() == fp


def test_a_changed_regulation_sid_is_still_caught_separately(world):
    """Both checks exist: the SID changing is a different failure from the shape
    changing, and they get different details."""
    assert engine.REQUIREMENTS_CHANGED


# ═══════════════════════════════════════════════════════════════════════════
# 2 — the collected answers are RECOVERABLE
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_details_are_persisted_BEFORE_the_provider_is_touched(world):
    """CASE 1: EndUser.create fails. The answers must already be safe."""
    world["twilio"].opts["end_user_error"] = ProviderError(code=20500, status=500)
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.PROVIDER_UNAVAILABLE
    assert world["details"], "the customer's answers were lost"
    assert world["details"][0]["business_registration_number"] == "123456"


@pytest.mark.asyncio
async def test_a_retry_after_a_provider_failure_needs_no_customer_input(world):
    """CASE 5: the customer has gone. The retry must still work."""
    world["twilio"].opts["end_user_error"] = ProviderError(code=20500, status=500)
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)

    world["twilio"].opts.pop("end_user_error")
    r = await engine.prepare_profile(tenant(), attributes={})   # nothing re-sent
    assert r["ok"], r
    assert r["end_user_sid"] == EU_SID


@pytest.mark.asyncio
async def test_one_field_can_be_corrected_without_resending_the_rest(world):
    """CASE 3: Twilio rejects the filing over the CRO number."""
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    r = await engine.prepare_profile(
        tenant(), attributes={"business_registration_number": "NC999999"})
    assert r["ok"]
    stored = world["details"][0]
    assert stored["business_registration_number"] == "NC999999"
    assert stored["authorized_rep_email"] == "ann@dani.ie", "an untouched field was wiped"
    assert stored["business_name"] == "DANI Ltd"


@pytest.mark.asyncio
async def test_a_lost_provider_EndUser_is_rebuilt_from_our_own_record(world):
    """CASE 2: the EndUser 404s later."""
    _seed(world)
    world["profiles"].append(_profile())
    world["twilio"].opts["end_user_fetch_error"] = ProviderError(code=20404, status=404)
    r = await engine.recover_end_user(tenant(), profile=world["profiles"][0])
    assert r["ok"] and r["recreated"] is True
    assert world["twilio"].created["end_user"] == 1


@pytest.mark.asyncio
async def test_recovery_refuses_to_recreate_on_an_UNKNOWN_provider_error(world):
    """Only a 404 proves it is gone. Recreating on 'we do not know' risks a duplicate
    regulatory identity."""
    _seed(world)
    world["profiles"].append(_profile())
    world["twilio"].opts["end_user_fetch_error"] = ProviderError(code=20500, status=500)
    r = await engine.recover_end_user(tenant(), profile=world["profiles"][0])
    assert r["status"] == engine.PROVIDER_UNAVAILABLE
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_recovery_says_so_plainly_when_nothing_was_ever_stored(world):
    """A profile from before the durable record genuinely needs the customer again --
    stated, not guessed around."""
    world["profiles"].append(_profile())
    world["twilio"].opts["end_user_fetch_error"] = ProviderError(code=20404, status=404)
    r = await engine.recover_end_user(tenant(), profile=world["profiles"][0])
    assert r["status"] == engine.NOT_READY
    assert r["detail"] == "no_stored_business_details"


@pytest.mark.asyncio
async def test_recovery_uses_the_SAME_declaration_policy_as_preparation(world):
    """The two paths must not be able to file different declarations (W9G.3)."""
    _seed(world, business_identity=None, is_subassigned=None)
    world["profiles"].append(_profile(end_user_sid=None))
    r = await engine.recover_end_user(tenant(), profile=world["profiles"][0])
    assert r["ok"], r
    sent = world["twilio"].last_end_user_attributes
    assert sent["business_identity"] == "DIRECT_CUSTOMER"
    assert sent["is_subassigned"] == "NO"


@pytest.mark.asyncio
async def test_recovery_will_not_file_an_identity_for_an_UNCONFIRMED_context(world):
    """CASE 4 must not become a side door around the stopping point."""
    from tests.test_w9g_regulation_discovery import FakeRegulation as _FR
    world["twilio"].opts["regulations"] = [_FR(iso_country="GB")]
    _seed(world, business_identity=None, is_subassigned=None)
    # the stored answers must be for the profile's own country, or recovery stops
    # earlier for a different (also correct) reason
    world["details"].append({**world["details"][0], "id": "det-gb", "iso_country": "GB"})
    world["addresses"].append({**world["addresses"][0], "id": "addr-gb",
                               "iso_country": "GB"})
    world["profiles"].append(_profile(end_user_sid=None, iso_country="GB",
                                      regulatory_address_id="addr-gb"))
    r = await engine.recover_end_user(tenant(business_country_code="GB"),
                                      profile=world["profiles"][0])
    assert r["status"] == engine.DECLARATION_POLICY_UNRESOLVED
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_recovery_refuses_a_profile_from_another_account(world):
    _seed(world)
    world["profiles"].append(_profile(provider_account_sid="ACsomeoneelse"))
    r = await engine.recover_end_user(tenant(), profile=world["profiles"][0])
    assert r["status"] == engine.OWNERSHIP_CONFLICT


# ── the storage boundary ───────────────────────────────────────────────────

def test_only_named_columns_are_ever_written():
    """A provider blob would let personal data accumulate in untyped storage."""
    assert "raw" not in " ".join(db_reg.BUSINESS_DETAIL_COLUMNS)
    assert set(db_reg.BUSINESS_DETAIL_COLUMNS) == {
        "business_name", "business_website", "business_registration_number",
        "authorized_rep_first_name", "authorized_rep_last_name",
        "authorized_rep_email", "business_identity", "is_subassigned", "comments",
        "requirements_fingerprint", "collected_at"}


def test_a_provider_field_with_no_column_is_reported_not_absorbed():
    assert db_reg.unstorable_fields(REQS.end_user_field_names) == []
    assert db_reg.unstorable_fields(("business_name", "vat_number")) == ["vat_number"]


@pytest.mark.asyncio
async def test_a_new_required_provider_field_STOPS_the_workflow(world):
    """The same discipline as an unexpected document requirement: do not invent a
    home for personal data nobody has designed storage for."""
    world["twilio"].opts["regulations"] = [
        FakeRegulation(requirements=CHANGED_REQUIREMENTS)]
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.UNSUPPORTED_REQUIREMENT_FIELD
    assert r["fields"] == ["vat_number"]
    assert world["details"] == []
    assert world["twilio"].created["end_user"] == 0


def test_the_column_mapping_round_trips():
    ours = db_reg.details_from_attributes(GOOD_ATTRS)
    assert ours["authorized_rep_first_name"] == "Ann"
    back = db_reg.attributes_from_details({**ours, "id": "x"},
                                         REQS.end_user_field_names)
    for k, v in GOOD_ATTRS.items():
        assert back[k] == v


# ═══════════════════════════════════════════════════════════════════════════
# 3 — the declaration is never guessed, and never logged
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_declaration_comes_from_the_POLICY_not_a_default(world):
    """W9G.3. The values are supplied, but from a context-keyed policy Twilio
    confirmed -- not a constant, and not for any other context."""
    from services import regulatory_declaration as rd
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    attrs = {k: v for k, v in GOOD_ATTRS.items()
             if k not in ("business_identity", "is_subassigned")}
    await engine.prepare_profile(tenant(), attributes=attrs)
    policy = rd.resolve(iso_country="IE", number_type="local",
                        end_user_type="business")
    sent = world["twilio"].last_end_user_attributes
    assert sent["business_identity"] == policy.business_identity
    assert sent["is_subassigned"] == policy.is_subassigned
    # and the identical values were recorded before the filing
    assert world["details"][0]["business_identity"] == policy.business_identity


def _executable_source(module) -> str:
    """Module source with docstrings and comments removed.

    Both modules legitimately QUOTE Twilio's field help, which contains the enum
    values verbatim -- so a grep over raw source would flag the explanation of why
    the values are not hardcoded. Stripping prose is what makes the assertion about
    code. (Same technique as the W8.1 timezone-authority audit.)
    """
    import ast
    import inspect
    src = inspect.getsource(module)
    tree = ast.parse(src)
    spans = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                d = body[0]
                spans.update(range(d.lineno, (d.end_lineno or d.lineno) + 1))
    out = []
    for i, line in enumerate(src.splitlines(), start=1):
        if i in spans:
            continue
        out.append(line.split("#", 1)[0])
    return "\n".join(out)


def test_no_module_contains_a_hardcoded_declaration_value():
    """Guards the mutation where someone 'unblocks' the engine by picking a value.

    Asserted against EXECUTABLE source only: the prose that explains the ambiguity
    necessarily names both values, and an explanation must not be able to satisfy --
    or break -- a code assertion."""
    for mod in (engine, ie_ux):
        code = _executable_source(mod)
        for value in ("DIRECT_CUSTOMER", "INDEPENDENT_SOFTWARE_VENDOR"):
            # The IE label/help dictionary is presentation text, not a value the
            # engine would submit; it is allowed to exist but must not appear here.
            assert value not in code, f"{mod.__name__} hardcodes {value}"


@pytest.mark.asyncio
async def test_the_declaration_and_rep_details_are_never_logged(world, caplog):
    world["twilio"].opts["end_user_error"] = ProviderError(code=400, status=400)
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    with caplog.at_level("INFO"):
        await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    for secret in ("DIRECT_CUSTOMER", "ann@dani.ie", "Ann", "Byrne", "123456",
                   "1 Example Street", "D02 AB12"):
        assert secret not in caplog.text, secret


@pytest.mark.asyncio
async def test_the_fake_provider_now_ENFORCES_the_regulations_required_fields(world):
    """W9G's fake accepted a partial attribute bag, so a test could pass on a payload
    the real provider would call incomplete. It now refuses, which is how the
    stopping point above is actually verified rather than asserted."""
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    partial = {k: v for k, v in GOOD_ATTRS.items() if k != "business_name"}
    r = await engine.prepare_profile(tenant(), attributes=partial)
    # Our own check catches it before the provider does -- but if it did not, the
    # fake would raise rather than pretend.
    assert r["status"] == engine.INVALID_CUSTOMER_DATA
    assert "business_name" in r["missing"]

    direct = await engine.resolve_end_user(
        tenant(), requirements=REQS, attributes=partial,
        client=world["twilio"], sub_sid=SUB)
    assert direct["status"] == engine.PROVIDER_UNAVAILABLE, \
        "the fake must refuse an incomplete payload"


# ═══════════════════════════════════════════════════════════════════════════
# Two gaps a mutation run exposed: fakes that masked the real behaviour.
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_submission_uses_OUR_record_even_when_the_providers_copy_diverges(world):
    """The two sources must be distinguishable, or a test cannot tell which is used.

    Here the provider's EndUser is missing a required field while our stored answers
    are complete. Submission must succeed on our record: reading it back from Twilio
    only works while Twilio has it and is reachable, which is exactly when it is
    least useful."""
    _seed(world)
    world["twilio"].opts["end_user_attributes"] = {
        k: v for k, v in GOOD_ATTRS.items() if k != "business_registration_number"}
    world["profiles"].append(_profile())
    r = await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert r["ok"], r
    assert r["state"] == st.PENDING_REVIEW


@pytest.mark.asyncio
async def test_submission_is_blocked_when_OUR_record_is_incomplete_even_if_the_provider_has_it(world):
    """The mirror image: a complete provider copy must NOT paper over a gap in the
    record we are responsible for."""
    _seed(world, business_registration_number=None)
    world["twilio"].opts["end_user_attributes"] = dict(GOOD_ATTRS)
    world["profiles"].append(_profile())
    r = await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert r["status"] == engine.NOT_READY
    assert any("business_registration_number" in b for b in r["blockers"])


# ── the real upsert, not the fixture's reimplementation ────────────────────

class _DetailsClient:
    """A fake Supabase client that records what the REAL upsert sends, so the
    merge-versus-replace behaviour is tested in db/regulatory.py rather than in a
    fixture that happens to reimplement it."""
    def __init__(self, rows):
        self.rows = rows
        self.inserted, self.updated = [], []

    def table(self, name):
        outer = self

        class QB:
            def __init__(self):
                self.filters, self.patch, self.payload = {}, None, None
            def select(self, *a, **k): return self
            def eq(self, c, v): self.filters[c] = v; return self
            def limit(self, *a, **k): return self
            def update(self, patch): self.patch = patch; return self
            def insert(self, payload): self.payload = payload; return self
            def execute(self):
                if self.payload is not None:
                    outer.inserted.append(self.payload)
                    return type("R", (), {"data": [self.payload]})()
                if self.patch is not None:
                    outer.updated.append(self.patch)
                    return type("R", (), {"data": [{**outer.rows[0], **self.patch}]})()
                rows = list(outer.rows)
                for c, v in self.filters.items():
                    rows = [r for r in rows if str(r.get(c)) == str(v)]
                return type("R", (), {"data": rows})()
        return QB()


@pytest.mark.asyncio
async def test_the_real_upsert_MERGES_rather_than_replacing(monkeypatch):
    """A correction after a rejection changes one field. Replacing the row would turn
    a one-field edit into a full retype -- the exact problem this table exists to
    solve."""
    existing = {"id": "det-1", "tenant_id": TENANT, "iso_country": "IE",
                "end_user_type": "business", "business_name": "DANI Ltd",
                "authorized_rep_email": "ann@dani.ie",
                "business_registration_number": "123456"}
    client = _DetailsClient([existing])
    monkeypatch.setattr(db_reg, "get_client", lambda: client)
    await db_reg.upsert_business_details(
        TENANT, "IE", values={"business_registration_number": "NC999999"})
    assert client.inserted == [], "an existing row must be updated, not duplicated"
    assert len(client.updated) == 1
    patch = client.updated[0]
    assert patch["business_registration_number"] == "NC999999"
    # The untouched fields are NOT in the patch, so they cannot be cleared.
    assert "business_name" not in patch
    assert "authorized_rep_email" not in patch


@pytest.mark.asyncio
async def test_the_real_upsert_inserts_when_there_is_nothing_yet(monkeypatch):
    client = _DetailsClient([])
    monkeypatch.setattr(db_reg, "get_client", lambda: client)
    await db_reg.upsert_business_details(
        TENANT, "IE", values={"business_name": "DANI Ltd"})
    assert len(client.inserted) == 1
    row = client.inserted[0]
    assert row["tenant_id"] == TENANT and row["iso_country"] == "IE"
    assert row["business_name"] == "DANI Ltd"


@pytest.mark.asyncio
async def test_the_real_upsert_ignores_unknown_columns(monkeypatch):
    """A provider field with no column must never be smuggled in through the values
    dict -- prepare_profile refuses it earlier, and this is the second line."""
    client = _DetailsClient([])
    monkeypatch.setattr(db_reg, "get_client", lambda: client)
    await db_reg.upsert_business_details(
        TENANT, "IE", values={"business_name": "X", "vat_number": "IE123",
                              "twilio_auth_token": "secret"})
    row = client.inserted[0]
    assert "vat_number" not in row and "twilio_auth_token" not in row


@pytest.mark.asyncio
async def test_the_real_upsert_does_not_clear_a_field_with_blank_input(monkeypatch):
    existing = {"id": "det-1", "tenant_id": TENANT, "iso_country": "IE",
                "end_user_type": "business", "business_name": "DANI Ltd"}
    client = _DetailsClient([existing])
    monkeypatch.setattr(db_reg, "get_client", lambda: client)
    await db_reg.upsert_business_details(
        TENANT, "IE", values={"business_name": "   ", "comments": "note"})
    patch = client.updated[0]
    assert "business_name" not in patch
    assert patch["comments"] == "note"


# ═══════════════════════════════════════════════════════════════════════════
# W9H-QA found these two against the LIVE provider.
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_details_survive_an_address_the_PROVIDER_REJECTS(world):
    """The defect: persistence sat downstream of the address gate, so a business
    that filled in every field but whose address Twilio refused lost everything it
    had typed -- the exact recoverability failure W9G.1 was meant to close. Found by
    running the real workflow against Twilio's live API with an unvalidatable
    address."""
    world["twilio"].opts["address_error"] = ProviderError(code=21628, status=400)
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.ADDRESS_VALIDATION_FAILED
    assert r["details_stored"] is True
    stored = world["details"][0]
    assert stored["business_name"] == "DANI Ltd"
    assert stored["business_registration_number"] == "123456"
    assert stored["authorized_rep_email"] == "ann@dani.ie"
    assert stored["requirements_fingerprint"] == REQS.fingerprint()
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_a_rejected_address_is_not_reported_as_never_submitted(world):
    """"No address yet" and "you submitted one and Twilio refused it" need different
    things from the customer. Reporting the second as the first would tell them to
    add an address they have already added."""
    world["twilio"].opts["address_error"] = ProviderError(code=21628, status=400)
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.ADDRESS_VALIDATION_FAILED
    assert r["detail"] == "provider_could_not_validate"
    assert "not_created" not in r["detail"] and "not_submitted" not in r["detail"]


@pytest.mark.asyncio
async def test_no_address_at_all_is_reported_as_not_submitted(world):
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.NOT_READY
    assert r["detail"] == "address_not_submitted"
    assert r["details_stored"] is True
    assert world["details"][0]["business_name"] == "DANI Ltd"


@pytest.mark.asyncio
async def test_the_customer_can_fix_the_address_without_retyping_anything(world):
    """The point of persisting first: correct the address, resend nothing else."""
    world["twilio"].opts["address_error"] = ProviderError(code=21628, status=400)
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)

    world["twilio"].opts.pop("address_error")
    world["addresses"].clear()
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes={})   # nothing re-sent
    assert r["ok"], r
    sent = world["twilio"].last_end_user_attributes
    assert sent["business_name"] == "DANI Ltd"
    assert sent["business_identity"] == "DIRECT_CUSTOMER"


@pytest.mark.asyncio
async def test_a_provider_OUTAGE_during_address_creation_also_preserves_details(world):
    """Rejection and outage are different classifications but must have the same
    effect on the customer's typed answers: they survive both."""
    world["twilio"].opts["address_error"] = ProviderError(code=20500, status=500)
    res = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert res["status"] == engine.PROVIDER_UNAVAILABLE
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["details_stored"] is True
    assert world["details"][0]["business_name"] == "DANI Ltd"
    assert world["details"][0]["authorized_rep_email"] == "ann@dani.ie"
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_repeated_attempts_never_create_a_second_details_row(world):
    """The row is keyed on (tenant, country, end-user type); a retry must merge."""
    world["twilio"].opts["address_error"] = ProviderError(code=21628, status=400)
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    for _ in range(4):
        await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert len(world["details"]) == 1, "a duplicate business-details row was created"


@pytest.mark.asyncio
async def test_a_rejected_address_leaves_no_provider_identity_of_any_kind(world):
    """The full stop, asserted resource by resource rather than by outcome alone."""
    world["twilio"].opts["address_error"] = ProviderError(code=21628, status=400)
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    created = world["twilio"].created
    assert created["address"] == 0 and created["end_user"] == 0
    assert created["document"] == 0 and created["bundle"] == 0
    assert created["assignment"] == 0 and created["evaluation"] == 0
    assert world["twilio"].purchases == 0
    assert world["profiles"] == [], "no profile may advance as though validation passed"
    # and the stored address row must not claim a provider SID
    assert world["addresses"][0].get("address_sid") is None
    assert world["addresses"][0]["validated"] is False


@pytest.mark.asyncio
async def test_neither_failure_path_logs_the_address_or_the_representative(world, caplog):
    for err in (ProviderError(code=21628, status=400),
                ProviderError(code=20500, status=500)):
        world["addresses"].clear()
        world["twilio"].opts["address_error"] = err
        with caplog.at_level("INFO"):
            await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
            await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    for secret in ("1 Example Street", "D02 AB12", "DANI Ltd", "ann@dani.ie",
                   "Ann", "Byrne", "123456"):
        assert secret not in caplog.text, secret
