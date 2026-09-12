"""W9I-B — the onboarding lifecycle foundation.

Four properties this gate exists to establish, and each is asserted by running
the code rather than by reading it:

  1. a tenant exists BEFORE any provider is touched, so Ireland can rest
     un-numbered without being a broken tenant;
  2. a retry resumes the same tenant instead of minting another;
  3. an unsupported country is refused instead of quietly buying Canadian;
  4. every provisioned number lands in tenant_phone_numbers AND the legacy
     scalar, through one path, and only becomes routable once it is configured.
"""
import contextlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services import onboarding_lifecycle as lifecycle_ob
from services import phone_lifecycle as lifecycle
from services import phone_registry, telephony
from services.provisioning import provision_tenant

SUB = "AC_w9ib_sub"
TOK = "w9ib_token"
E164 = "+14165550111"
NUM_SID = "PN_w9ib"
ASSISTANT = "asst_w9ib"

BASE = {"business_name": "W9I-B Test Co", "industry": "realtor",
        "owner_name": "Owner", "website_url": "", "agent_name": "Alex"}


class World:
    """The DB as far as onboarding can see it, plus a record of provider calls."""

    def __init__(self):
        self.tenants: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.phones: list[dict] = []
        self.subaccounts = 0
        self.purchases = 0
        self.searches: list[str] = []


@contextlib.contextmanager
def world():
    w = World()

    async def insert_tenant(data):
        tid = str(uuid.uuid4())
        row = {**data, "id": tid}
        w.tenants[tid] = row
        if data.get("onboarding_key"):
            w.by_key[data["onboarding_key"]] = tid
        return row

    async def claim_onboarding_tenant(key, row):
        # Models the partial unique index: a second claim on one key loses.
        if key in w.by_key:
            return None
        return await insert_tenant({**row, "onboarding_key": key})

    async def find_onboarding_tenant(key):
        tid = w.by_key.get(key)
        return dict(w.tenants[tid]) if tid else None

    async def update_tenant(tid, patch):
        w.tenants.setdefault(tid, {"id": tid}).update(patch)
        return dict(w.tenants[tid])

    async def create_subaccount(name):
        w.subaccounts += 1
        return {"sid": SUB, "auth_token": TOK}

    async def find_available_number(sid, tok, cc, **kw):
        # A distinct number per search, because Twilio does not sell one number
        # twice -- a fake that did would make the ownership guard look like a bug.
        w.searches.append(cc)
        return E164 if not w.searches[:-1] else f"+1416555{1000 + len(w.searches):04d}"

    async def purchase_with_sid(sid, tok, num):
        w.purchases += 1
        return num, NUM_SID

    # the canonical layer, modelled on migration 027's own predicates
    async def find_owned_by_e164(e164):
        return next((r for r in w.phones
                     if r["e164"] == e164
                     and r["status"] in lifecycle.OWNED_E164_STATUSES), None)

    async def list_for_tenant(tid, **kw):
        return [r for r in w.phones if r["tenant_id"] == tid]

    async def insert_number(row):
        new = {**row, "id": str(uuid.uuid4())}
        w.phones.append(new)
        return new

    async def update_number(nid, patch):
        for r in w.phones:
            if r["id"] == nid:
                r.update(patch)
                return r
        return None

    stack = contextlib.ExitStack()
    for cm in (
        patch("db.supabase.insert_tenant", AsyncMock(side_effect=insert_tenant)),
        patch("db.supabase.claim_onboarding_tenant",
              AsyncMock(side_effect=claim_onboarding_tenant)),
        patch("db.supabase.find_onboarding_tenant",
              AsyncMock(side_effect=find_onboarding_tenant)),
        patch("db.supabase.update_tenant", AsyncMock(side_effect=update_tenant)),
        patch("services.telephony.create_subaccount",
              AsyncMock(side_effect=create_subaccount)),
        patch("services.telephony.find_available_number",
              AsyncMock(side_effect=find_available_number)),
        patch("services.telephony.purchase_number_with_sid",
              AsyncMock(side_effect=purchase_with_sid)),
        patch("services.telephony.close_subaccount", AsyncMock(return_value=True)),
        patch("services.telephony.release_number", AsyncMock(return_value=True)),
        patch("db.phone_numbers.find_owned_by_e164",
              AsyncMock(side_effect=find_owned_by_e164)),
        patch("db.phone_numbers.list_for_tenant", AsyncMock(side_effect=list_for_tenant)),
        patch("db.phone_numbers.insert_number", AsyncMock(side_effect=insert_number)),
        patch("db.phone_numbers.update_number", AsyncMock(side_effect=update_number)),
        patch("services.knowledge.scrape_website", AsyncMock(return_value="")),
        patch("services.knowledge.embed_and_store", AsyncMock(return_value=0)),
        patch("services.vapi.build_assistant_config", MagicMock(return_value={})),
        patch("services.vapi.create_assistant", AsyncMock(return_value=ASSISTANT)),
        patch("services.vapi.import_twilio_number", AsyncMock(return_value="vp_1")),
        patch("services.vapi.create_suborg", AsyncMock(return_value=None)),
    ):
        stack.enter_context(cm)
    with stack:
        yield w


