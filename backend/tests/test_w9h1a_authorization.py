"""W9H.1A — the authorisation model.

An authorisation is an auditable customer EVENT, scoped to one premises. The tests
below are mostly about two things the old design could not do: hold Limerick and
Cork at the same time, and keep history when the facts change.
"""
import inspect
import pytest

from db import regulatory as db_reg
from services import regulatory_authorization as auth
from services import regulatory_engine as engine
from tests.test_w9g_engine import (ADDR_SID, GOOD_ADDRESS, GOOD_ATTRS, SUB, TENANT,
                                   ProviderError, authorize, prepared, tenant,
                                   world)  # noqa: F401


# ── golden vectors (mandatory) ─────────────────────────────────────────────
# These pin the DIGEST ITSELF, not merely the code that computes it. A future
# Python, a different unicodedata, a reordered FIELDS tuple or an "improved"
# normalisation rule would all change these numbers -- and silently invalidate
# every authorisation ever recorded, because a stored digest would stop matching
# facts that had not changed. If one of these fails, the scheme changed: bump
# auth.SCHEME rather than editing the expected value.

EMPTY_VECTOR = "8ebb0d0cb8668b32e9cc7381e2fa616bbb9b3dfee07ce2c34658c7a863122733"

FULL_FACTS = {
    "business_name": "DANI Ltd",
    "business_registration_number": "123456",
    "business_website": "https://dani.ie",
    "authorized_rep_first_name": "Ann",
    "authorized_rep_last_name": "Murphy",
    "authorized_rep_email": "Ann@Dani.ie",
    "address_street": "20 Thomas St",
    "address_street_secondary": "Prior's-Land",
    "address_city": "Limerick",
    "address_region": "Limerick",
    "address_postal_code": "V94 HT0X",
    "address_iso_country": "IE",
}


def test_the_canonical_payload_is_exactly_what_we_think_it_is():
    payload = auth.canonical_payload(FULL_FACTS)
    parts = payload.split(auth.SEP)
    assert parts[0] == "openlines.authorization.v1"
    assert len(parts) == 1 + len(auth.FIELDS)
    assert parts[1] == "business_name=dani ltd"
    assert parts[6] == "authorized_rep_email=ann@dani.ie"     # casefolded
    assert parts[11] == "address_postal_code=V94HT0X"         # upper, no space
    assert parts[12] == "address_iso_country=IE"


def test_golden_vector_for_the_full_fact_set():
    assert auth.fingerprint(FULL_FACTS) == (
        "dee0b2336028ba62e9cb0c755d79e738503a582f34082742457fbe3003dc5d77"
    )


def test_golden_vector_for_an_entirely_empty_fact_set():
    assert auth.fingerprint({}) == EMPTY_VECTOR


@pytest.mark.parametrize("variant", [
    {"business_name": "  DANI   Ltd  "},          # whitespace collapse + trim
    {"business_name": "dani ltd"},                # case
    {"address_postal_code": "v94ht0x"},           # Eircode spacing + case
    {"address_iso_country": "ie"},                # ISO case
    {"authorized_rep_email": "ANN@DANI.IE"},      # email case
])
def test_normalisation_makes_equivalent_facts_produce_one_digest(variant):
    assert auth.fingerprint({**FULL_FACTS, **variant}) == auth.fingerprint(FULL_FACTS)


def test_null_and_empty_string_canonicalise_identically():
    a = auth.fingerprint({**FULL_FACTS, "address_street_secondary": None})
    b = auth.fingerprint({**FULL_FACTS, "address_street_secondary": ""})
    c = auth.fingerprint({**FULL_FACTS, "address_street_secondary": "   "})
    assert a == b == c


def test_a_value_shifting_between_fields_cannot_collide():
    """The separator exists for this: "ab"+"" must not serialise like ""+"ab"."""
    x = auth.fingerprint({"business_name": "ab", "business_registration_number": ""})
    y = auth.fingerprint({"business_name": "a", "business_registration_number": "b"})
    assert x != y


def test_the_scheme_is_versioned_and_inside_the_digest():
    """Bumping SCHEME must change every digest, so a rule change cannot leave old
    stored digests silently matching facts computed under new rules."""
    before = auth.fingerprint(FULL_FACTS)
    original = auth.SCHEME
    try:
        auth.SCHEME = "openlines.authorization.v2"
        after = auth.fingerprint(FULL_FACTS)
    finally:
        auth.SCHEME = original
    assert after != before
    assert auth.fingerprint(FULL_FACTS) == before, "the scheme must be restorable"


def test_there_is_exactly_one_fingerprint_implementation():
    """A second copy in a router or repository would be a second definition of what
    the customer agreed to, and the two would drift."""
    import pathlib
    root = pathlib.Path(engine.__file__).parent.parent
    offenders = []
    for f in list(root.glob("services/*.py")) + list(root.glob("db/*.py")) + \
             list(root.glob("routers/*.py")):
        if f.name == "regulatory_authorization.py":
            continue
        body = f.read_text()
        if "openlines.authorization" in body:
            offenders.append(f.name)
    assert not offenders, f"a second authorisation digest lives in {offenders}"


# ── which facts count ──────────────────────────────────────────────────────

@pytest.mark.parametrize("field", [
    "business_name", "business_registration_number", "business_website",
    "authorized_rep_first_name", "authorized_rep_last_name", "authorized_rep_email",
    "address_street", "address_city", "address_region", "address_postal_code",
    "address_iso_country",
])
def test_changing_any_authorised_fact_changes_the_digest(field):
    changed = {**FULL_FACTS, field: "something else"}
    assert auth.fingerprint(changed) != auth.fingerprint(FULL_FACTS)


@pytest.mark.parametrize("noise", [
    {"comments": "an internal note"},
    {"business_identity": "INDEPENDENT_SOFTWARE_VENDOR"},
    {"is_subassigned": "YES"},
    {"requirements_fingerprint": "f" * 64},
    {"address_sid": "ADsomethingelse"},
    {"bundle_sid": "BUsomethingelse"},
    {"provider_account_sid": "ACsomethingelse"},
])
def test_system_and_provider_values_never_affect_the_digest(noise):
    assert auth.fingerprint({**FULL_FACTS, **noise}) == auth.fingerprint(FULL_FACTS)


def test_the_address_facts_really_are_inside_the_digest():
    limerick = auth.facts_from({"business_name": "DANI Ltd"},
                               {"city": "Limerick", "postal_code": "V94 HT0X",
                                "iso_country": "IE"})
    cork = auth.facts_from({"business_name": "DANI Ltd"},
                           {"city": "Cork", "postal_code": "T12 XY34",
                            "iso_country": "IE"})
    assert auth.fingerprint(limerick) != auth.fingerprint(cork)


# ── multi-location: the reason this design exists ──────────────────────────

def _address(world, rid, city, postal, loc=None):
    row = {"id": rid, "tenant_id": TENANT, "iso_country": "IE", "validated": True,
           "address_sid": f"AD{rid}", "provider_account_sid": SUB,
           "tenant_location_id": loc, "city": city, "postal_code": postal,
           "street": f"1 {city} St", "region": city}
    world["addresses"].append(row)
    return row


async def _authorize(world, address, who="A Representative"):
    details = {"business_name": "DANI Ltd"}
    world["details"][:] = [{"id": "det-1", "tenant_id": TENANT, "iso_country": "IE",
                            "end_user_type": "business", **details}]
    r = await engine.record_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=address,
        details=details, authorized_by=who, authorization_method="dashboard")
    assert r["ok"], r
    return r