# ══════════════════════════════════════════════════════════════════════════
# 1 — the tenant comes first
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_tenant_exists_before_any_provider_is_touched():
    """Asserted AT the moment the provider is called, not afterwards -- checking
    after the fact would pass even if the tenant were still created last."""
    seen = {}
    with world() as w:
        real = telephony.create_subaccount

        async def spy(name):
            seen["tenants_at_provider_time"] = len(w.tenants)
            return await real(name)

        with patch("services.telephony.create_subaccount", AsyncMock(side_effect=spy)):
            await provision_tenant({**BASE, "country": "CA"})
    assert seen["tenants_at_provider_time"] == 1, \
        "the tenant must already exist when the first provider call happens"


@pytest.mark.asyncio
async def test_a_ca_signup_completes_and_records_everything():
    with world() as w:
        out = await provision_tenant({**BASE, "country": "CA"})
    assert out["onboarding_state"] == lifecycle_ob.ACTIVE
    assert out["status"] == "live"
    assert out["phone_number"] == E164
    tenant = list(w.tenants.values())[0]
    assert tenant["business_country_code"] == "CA", \
        "the explicit signup country must become the compliance country"
    assert tenant["onboarding_state"] == lifecycle_ob.ACTIVE
    assert tenant["twilio_phone_number"] == E164, "the legacy scalar must be mirrored"
    assert len(w.phones) == 1, "the canonical row must exist"
    row = w.phones[0]
    assert row["purpose"] == lifecycle.PURPOSE_PERMANENT
    assert row["status"] == lifecycle.STATUS_ACTIVE
    assert row["e164"] == E164 and row["provider_sid"] == NUM_SID
    assert row["provider_account_sid"] == SUB and row["iso_country"] == "CA"


@pytest.mark.asyncio
async def test_a_us_signup_behaves_the_same():
    with world() as w:
        out = await provision_tenant({**BASE, "country": "US"})
    assert out["onboarding_state"] == lifecycle_ob.ACTIVE
    assert w.searches == ["US"]
    assert w.phones[0]["iso_country"] == "US"
    assert list(w.tenants.values())[0]["twilio_phone_number"] == E164


# ══════════════════════════════════════════════════════════════════════════
# 2 — retries resume
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_retry_with_the_same_key_resumes_one_tenant():
    key = str(uuid.uuid4())
    with world() as w:
        first = await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})
        second = await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})
    assert first["tenant_id"] == second["tenant_id"], "a retry minted a second tenant"
    assert len(w.tenants) == 1
    assert w.subaccounts == 1, "a completed signup must not buy a second line"
    assert w.purchases == 1
    assert len(w.phones) == 1


@pytest.mark.asyncio
async def test_a_new_signup_with_a_new_key_is_a_new_tenant():
    with world() as w:
        a = await provision_tenant({**BASE, "country": "CA",
                                    "onboarding_key": str(uuid.uuid4())})
        b = await provision_tenant({**BASE, "country": "CA",
                                    "onboarding_key": str(uuid.uuid4())})
    assert a["tenant_id"] != b["tenant_id"]
    assert len(w.tenants) == 2, "two genuine signups must not be collapsed"


@pytest.mark.asyncio
async def test_concurrent_duplicate_submissions_create_one_tenant():
    """Two requests, one key -- the claim index picks the winner and the loser
    resumes. Modelled the way the real partial unique index behaves."""
    import asyncio
    key = str(uuid.uuid4())
    with world() as w:
        a, b = await asyncio.gather(
            provision_tenant({**BASE, "country": "CA", "onboarding_key": key}),
            provision_tenant({**BASE, "country": "CA", "onboarding_key": key}),
            return_exceptions=True)
    ok = [r for r in (a, b) if isinstance(r, dict)]
    assert ok, f"both attempts failed: {a} {b}"
    assert len(w.tenants) == 1, "a concurrent double-submit minted two tenants"
    assert len({r["tenant_id"] for r in ok}) == 1


@pytest.mark.asyncio
async def test_a_signup_without_a_key_still_works():
    """Callers that predate the key keep working; they simply cannot resume."""
    with world() as w:
        out = await provision_tenant({**BASE, "country": "CA"})
    assert out["onboarding_state"] == lifecycle_ob.ACTIVE
    assert len(w.tenants) == 1


@pytest.mark.asyncio
async def test_a_retry_after_the_provider_failed_reuses_the_same_tenant():
    """The failure that used to leave nothing behind now leaves a resumable tenant."""
    key = str(uuid.uuid4())
    with world() as w:
        with patch("services.telephony.find_available_number",
                   AsyncMock(side_effect=RuntimeError("no inventory"))):
            with pytest.raises(HTTPException):
                await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})
        assert len(w.tenants) == 1, "the tenant should survive a provider failure"
        tid = list(w.tenants)[0]
        assert w.tenants[tid]["onboarding_state"] == lifecycle_ob.PROVISIONING

        out = await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})
    assert out["tenant_id"] == tid, "the retry did not resume the same tenant"
    assert len(w.tenants) == 1
    assert w.purchases == 1


# ══════════════════════════════════════════════════════════════════════════
# 3 — unsupported countries fail closed
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["ZZ", "XX", "", "  ", "CANADA", "ie!"])
async def test_an_unsupported_country_never_reaches_canadian_inventory(bad):
    with pytest.raises(telephony.CountryNotSupported):
        await telephony.find_available_number(SUB, TOK, bad)


def test_the_canada_fallback_is_gone_from_the_source():
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(telephony.find_available_number)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)):
        node.body = node.body[1:]
    body = ast.unparse(tree)
    assert "CountryNotSupported" in body
    assert 'cc = "CA"' not in body and "cc = 'CA'" not in body, \
        "the silent Canada substitution is still there"


@pytest.mark.asyncio
async def test_a_supported_country_still_reaches_inventory():
    """The guard must not have made CA/US unreachable."""
    with world() as w:
        await provision_tenant({**BASE, "country": "CA"})
    assert w.searches == ["CA"]