@pytest.mark.asyncio
async def test_limerick_and_cork_can_be_authorised_at_the_same_time(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X", loc="loc-1")
    cork = _address(world, "a-cork", "Cork", "T12 XY34", loc="loc-2")
    a = await _authorize(world, lim)
    b = await _authorize(world, cork)
    assert a["authorization"]["id"] != b["authorization"]["id"]
    active = [x for x in world["authorizations"]
              if x["authorization_revoked_at"] is None]
    assert len(active) == 2, "the old design could hold only one"


@pytest.mark.asyncio
async def test_dublin_can_coexist_with_both(world):
    for rid, city, pc, loc in (("a-lim", "Limerick", "V94 HT0X", "loc-1"),
                               ("a-cork", "Cork", "T12 XY34", "loc-2"),
                               ("a-dub", "Dublin", "D02 AF30", "loc-3")):
        await _authorize(world, _address(world, rid, city, pc, loc))
    assert len([x for x in world["authorizations"]
                if x["authorization_revoked_at"] is None]) == 3


@pytest.mark.asyncio
async def test_authorising_cork_does_not_touch_limerick(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X", loc="loc-1")
    first = (await _authorize(world, lim))["authorization"]
    before = dict(first)
    await _authorize(world, _address(world, "a-cork", "Cork", "T12 XY34", loc="loc-2"))
    assert first == before, "Limerick's authorisation was modified"
    assert first["authorization_revoked_at"] is None


@pytest.mark.asyncio
async def test_an_authorisation_for_one_address_does_not_cover_another(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X", loc="loc-1")
    cork = _address(world, "a-cork", "Cork", "T12 XY34", loc="loc-2")
    await _authorize(world, lim)
    r = await engine.check_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=cork,
        details={"business_name": "DANI Ltd"})
    assert r["status"] == engine.AUTHORIZATION_WRONG_SCOPE


@pytest.mark.asyncio
async def test_different_addresses_produce_different_authorisation_scope(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X", loc="loc-1")
    cork = _address(world, "a-cork", "Cork", "T12 XY34", loc="loc-2")
    a = (await _authorize(world, lim))["authorization"]
    b = (await _authorize(world, cork))["authorization"]
    assert a["tenant_regulatory_address_id"] != b["tenant_regulatory_address_id"]
    assert a["authorized_details_fingerprint"] != b["authorized_details_fingerprint"]
    assert a["authorized_address_city"] == "Limerick"
    assert b["authorized_address_city"] == "Cork"


# ── idempotency and history ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authorising_the_same_facts_twice_is_idempotent(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    a = await _authorize(world, lim)
    b = await _authorize(world, lim)
    assert a["created"] is True and b["created"] is False
    assert a["authorization"]["id"] == b["authorization"]["id"]
    assert len(world["authorizations"]) == 1


@pytest.mark.asyncio
async def test_two_concurrent_identical_authorisations_record_one_row(world):
    import asyncio
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    world["details"][:] = [{"id": "det-1", "tenant_id": TENANT, "iso_country": "IE",
                            "end_user_type": "business", "business_name": "DANI Ltd"}]
    kw = dict(iso_country="IE", end_user_type="business", address_row=lim,
              details={"business_name": "DANI Ltd"},
              authorization_method="dashboard")
    a, b = await asyncio.gather(
        engine.record_authorization(TENANT, authorized_by="Rep", **kw),
        engine.record_authorization(TENANT, authorized_by="Rep", **kw))
    assert a["ok"] and b["ok"]
    assert len(world["authorizations"]) == 1
    assert a["authorization"]["id"] == b["authorization"]["id"]


@pytest.mark.asyncio
async def test_a_revoked_authorisation_stays_queryable_and_a_new_one_can_be_made(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    v1 = (await _authorize(world, lim, who="First Rep"))["authorization"]
    await db_reg.revoke_authorization(TENANT, v1["id"])
    v2 = (await _authorize(world, lim, who="Second Rep"))["authorization"]

    history = await db_reg.list_authorizations(TENANT, "IE", lim["id"])
    assert len(history) == 2, "history must survive"
    assert v1["authorized_by"] == "First Rep"
    assert v1["authorization_revoked_at"] is not None
    assert v1["authorized_at"], "authorized_at must never be erased"
    assert v2["authorization_revoked_at"] is None


@pytest.mark.asyncio
async def test_revoking_twice_does_not_rewrite_the_first_revocation(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    a = (await _authorize(world, lim))["authorization"]
    first = await db_reg.revoke_authorization(TENANT, a["id"])
    stamp = first["authorization_revoked_at"]
    again = await db_reg.revoke_authorization(TENANT, a["id"])
    assert again is None, "a second revocation must be a no-op"
    assert a["authorization_revoked_at"] == stamp


def test_the_repository_exposes_no_generic_update():
    names = [n for n in dir(db_reg) if "authorization" in n]
    assert "revoke_authorization" in names
    assert not any(n.startswith("update_authorization") for n in names), \
        "the only permitted mutation is revoke"


# ── the gates ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_authorisation_blocks_the_first_provider_identity(world):
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.AUTHORIZATION_NOT_RECORDED
    assert world["twilio"].created["end_user"] == 0
    assert world["twilio"].created["bundle"] == 0
    assert world["details"], "the typed answers must still be persisted"


@pytest.mark.asyncio
async def test_a_revoked_authorisation_blocks_the_first_provider_identity(world):
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    a = await authorize(world)
    await db_reg.revoke_authorization(TENANT, a["id"])
    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["status"] == engine.AUTHORIZATION_REVOKED
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_a_revoked_authorisation_blocks_submission(world):
    from services import regulatory_state as st
    r = await prepared(world)
    assert r["ok"], r
    profile = world["profiles"][0]
    profile.update({"state": st.READY_TO_SUBMIT, "evaluation_status": "compliant"})
    a = world["authorizations"][0]
    await db_reg.revoke_authorization(TENANT, a["id"])

    out = await engine.submit_profile(tenant(), profile=profile)
    assert out["status"] == engine.AUTHORIZATION_REVOKED
    assert profile["state"] == st.READY_TO_SUBMIT, "it must not have been submitted"


@pytest.mark.asyncio
async def test_a_revocation_after_submission_is_recorded_and_does_not_undo_it(world):
    from services import regulatory_state as st
    r = await prepared(world)
    profile = world["profiles"][0]
    profile.update({"state": st.READY_TO_SUBMIT, "evaluation_status": "compliant"})
    assert (await engine.submit_profile(tenant(), profile=profile))["ok"]
    assert profile["state"] == st.PENDING_REVIEW and profile["submitted_at"]

    a = world["authorizations"][0]
    await db_reg.revoke_authorization(TENANT, a["id"])

    # The filing is NOT rewritten, and the link to what it was made under survives.
    assert profile["state"] == st.PENDING_REVIEW
    assert profile["submitted_at"]
    assert profile["authorization_id"] == a["id"]
    assert a["authorized_at"], "authorized_at must survive revocation"
    # and whether the revocation came after submission is derivable
    assert a["authorization_revoked_at"] is not None and profile["submitted_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("business_name", "DANI Trading Ltd"),
    ("business_registration_number", "NC999999"),
    ("business_website", "https://dani.example"),
    ("authorized_rep_first_name", "Brendan"),
    ("authorized_rep_last_name", "O'Neill"),
    ("authorized_rep_email", "brendan@dani.ie"),
])
async def test_changing_an_authorised_fact_makes_the_authorisation_stale(world, field, value):
    r = await prepared(world)
    assert r["ok"], r
    out = await engine.prepare_profile(tenant(), attributes={
        {"authorized_rep_first_name": "first_name",
         "authorized_rep_last_name": "last_name",
         "authorized_rep_email": "email"}.get(field, field): value})
    assert out["status"] == engine.AUTHORIZATION_STALE


@pytest.mark.asyncio
async def test_changing_the_eircode_invalidates_the_authorisation(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    await _authorize(world, lim)
    moved = {**lim, "postal_code": "V94 AAAA"}
    r = await engine.check_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=moved,
        details={"business_name": "DANI Ltd"})
    assert r["status"] == engine.AUTHORIZATION_STALE


@pytest.mark.asyncio
async def test_comments_do_not_invalidate_an_authorisation(world):
    r = await prepared(world)
    assert r["ok"], r
    out = await engine.prepare_profile(tenant(), attributes={"comments": "a note"})
    assert out["ok"], out


@pytest.mark.asyncio
async def test_a_changed_requirements_fingerprint_does_not_invalidate_it(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    await _authorize(world, lim)
    details = {"business_name": "DANI Ltd", "requirements_fingerprint": "f" * 64}
    r = await engine.check_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=lim,
        details=details)
    assert r["ok"], "Twilio changing its form is not a customer withdrawing consent"


# ── the fingerprint is never the customer's to supply ──────────────────────

@pytest.mark.asyncio
async def test_the_fingerprint_is_computed_server_side(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    r = await _authorize(world, lim)
    expected = auth.fingerprint_for({"business_name": "DANI Ltd"}, lim)
    assert r["authorization"]["authorized_details_fingerprint"] == expected


def test_record_authorization_accepts_no_caller_supplied_fingerprint():
    params = inspect.signature(engine.record_authorization).parameters
    assert "authorized_details_fingerprint" not in params
    assert "fingerprint" not in params


def test_check_authorization_accepts_no_caller_supplied_fingerprint():
    params = inspect.signature(engine.check_authorization).parameters
    assert "fingerprint" not in params


@pytest.mark.asyncio
async def test_a_customer_cannot_inject_declaration_values_through_authorisation(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    hostile = {"business_name": "DANI Ltd",
               "business_identity": "INDEPENDENT_SOFTWARE_VENDOR",
               "is_subassigned": "YES"}
    r = await engine.record_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=lim,
        details=hostile, authorized_by="Rep", authorization_method="dashboard")
    row = r["authorization"]
    assert "business_identity" not in row
    assert "is_subassigned" not in row
    # and the injected values did not move the digest
    assert row["authorized_details_fingerprint"] == \
        auth.fingerprint_for({"business_name": "DANI Ltd"}, lim)


@pytest.mark.asyncio
async def test_an_invented_authorisation_method_is_refused(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    r = await engine.record_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=lim,
        details={}, authorized_by="Rep", authorization_method="sms")
    assert r["status"] == engine.INVALID_CUSTOMER_DATA


@pytest.mark.asyncio
async def test_an_authorisation_attributed_to_nobody_is_refused(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    r = await engine.record_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=lim,
        details={}, authorized_by="   ", authorization_method="dashboard")
    assert r["status"] == engine.INVALID_CUSTOMER_DATA


# ── linkage and blast radius ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_profile_records_the_exact_authorisation_it_relied_on(world):
    r = await prepared(world)
    assert r["ok"], r
    profile = world["profiles"][0]
    assert profile["authorization_id"] == world["authorizations"][0]["id"]


@pytest.mark.asyncio
async def test_a_later_authorisation_does_not_rewrite_a_filings_link(world):
    r = await prepared(world)
    profile = world["profiles"][0]
    original = profile["authorization_id"]
    second = await db_reg.insert_authorization({
        "tenant_id": TENANT, "iso_country": "IE", "end_user_type": "business",
        "tenant_regulatory_address_id": "addr-1",
        "authorized_details_fingerprint": "c" * 64, "authorized_by": "Someone Else",
        "authorization_method": "phone", "authorized_at": "2026-10-01T00:00:00Z",
        "authorized_address_city": "Dublin", "authorized_address_postal_code": None})
    assert await db_reg.attach_profile_authorization(profile["id"], second["id"]) is None
    assert profile["authorization_id"] == original


@pytest.mark.asyncio
async def test_recording_an_authorisation_touches_no_provider(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    await _authorize(world, lim)
    tw = world["twilio"]
    assert tw.created["address"] == 0 and tw.created["end_user"] == 0
    assert tw.created["document"] == 0 and tw.created["bundle"] == 0
    assert tw.purchases == 0


def test_no_authorisation_code_runs_at_import_or_startup():
    import pathlib
    src = pathlib.Path(auth.__file__).read_text()
    tree = __import__("ast").parse(src)
    import ast as _ast
    for node in tree.body:
        assert isinstance(node, (_ast.Import, _ast.ImportFrom, _ast.FunctionDef,
                                 _ast.AsyncFunctionDef, _ast.ClassDef, _ast.Assign,
                                 _ast.AnnAssign, _ast.Expr)), \
            f"module-level side effect: {type(node).__name__}"


# ── the REAL data layer ────────────────────────────────────────────────────
# Everything above runs against fakes, which is what makes the engine testable --
# but it also means a mutation inside db/regulatory.py changes nothing those tests
# can see. Mutation testing found exactly that hole: dropping the revocation
# filter, the address filter, the write-once fence and the duplicate catch all
# survived a green suite. These bind the real predicates, and the same invariants
# are proved again against real PostgreSQL in backend/scripts/verify_027/stage_j.py.

def _src(fn):
    """Source with the docstring removed, so prose cannot satisfy an assertion.

    Dedented: a test running under the `world` fixture may read a function the
    fixture has replaced with a nested def, which would otherwise fail to parse.
    """
    import ast, textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)):
        node.body = node.body[1:]
    return ast.unparse(tree)


def test_the_real_lookup_excludes_revoked_authorizations():
    body = _src(db_reg.find_active_authorization)
    assert "'authorization_revoked_at', 'null'" in body.replace('"', "'"), \
        "a revoked authorisation must never be returned as active"


def test_the_real_lookup_is_scoped_to_one_address():
    body = _src(db_reg.find_active_authorization)
    assert "tenant_regulatory_address_id" in body, \
        "authorising Limerick must not authorise Cork"
    assert "tenant_id" in body and "iso_country" in body and "end_user_type" in body


def test_the_real_profile_link_is_write_once():
    body = _src(db_reg.attach_profile_authorization).replace('"', "'")
    assert "'authorization_id', 'null'" in body, \
        "a submitted filing's authorisation link must never be rewritten"
    assert "len(res.data or []) == 1" in body


def test_the_real_insert_catches_the_duplicate_and_returns_none():
    body = _src(db_reg.insert_authorization)
    assert "_is_unique_violation" in body and "return None" in body, \
        "two identical concurrent authorisations must collapse, not raise"


def test_the_real_revoke_is_fenced_and_never_touches_authorized_at():
    body = _src(db_reg.revoke_authorization).replace('"', "'")
    assert "'authorization_revoked_at', 'null'" in body, "revocation must be fenced"
    assert "authorized_at" not in body, "revocation must never rewrite authorized_at"


def test_the_real_insert_writes_only_the_declared_columns():
    body = _src(db_reg.insert_authorization)
    assert "AUTHORIZATION_COLUMNS" in body, \
        "a caller-supplied key must not be able to reach the table"
    for forbidden in ("business_identity", "is_subassigned"):
        assert forbidden not in db_reg.AUTHORIZATION_COLUMNS


@pytest.mark.asyncio
async def test_a_caller_supplied_fingerprint_in_the_details_is_ignored(world):
    """The hostile case: a client puts a digest where the facts go, hoping it is
    stored verbatim and later matched."""
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    hostile = {"business_name": "DANI Ltd",
               "authorized_details_fingerprint": "d" * 64}
    r = await engine.record_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=lim,
        details=hostile, authorized_by="Rep", authorization_method="dashboard")
    stored = r["authorization"]["authorized_details_fingerprint"]
    assert stored != "d" * 64, "a caller-supplied digest was accepted"
    assert stored == auth.fingerprint_for({"business_name": "DANI Ltd"}, lim)


@pytest.mark.asyncio
async def test_the_gate_also_ignores_a_caller_supplied_fingerprint(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    await _authorize(world, lim)
    r = await engine.check_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=lim,
        details={"business_name": "SOMEONE ELSE Ltd",
                 "authorized_details_fingerprint":
                     auth.fingerprint_for({"business_name": "DANI Ltd"}, lim)})
    assert r["status"] == engine.AUTHORIZATION_STALE, \
        "the gate trusted a digest supplied alongside the facts"


# ══════════════════════════════════════════════════════════════════════════
# WHEN a customer consented is the server's to say (W9H.1B)
# ══════════════════════════════════════════════════════════════════════════
# An earlier draft accepted an optional authorized_at. Nothing was exploiting it,
# but the integrity of an audit record depended on every caller declining to pass
# one -- and the moment this reaches a route, a customer could backdate consent to
# before a filing, or forward-date it so it appears never to have been given. The
# capability is now absent rather than merely unused.


def _real_source(name):
    """The function as it exists ON DISK.

    inspect.getsource would return whatever the `world` fixture monkeypatched in,
    so an assertion about the real data layer would actually be reading a fake --
    the exact trap mutation testing caught twice in earlier gates.
    """
    import ast, pathlib
    src = (pathlib.Path(db_reg.__file__)).read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)):
                node.body = node.body[1:]
            return ast.unparse(node)
    raise AssertionError(f"{name} not found in db/regulatory.py")


def test_record_authorization_has_no_timestamp_parameter():
    params = inspect.signature(engine.record_authorization).parameters
    for forbidden in ("authorized_at", "timestamp", "when", "occurred_at"):
        assert forbidden not in params, f"{forbidden} is still accepted"


def test_the_repository_create_has_no_timestamp_override():
    assert "authorized_at" not in db_reg.AUTHORIZATION_COLUMNS, \
        "a caller could supply authorized_at through the repository"
    body = _real_source("insert_authorization")
    assert 'payload["authorized_at"] = _now_iso()' in body.replace("'", '"'), \
        "the repository must stamp the time itself"


@pytest.mark.asyncio
async def test_a_normal_authorisation_is_stamped_by_the_server(world):
    import datetime as dt
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    before = dt.datetime.now(dt.timezone.utc)
    r = await _authorize(world, lim)
    after = dt.datetime.now(dt.timezone.utc)
    stamped = dt.datetime.fromisoformat(r["authorization"]["authorized_at"])
    assert before <= stamped <= after, "authorized_at is not the server's clock"


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt,label", [
    ("1999-01-01T00:00:00+00:00", "backdated"),
    ("2999-01-01T00:00:00+00:00", "future-dated"),
])
async def test_a_caller_cannot_backdate_or_future_date_consent(world, attempt, label):
    """Passed through the details bag -- the only channel a caller controls."""
    import datetime as dt
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    hostile = {"business_name": "DANI Ltd", "authorized_at": attempt}
    r = await engine.record_authorization(
        TENANT, iso_country="IE", end_user_type="business", address_row=lim,
        details=hostile, authorized_by="Rep", authorization_method="dashboard")
    stamped = r["authorization"]["authorized_at"]
    assert stamped != attempt, f"a {label} timestamp was accepted"
    now = dt.datetime.now(dt.timezone.utc)
    assert abs((dt.datetime.fromisoformat(stamped) - now).total_seconds()) < 120