# ══════════════════════════════════════════════════════════════════════════
# 4 — Ireland diverts before telephony
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ireland_creates_a_tenant_and_touches_no_provider():
    with world() as w:
        out = await provision_tenant({**BASE, "country": "IE",
                                      "onboarding_key": str(uuid.uuid4())})
    assert out["onboarding_state"] == lifecycle_ob.REGULATORY_REQUIRED
    assert out["next_step"] == "regulatory_information_required"
    assert out["phone_number"] == ""
    assert len(w.tenants) == 1, "the Irish tenant must exist"
    t = list(w.tenants.values())[0]
    assert t["business_country_code"] == "IE"
    assert t["onboarding_state"] == lifecycle_ob.REGULATORY_REQUIRED
    # NOTHING at the provider, and nothing in the canonical model
    assert w.subaccounts == 0, "Ireland must not create a Twilio sub-account"
    assert w.searches == [], "Ireland must not search number inventory"
    assert w.purchases == 0, "Ireland must not buy a number"
    assert w.phones == [], "Ireland must not create a phone row"


@pytest.mark.asyncio
async def test_an_irish_retry_resumes_the_same_pending_tenant():
    key = str(uuid.uuid4())
    with world() as w:
        a = await provision_tenant({**BASE, "country": "IE", "onboarding_key": key})
        b = await provision_tenant({**BASE, "country": "IE", "onboarding_key": key})
    assert a["tenant_id"] == b["tenant_id"]
    assert len(w.tenants) == 1
    assert w.purchases == 0


def test_ireland_is_the_only_country_marked_regulated():
    assert lifecycle_ob.needs_regulatory_clearance("IE") is True
    for cc in ("CA", "US", "GB", "AU", "NZ"):
        assert lifecycle_ob.needs_regulatory_clearance(cc) is False, \
            f"{cc} was silently added to the regulated set without measurement"


def test_ireland_signup_is_closed_to_the_public_by_default():
    """The billing policy Ireland needs (trial starts when the +353 is ACTIVE)
    is not implemented yet, so the path must not be publicly reachable."""
    assert lifecycle_ob.ireland_onboarding_enabled() is False


# ══════════════════════════════════════════════════════════════════════════
# 5 — the canonical write path
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_number_is_not_routable_until_it_is_configured():
    """A row is inserted `provisioning`, which phone_lifecycle excludes from
    ROUTABLE_STATUSES -- so a caller cannot be sent to an unwired number."""
    statuses = []
    with world() as w:
        real = phone_registry.mark_active

        async def spy(**kw):
            statuses.append(w.phones[0]["status"])
            return await real(**kw)

        with patch("services.phone_registry.mark_active", AsyncMock(side_effect=spy)):
            await provision_tenant({**BASE, "country": "CA"})
    assert statuses == [lifecycle.STATUS_PROVISIONING], \
        "the row was already active before the voice path was configured"
    assert lifecycle.STATUS_PROVISIONING not in lifecycle.ROUTABLE_STATUSES
    assert w.phones[0]["status"] == lifecycle.STATUS_ACTIVE


@pytest.mark.asyncio
async def test_the_scalar_and_the_canonical_row_are_written_together():
    scalar_at_activation = {}
    with world() as w:
        real = phone_registry.mark_active

        async def spy(**kw):
            t = list(w.tenants.values())[0]
            scalar_at_activation["before"] = t.get("twilio_phone_number")
            out = await real(**kw)
            scalar_at_activation["after"] = list(w.tenants.values())[0].get("twilio_phone_number")
            return out

        with patch("services.phone_registry.mark_active", AsyncMock(side_effect=spy)):
            await provision_tenant({**BASE, "country": "CA"})
    assert scalar_at_activation["before"] in (None, ""), \
        "the legacy scalar was written before the number was routable"
    assert scalar_at_activation["after"] == E164


@pytest.mark.asyncio
async def test_registering_the_same_number_twice_is_idempotent():
    with world() as w:
        tid = str(uuid.uuid4())
        w.tenants[tid] = {"id": tid}
        a = await phone_registry.register_permanent(
            tenant_id=tid, e164=E164, provider_account_sid=SUB,
            provider_sid=NUM_SID, iso_country="CA")
        b = await phone_registry.register_permanent(
            tenant_id=tid, e164=E164, provider_account_sid=SUB,
            provider_sid=NUM_SID, iso_country="CA")
    assert a["created"] is True and b["created"] is False
    assert len(w.phones) == 1, "a retry created a second canonical row"


@pytest.mark.asyncio
async def test_another_tenants_number_is_refused_not_stolen():
    with world() as w:
        t1, t2 = str(uuid.uuid4()), str(uuid.uuid4())
        await phone_registry.register_permanent(
            tenant_id=t1, e164=E164, provider_account_sid=SUB,
            provider_sid=NUM_SID, iso_country="CA")
        out = await phone_registry.register_permanent(
            tenant_id=t2, e164=E164, provider_account_sid=SUB,
            provider_sid=NUM_SID, iso_country="CA")
    assert out["status"] == phone_registry.CONFLICT
    assert out["detail"] == "number_owned_by_another_tenant"
    assert len(w.phones) == 1


@pytest.mark.asyncio
async def test_a_second_live_permanent_number_is_refused():
    """tpn_one_current_permanent, enforced in code before the index has to."""
    with world() as w:
        tid = str(uuid.uuid4())
        await phone_registry.register_permanent(
            tenant_id=tid, e164=E164, provider_account_sid=SUB,
            provider_sid=NUM_SID, iso_country="CA")
        out = await phone_registry.register_permanent(
            tenant_id=tid, e164="+14165550999", provider_account_sid=SUB,
            provider_sid="PN_other", iso_country="CA")
    assert out["status"] == phone_registry.CONFLICT
    assert len(w.phones) == 1


def test_the_scalar_has_exactly_one_writer_in_the_provisioning_path():
    """Two writers with different semantics is how the W9I-A drift happened."""
    import pathlib
    import ast
    import inspect
    import textwrap
    from services import provisioning
    # Both number-acquiring paths -- first signup and re-provision -- must mirror
    # the scalar only through phone_registry. Reading their source directly rather
    # than the whole module, which legitimately CLEARS the scalar elsewhere.
    for fn in (provisioning._provision_after_twilio,
               provisioning.reprovision_tenant_number):
        body = textwrap.dedent(inspect.getsource(fn))
        body = "\n".join(l for l in body.splitlines()
                         if not l.strip().startswith("#"))
        assert '"twilio_phone_number":' not in body, \
            f"{fn.__name__} writes the legacy scalar directly again"
        assert "phone_registry" in body, \
            f"{fn.__name__} does not go through the one write path"
    reg = pathlib.Path(phone_registry.__file__).read_text()
    assert reg.count('"twilio_phone_number"') == 1


# ══════════════════════════════════════════════════════════════════════════
# gaps mutation testing found in the tests above
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_retry_reads_before_it_tries_to_claim():
    """Resuming works through two paths -- the pre-claim read and the re-read after
    a lost claim -- so removing the first one did not change the outcome. It still
    matters: without it every retry attempts a doomed insert and logs a uniqueness
    violation, which is noise that hides real ones.
    """
    key = str(uuid.uuid4())
    with world() as w:
        await provision_tenant({**BASE, "country": "IE", "onboarding_key": key})
        calls = {"n": 0}
        import db.supabase as dbs
        real = dbs.claim_onboarding_tenant

        async def counting(k, row):
            calls["n"] += 1
            return await real(k, row)

        with patch("db.supabase.claim_onboarding_tenant",
                   AsyncMock(side_effect=counting)):
            await provision_tenant({**BASE, "country": "IE", "onboarding_key": key})
    assert calls["n"] == 0, "a retry attempted a claim instead of reading first"
    assert len(w.tenants) == 1