@pytest.mark.asyncio
async def test_a_timestamp_smuggled_into_the_repository_row_is_ignored(world):
    """Defence in depth: even a direct repository call cannot choose the time."""
    import datetime as dt
    row = await db_reg.insert_authorization({
        "tenant_id": TENANT, "iso_country": "IE", "end_user_type": "business",
        "tenant_regulatory_address_id": "a-x",
        "authorized_details_fingerprint": "a" * 64, "authorized_by": "Rep",
        "authorization_method": "dashboard",
        "authorized_at": "1999-01-01T00:00:00+00:00",
        "authorized_address_city": "Limerick", "authorized_address_postal_code": None})
    assert row["authorized_at"] != "1999-01-01T00:00:00+00:00"
    now = dt.datetime.now(dt.timezone.utc)
    assert abs((dt.datetime.fromisoformat(row["authorized_at"]) - now).total_seconds()) < 120


def test_no_historical_recording_path_exists_anywhere():
    """Historical consent (given by phone, entered later) is a real future need and
    is deliberately NOT built: it needs a privileged path that can say WHICH
    operator recorded it, and this repository's admin surface is one shared static
    API key with no per-operator identity. Inventing that to justify backdating
    would be the wrong order. Until then, no path accepts a timestamp."""
    import pathlib
    root = pathlib.Path(engine.__file__).parent.parent
    offenders = []
    for f in list(root.glob("services/*.py")) + list(root.glob("routers/*.py")) + \
             list(root.glob("db/*.py")):
        body = f.read_text()
        if "record_authorization" in body or "insert_authorization" in body:
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "authorized_at=" in stripped:
                    offenders.append((f.name, stripped[:70]))
    assert not offenders, f"a caller-supplied authorized_at survives in {offenders}"