def test_the_real_tenant_claim_catches_the_uniqueness_violation():
    """Binds the REAL data layer. The world() fake returns None directly, so it
    never exercises the 23505 catch -- exactly the fixture-masking trap that has
    bitten every gate in this series."""
    import ast
    import pathlib
    import db.supabase as dbs

    src = pathlib.Path(dbs.__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "claim_onboarding_tenant")
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    body = ast.unparse(fn)
    assert "_is_unique_violation" in body and "return None" in body, \
        "a concurrent duplicate submission would raise a raw 23505 at the API"
    assert dbs._is_unique_violation(type("E", (Exception,), {"code": "23505"})()) is True
    assert dbs._is_unique_violation(ValueError("something else")) is False


# ══════════════════════════════════════════════════════════════════════════
# the onboarding_key trust boundary (W9I-B Stage O4)
# ══════════════════════════════════════════════════════════════════════════
# The key is an idempotency/resume token and NOTHING else. It is not a
# credential: it authenticates nobody, and the only thing it may do is continue
# one narrowly defined INCOMPLETE onboarding.

@pytest.mark.asyncio
async def test_a_random_key_starts_a_fresh_signup_and_reaches_nothing_existing():
    """A guessed uuid4 must not land on anyone's tenant."""
    with world() as w:
        first = await provision_tenant({**BASE, "country": "CA",
                                        "onboarding_key": str(uuid.uuid4())})
        before = dict(w.tenants[first["tenant_id"]])
        await provision_tenant({**BASE, "business_name": "Someone Else",
                                "country": "CA", "onboarding_key": str(uuid.uuid4())})
    assert len(w.tenants) == 2, "a different key must not reach an existing tenant"
    assert w.tenants[first["tenant_id"]]["business_name"] == before["business_name"]


@pytest.mark.asyncio
async def test_a_completed_tenant_is_FROZEN_to_the_onboarding_path():
    """Possession of the key of an ACTIVE tenant must change nothing at all."""
    key = str(uuid.uuid4())
    with world() as w:
        done = await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})
        tid = done["tenant_id"]
        snapshot = dict(w.tenants[tid])
        phones = [dict(r) for r in w.phones]

        again = await provision_tenant({
            **BASE, "business_name": "Hijacked Ltd", "industry": "restaurant",
            "country": "US", "onboarding_key": key})

    assert again["tenant_id"] == tid
    assert again["onboarding_state"] == lifecycle_ob.ACTIVE
    assert w.tenants[tid] == snapshot, "a completed tenant was mutated through the key"
    assert [dict(r) for r in w.phones] == phones, "the phone rows were touched"
    assert w.purchases == 1, "a second number was bought"


@pytest.mark.asyncio
async def test_an_active_tenant_without_a_number_is_still_frozen():
    """Checked on the STATE, not on whether a number happens to be present -- so a
    tenant marked active without one cannot fall through into provisioning."""
    key = str(uuid.uuid4())
    with world() as w:
        await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})
        tid = list(w.tenants)[0]
        w.tenants[tid]["twilio_phone_number"] = None      # the odd historical shape
        out = await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})
    assert out["onboarding_state"] == lifecycle_ob.ACTIVE
    assert w.purchases == 1, "a frozen tenant was re-provisioned"


@pytest.mark.asyncio
async def test_the_country_cannot_be_changed_on_resume():
    """THE HOLE THIS TEST EXISTS FOR. An earlier version took the diversion
    decision from the REQUEST, so a retry carrying the same key and a different
    country would have bought a Canadian number for a tenant whose compliance
    country was already IE."""
    key = str(uuid.uuid4())
    with world() as w:
        ie = await provision_tenant({**BASE, "country": "IE", "onboarding_key": key})
        assert ie["onboarding_state"] == lifecycle_ob.REGULATORY_REQUIRED

        with pytest.raises(HTTPException) as exc:
            await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})

    assert exc.value.status_code == 409
    assert exc.value.detail["status"] == "country_already_set"
    assert exc.value.detail["business_country_code"] == "IE"
    # and nothing was spent on the way to that refusal
    assert w.subaccounts == 0 and w.purchases == 0 and w.phones == []
    assert len(w.tenants) == 1
    assert list(w.tenants.values())[0]["business_country_code"] == "IE"