@pytest.mark.asyncio
async def test_authorized_at_is_immutable_and_survives_revocation(world):
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    a = (await _authorize(world, lim))["authorization"]
    stamped = a["authorized_at"]
    await db_reg.revoke_authorization(TENANT, a["id"])
    assert a["authorized_at"] == stamped, "revocation altered authorized_at"
    assert a["authorization_revoked_at"] is not None
    assert "authorized_at" not in _real_source("revoke_authorization"), \
        "revoke must not touch authorized_at"


def test_no_route_exposes_authorisation_yet():
    """Stating the current contract rather than assuming it: authorisation has no
    HTTP surface, so there is nothing advertising a timestamp field. When a route
    is added, record_authorization cannot accept one."""
    import pathlib
    router = pathlib.Path(engine.__file__).parent.parent / "routers" / "regulatory.py"
    assert "record_authorization" not in router.read_text()


@pytest.mark.asyncio
async def test_the_engine_hands_the_repository_no_caller_timestamp(world):
    """Binds the ENGINE's own guarantee, not just the repository's.

    Both layers refuse a caller's timestamp, which is deliberate -- but it also
    means a regression in one is invisible while the other still holds. Mutation
    testing found exactly that: reinstating the override in the engine changed no
    observable behaviour because the repository overwrote it. This watches what the
    engine actually passes down.
    """
    lim = _address(world, "a-lim", "Limerick", "V94 HT0X")
    seen = {}
    real = engine.db_reg.insert_authorization

    async def spy(row):
        seen["row"] = dict(row)
        return await real(row)

    engine.db_reg.insert_authorization = spy
    try:
        await engine.record_authorization(
            TENANT, iso_country="IE", end_user_type="business", address_row=lim,
            details={"business_name": "DANI Ltd",
                     "authorized_at": "1999-01-01T00:00:00+00:00"},
            authorized_by="Rep", authorization_method="dashboard")
    finally:
        engine.db_reg.insert_authorization = real

    row = seen["row"]
    assert row.get("authorized_at") != "1999-01-01T00:00:00+00:00", \
        "the engine forwarded a caller-supplied timestamp to the repository"
    if "authorized_at" in row:
        import datetime as dt
        stamped = dt.datetime.fromisoformat(row["authorized_at"])
        now = dt.datetime.now(dt.timezone.utc)
        assert abs((stamped - now).total_seconds()) < 120, \
            "the engine sent a timestamp that is not the server clock"