@pytest.mark.asyncio
async def test_the_reverse_country_flip_is_also_refused():
    """A CA signup mid-flight must not be diverted into the regulated path."""
    key = str(uuid.uuid4())
    with world() as w:
        with patch("services.telephony.find_available_number",
                   AsyncMock(side_effect=RuntimeError("no inventory"))):
            with pytest.raises(HTTPException):
                await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})
        with pytest.raises(HTTPException) as exc:
            await provision_tenant({**BASE, "country": "IE", "onboarding_key": key})
    assert exc.value.status_code == 409
    assert exc.value.detail["business_country_code"] == "CA"


@pytest.mark.asyncio
async def test_resuming_with_the_same_country_is_allowed():
    """The refusal must not break the ordinary retry it exists to protect."""
    key = str(uuid.uuid4())
    with world() as w:
        a = await provision_tenant({**BASE, "country": "IE", "onboarding_key": key})
        b = await provision_tenant({**BASE, "country": "IE", "onboarding_key": key})
    assert a["tenant_id"] == b["tenant_id"]
    assert len(w.tenants) == 1


@pytest.mark.asyncio
async def test_the_compliance_country_is_written_once_and_never_rewritten():
    """Step 12 completes the tenant; it must not carry a country at all."""
    import inspect
    from services import provisioning
    body = inspect.getsource(provisioning._provision_after_twilio)
    assert 'tenant_data.pop("country", None)' in body
    assert 'tenant_data.pop("business_country_code", None)' in body, \
        "a later request could rewrite the compliance country"

    with world() as w:
        key = str(uuid.uuid4())
        await provision_tenant({**BASE, "country": "CA", "onboarding_key": key})
        t = list(w.tenants.values())[0]
    assert t["business_country_code"] == "CA"


@pytest.mark.asyncio
async def test_concurrent_resumes_of_one_incomplete_tenant_stay_single():
    import asyncio
    key = str(uuid.uuid4())
    with world() as w:
        await provision_tenant({**BASE, "country": "IE", "onboarding_key": key})
        out = await asyncio.gather(
            provision_tenant({**BASE, "country": "IE", "onboarding_key": key}),
            provision_tenant({**BASE, "country": "IE", "onboarding_key": key}),
            return_exceptions=True)
    assert len(w.tenants) == 1
    ids = {r["tenant_id"] for r in out if isinstance(r, dict)}
    assert len(ids) == 1
    assert w.purchases == 0


def test_the_key_is_not_a_credential_on_any_authenticated_route():
    """No authenticated route may accept the key as identity. The regulatory
    router is owner-authenticated and must never learn of it."""
    import pathlib
    from services import provisioning
    root = pathlib.Path(provisioning.__file__).parent.parent
    for name in ("regulatory.py", "billing.py", "calls.py", "knowledge.py"):
        f = root / "routers" / name
        if f.exists():
            assert "onboarding_key" not in f.read_text(), \
                f"{name} references the onboarding key"
    # it is written on exactly one table, by exactly one path
    dbs = (root / "db" / "supabase.py").read_text()
    assert dbs.count('"onboarding_key": onboarding_key') == 1


def test_the_key_must_be_a_uuid4():
    """Constrained so it cannot smuggle text into the column, and so a guessable
    value (a name, an email) cannot be passed off as a key."""
    from routers.onboarding import ProvisionRequest
    import pydantic
    for bad in ("not-a-uuid", "admin", "a@b.com", "1", "x" * 64,
                "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(pydantic.ValidationError):
            ProvisionRequest(business_name="X", industry="realtor",
                             country="CA", onboarding_key=bad)
    good = ProvisionRequest(business_name="X", industry="realtor",
                            country="CA", onboarding_key=str(uuid.uuid4()))
    assert good.onboarding_key
