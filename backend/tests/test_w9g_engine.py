"""W9G — the regulatory engine: idempotent steps, ownership checks, no purchases.

Every provider resource must be created at most once per profile. A duplicate Twilio
Address or Bundle is not untidy, it is a second filing about the same business, so
each step looks for a stored SID, confirms it still exists, and only then creates.
"""
import pytest

from services import regulatory_engine as engine
from services import regulatory_ireland as ie_ux
from services import regulatory_requirements as rq
from services import regulatory_state as st
from tests.test_w9g_regulation_discovery import FakeRegulation, IE_REQUIREMENTS

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
SUB = "ACsub00000000000000000000000000001"
WRONG_SUB = "ACwrong0000000000000000000000001"
ADDR_SID = "AD00000000000000000000000000000001"
DOC_SID = "RD00000000000000000000000000000001"
EU_SID = "IT00000000000000000000000000000001"
BU_SID = "BU00000000000000000000000000000001"

GOOD_ADDRESS = {"customer_name": "DANI Ltd", "street": "1 Example Street",
                "city": "Dublin", "region": "Dublin", "postal_code": "D02 AB12"}
GOOD_ATTRS = {"business_name": "DANI Ltd", "business_website": "https://dani.ie",
              "business_registration_number": "123456", "first_name": "Ann",
              "last_name": "Byrne", "email": "ann@dani.ie",
              "business_identity": "DIRECT_CUSTOMER", "is_subassigned": "NO"}

REQS = rq.normalize_regulation(FakeRegulation())


def tenant(**over):
    base = {"id": TENANT, "business_name": "DANI", "email": "owner@dani.ie",
            "business_country_code": "IE", "twilio_subaccount_sid": SUB,
            "twilio_auth_token": "tok"}
    base.update(over)
    return base


# ── a fake Twilio sub-account client ───────────────────────────────────────

class ProviderError(Exception):
    def __init__(self, code=None, status=500, detail="provider"):
        super().__init__(detail)
        self.code = code
        self.status = status



class _Obj:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _Resource:
    """Twilio resources are BOTH callable and collection-like:
    `client.addresses.create(...)` and `client.addresses(sid).fetch()`. A plain
    method cannot be both, which is what the first version of this fake got wrong."""
    def __init__(self, *, create=None, list=None, context=None):
        self._create, self._list, self._context = create, list, context
    def __call__(self, sid=None):
        return self._context(sid)
    def create(self, *a, **kw):
        return self._create(*a, **kw)
    def list(self, *a, **kw):
        return self._list(*a, **kw)


class FakeTwilio:
    """Records every create so duplication is visible, and can be told to fail."""
    def __init__(self, **opts):
        self.opts = opts
        self.created = {"address": 0, "end_user": 0, "document": 0, "bundle": 0,
                        "assignment": 0, "evaluation": 0}
        self.assignments = list(opts.get("existing_assignments", []))
        self.bundle_status = opts.get("bundle_status", "draft")
        self.purchases = 0
        self.last_end_user_attributes = None
        self.last_document = None
        self.last_bundle = None
        self.address_store = {}
        self.deleted_addresses = []
        # SIDs the provider has authoritatively lost. Explicit, because
        # "deleted at the provider" is a precise fact and must not be inferred
        # from an empty store or expressed as a blunt global fetch error -- a
        # freshly recreated resource must not look deleted too.
        self.gone = set()
        self.end_user_store = {}
        self.deleted_end_users = []
        self.document_store = {}
        self.deleted_documents = []
        self.bundle_store = {}
        self.deleted_bundles = []
        self.numbers = self
        self.v2 = self
        self.regulatory_compliance = self

    def _fail(self, key):
        if self.opts.get(key):
            raise self.opts[key]

    # ── addresses ────────────────────────────────────────────────────────
    # Backed by a real store keyed on SID, because W9H-QA.3 turns on questions the
    # provider answers: does an Address with THIS FriendlyName already exist, and is
    # it still there after we delete it. A fake that only counted creates could not
    # express either, and would let takeover/adoption tests pass without the
    # behaviour existing. Measured against the live API in W9H-QA.2: Twilio does NOT
    # deduplicate identical creates, so this fake does not either.
    @property
    def addresses(self):
        outer = self
        def create(**kw):
            hook = outer.opts.get("on_address_create")
            if hook:
                hook(**kw)
            outer._fail("address_error")
            outer.created["address"] += 1
            sid = outer.opts.get("address_sid", ADDR_SID)
            if outer.created["address"] > 1:
                sid = f"{sid}-dup{outer.created['address']}"
            rec = _Obj(sid=sid,
                       validated=outer.opts.get("address_validated", True),
                       city="Dublin 2", region="Dublin",
                       friendly_name=kw.get("friendly_name"))
            outer.address_store[sid] = rec
            return rec
        def _list(friendly_name=None, limit=None, **kw):
            outer._fail("address_list_error")
            return [a for a in outer.address_store.values()
                    if friendly_name is None or a.friendly_name == friendly_name]
        def context(sid):
            class _Ctx:
                def fetch(self):
                    outer._fail("address_fetch_error")
                    rec = outer.address_store.get(sid)
                    if rec is None:
                        raise ProviderError(code=20404, status=404,
                                            detail="address not found")
                    return rec
                def delete(self):
                    outer._fail("address_delete_error")
                    outer.deleted_addresses.append(sid)
                    outer.address_store.pop(sid, None)
                    return True
            return _Ctx()
        return _Resource(create=create, list=_list, context=context)

    # ── end users ────────────────────────────────────────────────────────
    @property
    def end_users(self):
        outer = self
        def _list(limit=None, **kw):
            # MEASURED: Twilio offers NO server-side filter for EndUsers, so this
            # fake accepts none either -- a fake that filtered would let the engine
            # pass while relying on a filter that does not exist.
            outer._fail("end_user_list_error")
            # A resource the provider has lost is absent from list() as well as
            # fetch(), or reconciliation would keep adopting a deleted one.
            return [x for x in outer.end_user_store.values()
                    if x.sid not in outer.gone]
        def create(**kw):
            hook = outer.opts.get("on_end_user_create")
            if hook:
                hook(**kw)
            outer._fail("end_user_error")
            attrs = kw.get("attributes") or {}
            # MODELS THE PROVIDER'S OWN REQUIREMENT, not our hopes. The live IE
            # regulation lists all nine fields as required end-user attributes, so a
            # fake that accepts a partial bag would let a test pass on a payload the
            # real provider would consider incomplete -- which is exactly the
            # too-permissive fake W9G.1 was asked to find. `required_end_user_fields`
            # is settable so a test can model a different regulation.
            required = outer.opts.get("required_end_user_fields",
                                      tuple(REQS.end_user_field_names))
            optional = {"comments"}
            missing = [f for f in required
                       if f not in optional
                       and str(attrs.get(f) or "").strip() == ""]
            if missing:
                raise ProviderError(code=22212, status=400,
                                    detail=f"missing required end-user fields: {missing}")
            outer.created["end_user"] += 1
            outer.last_end_user_attributes = attrs
            sid = EU_SID if outer.created["end_user"] == 1 \
                else f"{EU_SID}-dup{outer.created['end_user']}"
            rec = _Obj(sid=sid, friendly_name=kw.get("friendly_name"),
                       attributes=attrs)
            outer.end_user_store[sid] = rec
            return rec
        def context(sid):
            class _Ctx:
                def fetch(self):
                    hook = outer.opts.get("on_end_user_fetch")
                    if hook:
                        hook(sid)
                    # THE STORE IS AUTHORITATIVE FOR EXISTENCE. A SID that is not
                    # there 404s, exactly as the provider would; a configured error
                    # applies only to one that IS there. A blunt global fetch error
                    # made a freshly recreated resource appear deleted too, which
                    # is not a state the provider can be in.
                    if sid in outer.gone:
                        raise ProviderError(code=20404, status=404,
                                            detail="end user not found")
                    outer._fail("end_user_fetch_error")
                    return _Obj(sid=sid,
                                attributes=outer.opts.get("end_user_attributes",
                                                          dict(GOOD_ATTRS)))
                def delete(self):
                    outer._fail("end_user_delete_error")
                    outer.deleted_end_users.append(sid)
                    outer.end_user_store.pop(sid, None)
                    return True
            return _Ctx()
        return _Resource(create=create, list=_list, context=context)

    # ── supporting documents ─────────────────────────────────────────────
    @property
    def supporting_documents(self):
        outer = self
        def _list(limit=None, **kw):
            # MEASURED: no server-side filter for SupportingDocuments either.
            outer._fail("document_list_error")
            return [x for x in outer.document_store.values()
                    if x.sid not in outer.gone]
        def create(**kw):
            hook = outer.opts.get("on_document_create")
            if hook:
                hook(**kw)
            outer._fail("document_error")
            outer.created["document"] += 1
            outer.last_document = kw
            sid = DOC_SID if outer.created["document"] == 1 \
                else f"{DOC_SID}-dup{outer.created['document']}"
            rec = _Obj(sid=sid, status="draft", friendly_name=kw.get("friendly_name"))
            outer.document_store[sid] = rec
            return rec
        def context(sid):
            class _Ctx:
                def fetch(self):
                    hook = outer.opts.get("on_document_fetch")
                    if hook:
                        hook(sid)
                    if sid in outer.gone:
                        raise ProviderError(code=20404, status=404,
                                            detail="document not found")
                    outer._fail("document_fetch_error")
                    return _Obj(sid=sid)
                def delete(self):
                    outer._fail("document_delete_error")
                    outer.deleted_documents.append(sid)
                    outer.document_store.pop(sid, None)
                    return True
            return _Ctx()
        return _Resource(create=create, list=_list, context=context)

    # ── bundles ──────────────────────────────────────────────────────────
    @property
    def bundles(self):
        outer = self
        def _list(friendly_name=None, limit=None, **kw):
            # MEASURED: Bundles DO support a server-side FriendlyName filter, so
            # this fake honours it -- the engine relies on it for Bundles only.
            outer._fail("bundle_list_error")
            return [b for b in outer.bundle_store.values()
                    if b.sid not in outer.gone
                    and (friendly_name is None or b.friendly_name == friendly_name)]
        def create(**kw):
            hook = outer.opts.get("on_bundle_create")
            if hook:
                hook(**kw)
            outer._fail("bundle_error")
            outer.created["bundle"] += 1
            outer.last_bundle = kw
            sid = BU_SID if outer.created["bundle"] == 1 \
                else f"{BU_SID}-dup{outer.created['bundle']}"
            rec = _Obj(sid=sid, status="draft", friendly_name=kw.get("friendly_name"))
            outer.bundle_store[sid] = rec
            return rec

        def context(sid):
            class _IA:
                def list(self, limit=None):
                    outer._fail("assignment_list_error")
                    return [_Obj(sid=f"BV{i}", object_sid=s)
                            for i, s in enumerate(outer.assignments)]
                def create(self, object_sid):
                    outer._fail("assignment_error")
                    outer.created["assignment"] += 1
                    outer.assignments.append(object_sid)
                    return _Obj(sid="BVnew", object_sid=object_sid)

            class _Ev:
                def create(self):
                    outer._fail("evaluation_error")
                    outer.created["evaluation"] += 1
                    compliant = outer.opts.get("compliant", True)
                    return _Obj(sid="ELx",
                                status="compliant" if compliant else "noncompliant",
                                results=([{"requirement_name": "business_info",
                                           "passed": True}] if compliant else
                                         [{"requirement_name": "business_address_info",
                                           "passed": False}]))

            class _Ctx:
                item_assignments = _IA()
                evaluations = _Ev()
                def fetch(self):
                    if sid in outer.gone:
                        raise ProviderError(code=20404, status=404,
                                            detail="bundle not found")
                    outer._fail("bundle_fetch_error")
                    return _Obj(sid=sid, status=outer.bundle_status)
                def update(self, **kw):
                    outer._fail("submit_error")
                    outer.bundle_status = kw.get("status", "pending-review")
                    return _Obj(sid=sid, status=outer.bundle_status)
                def delete(self):
                    outer._fail("bundle_delete_error")
                    outer.deleted_bundles.append(sid)
                    outer.bundle_store.pop(sid, None)
                    return True
            return _Ctx()
        return _Resource(create=create, list=_list, context=context)

    # ── regulations ──────────────────────────────────────────────────────
    @property
    def regulations(self):
        outer = self
        def _list(**kw):
            outer._fail("regulation_error")
            return outer.opts.get("regulations", [FakeRegulation()])
        return _Resource(list=_list, context=lambda sid: _Obj(sid=sid))

    # A purchase would be a gate violation. Recorded AND raised.
    @property
    def incoming_phone_numbers(self):
        outer = self
        def create(**kw):
            outer.purchases += 1
            raise AssertionError("W9G MUST NOT PURCHASE A NUMBER")
        return _Resource(create=create, context=lambda sid: _Obj(sid=sid))


@pytest.fixture
def world(monkeypatch):
    # A controllable clock, so a stale-claim test states the elapsed time it means
    # instead of sleeping for two real minutes.
    clock = {"t": 1_000_000.0}
    state = {"twilio": FakeTwilio(), "addresses": [], "profiles": [], "details": [],
             "locations": [{"id": "loc-1", "tenant_id": TENANT}],
             "inserted_addresses": 0, "inserted_profiles": 0,
             "claims": [],
             "clock": clock, "now": lambda: clock["t"]}

    class FakeQB:
        def __init__(self, table): self.table, self.filters = table, {}
        def select(self, *a, **k): return self
        def eq(self, c, v): self.filters[c] = v; return self
        def limit(self, *a, **k): return self
        def execute(self):
            rows = state["locations"] if self.table == "tenant_locations" else []
            for c, v in self.filters.items():
                rows = [r for r in rows if str(r.get(c)) == str(v)]
            class R: data = rows
            return R()

    class FakeClient:
        def table(self, name): return FakeQB(name)

    monkeypatch.setattr(engine.telephony, "_sub_client",
                        lambda sid, tok: state["twilio"])
    monkeypatch.setattr("db.supabase.get_client", lambda: FakeClient())

    async def find_address(tid, country, loc):
        for a in state["addresses"]:
            if (a["tenant_id"] == tid and a["iso_country"] == country
                    and (a.get("tenant_location_id") or None) == (loc or None)):
                return a
        return None
    async def insert_address(row):
        state["inserted_addresses"] += 1
        row = {**row, "id": f"addr-{state['inserted_addresses']}"}
        state["addresses"].append(row)
        return row
    async def update_address(aid, patch):
        for a in state["addresses"]:
            if a["id"] == aid:
                a.update(patch); return a
        return None
    async def get_address(tid, aid):
        return next((a for a in state["addresses"]
                     if a["id"] == aid and a["tenant_id"] == tid), None)

    # ── the claim primitives (W9H-QA.3) ──────────────────────────────────
    # These model the DATABASE, not the engine: claim_address enforces migration
    # 027's partial unique indexes and returns None on conflict exactly as a caught
    # 23505 does; attach/record are fenced on `address_sid is null`; takeover
    # reproduces the two compare-and-set predicates. Nothing here reimplements a
    # decision ensure_address makes -- if the engine stopped claiming before
    # creating, every one of these would still behave the same and the tests would
    # correctly fail.
    async def claim_address(row):
        scope = (row["tenant_id"], row.get("tenant_location_id") or None,
                 row["iso_country"], row.get("provider", "twilio"))
        for a in state["addresses"]:
            if (a["tenant_id"], a.get("tenant_location_id") or None,
                    a["iso_country"], a.get("provider", "twilio")) == scope:
                return None                      # 23505, caught in the real layer
        state["inserted_addresses"] += 1
        # Postgres returns the row with every column present; address_sid is NULL,
        # not absent. A fake that omitted it would hide a KeyError the real layer
        # cannot produce.
        new_row = {"address_sid": None, "validation_error": None,
                   **row, "id": f"addr-{state['inserted_addresses']}",
                   "updated_at": state["now"]()}
        state["addresses"].append(new_row)
        return new_row

    async def attach_address_sid(aid, patch):
        for a in state["addresses"]:
            if a["id"] == aid and a.get("address_sid") is None:
                a.update(patch); a["updated_at"] = state["now"]()
                return a
        return None                              # the fence rejected us

    async def take_over_address_claim(aid):
        for a in state["addresses"]:
            if a["id"] != aid or a.get("address_sid") is not None:
                continue
            terminal = a.get("validation_error") is not None
            age = state["now"]() - a.get("updated_at", state["now"]())
            if terminal or age >= engine.db_reg.CLAIM_STALE_SECONDS:
                a["validation_error"] = None
                a["updated_at"] = state["now"]()
                return a
            return None
        return None

    async def release_address_claim(aid):
        for a in state["addresses"]:
            if a["id"] == aid and a.get("address_sid") is None:
                a["updated_at"] = -10 ** 9      # older than any stale window
                return a
        return None

    async def record_address_failure(aid, error):
        for a in state["addresses"]:
            if a["id"] == aid and a.get("address_sid") is None:
                a.update({"validated": False, "validation_error": error})
                a["updated_at"] = state["now"]()
                return a
        return None
    # ── provider claims (migration 030, W9H-QA.4) ────────────────────────
    # Models the TABLE: trpc_scope_key's uniqueness, the provider_sid IS NULL
    # fence, and the two takeover compare-and-sets. Nothing here reimplements a
    # decision the engine makes -- if _ensure_provider_resource stopped claiming
    # before creating, these fakes would behave identically and the tests would
    # correctly fail.
    async def claim_provider_resource(*, tenant_id, resource, scope_key,
                                      provider_account_sid, provider="twilio"):
        key = (tenant_id, provider, resource, scope_key)
        for c_ in state["claims"]:
            if (c_["tenant_id"], c_["provider"], c_["resource"], c_["scope_key"]) == key:
                return None                      # 23505 on trpc_scope_key
        row = {"id": f"claim-{len(state['claims']) + 1}", "tenant_id": tenant_id,
               "provider": provider, "resource": resource, "scope_key": scope_key,
               "provider_account_sid": provider_account_sid, "provider_sid": None,
               "failure": None, "claimed_at": state["now"]()}
        state["claims"].append(row)
        return row

    async def find_provider_claim(*, tenant_id, resource, scope_key,
                                  provider="twilio"):
        return next((c_ for c_ in state["claims"]
                     if c_["tenant_id"] == tenant_id and c_["provider"] == provider
                     and c_["resource"] == resource
                     and c_["scope_key"] == scope_key), None)

    async def attach_provider_sid(claim_id, provider_sid, provider_account_sid):
        for c_ in state["claims"]:
            if c_["id"] == claim_id and c_["provider_sid"] is None:
                c_.update({"provider_sid": provider_sid, "failure": None,
                           "provider_account_sid": provider_account_sid})
                return c_
        return None                              # the fence rejected us

    async def take_over_provider_claim(claim_id):
        for c_ in state["claims"]:
            if c_["id"] != claim_id or c_["provider_sid"] is not None:
                continue
            terminal = c_.get("failure") is not None
            age = state["now"]() - c_.get("claimed_at", state["now"]())
            if terminal or age >= engine.db_reg.CLAIM_STALE_SECONDS:
                c_.update({"failure": None, "claimed_at": state["now"]()})
                return c_
            return None
        return None

    async def reconcile_profile_end_user_sids(tid, country, eut, canonical):
        n = 0
        for p_ in state["profiles"]:
            if (p_["tenant_id"] == tid and p_.get("iso_country") == country
                    and p_.get("end_user_type") == eut
                    and p_.get("end_user_sid") != canonical):
                p_["end_user_sid"] = canonical
                n += 1
        return n

    async def retire_provider_claim(claim_id, expected_provider_sid):
        # Models the CAS: the fence is the EXPECTED SID, not the claim id, so a
        # worker holding a stale 404 cannot clear a newer attachment.
        for c_ in state["claims"]:
            if c_["id"] == claim_id and c_["provider_sid"] == expected_provider_sid:
                c_.update({"provider_sid": None, "failure": None,
                           "claimed_at": state["now"]()})
                return c_
        return None

    async def release_provider_claim(claim_id):
        for c_ in state["claims"]:
            if c_["id"] == claim_id and c_["provider_sid"] is None:
                c_["claimed_at"] = -10 ** 9     # older than any stale window
                return c_
        return None

    async def record_provider_claim_failure(claim_id, failure):
        for c_ in state["claims"]:
            if c_["id"] == claim_id and c_["provider_sid"] is None:
                c_["failure"] = failure
                return c_
        return None

    async def list_profiles(tid):
        return [p for p in state["profiles"] if p["tenant_id"] == tid]
    async def find_profile_for_address(tid, country, nt, eut, addr_id):
        return next((p for p in state["profiles"]
                     if p["tenant_id"] == tid and p.get("regulatory_address_id") == addr_id
                     and p["iso_country"] == country and p["number_type"] == nt), None)
    async def insert_profile(row):
        state["inserted_profiles"] += 1
        row = {**row, "id": f"prof-{state['inserted_profiles']}"}
        state["profiles"].append(row)
        return row
    async def update_profile(pid, patch):
        for p in state["profiles"]:
            if p["id"] == pid:
                p.update(patch); return p
        return None
    async def transition_profile(pid, *, expected_state, new_state, patch=None):
        for p in state["profiles"]:
            if p["id"] == pid and p.get("state") == expected_state:
                p.update(patch or {}); p["state"] = new_state
                return True
        return False

    async def get_details(tid, country, end_user_type="business"):
        return next((d for d in state["details"]
                     if d["tenant_id"] == tid and d["iso_country"] == country
                     and d["end_user_type"] == end_user_type), None)

    async def upsert_details(tid, country, *, end_user_type="business", values):
        patch = {k: v for k, v in (values or {}).items()
                 if k in engine.db_reg.BUSINESS_DETAIL_COLUMNS
                 and str(v if v is not None else "").strip() != ""}
        row = await get_details(tid, country, end_user_type)
        if row:
            row.update(patch)
            return row
        row = {"id": f"det-{len(state['details']) + 1}", "tenant_id": tid,
               "iso_country": country, "end_user_type": end_user_type, **patch}
        state["details"].append(row)
        return row

    monkeypatch.setattr(engine.db_reg, "get_business_details", get_details)
    monkeypatch.setattr(engine.db_reg, "upsert_business_details", upsert_details)

    for name, fn in (("find_address", find_address), ("insert_address", insert_address),
                     ("update_address", update_address), ("get_address", get_address),
                     ("claim_address", claim_address),
                     ("attach_address_sid", attach_address_sid),
                     ("take_over_address_claim", take_over_address_claim),
                     ("record_address_failure", record_address_failure),
                     ("release_address_claim", release_address_claim),
                     ("release_provider_claim", release_provider_claim),
                     ("retire_provider_claim", retire_provider_claim),
                     ("reconcile_profile_end_user_sids", reconcile_profile_end_user_sids),
                     ("claim_provider_resource", claim_provider_resource),
                     ("find_provider_claim", find_provider_claim),
                     ("attach_provider_sid", attach_provider_sid),
                     ("take_over_provider_claim", take_over_provider_claim),
                     ("record_provider_claim_failure", record_provider_claim_failure),
                     ("list_profiles", list_profiles),
                     ("find_profile_for_address", find_profile_for_address),
                     ("insert_profile", insert_profile),
                     ("update_profile", update_profile),
                     ("transition_profile", transition_profile)):
        monkeypatch.setattr(engine.db_reg, name, fn)
    return state


# ── address ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_complete_irish_address_is_created_and_persisted(world):
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert r["ok"] and r["reused"] is False
    a = r["address"]
    assert a["address_sid"] == ADDR_SID and a["validated"] is True
    assert a["provider_account_sid"] == SUB
    assert a["provider_locality"] == "Dublin 2"     # provider normalisation, metadata only
    assert world["twilio"].created["address"] == 1


@pytest.mark.asyncio
async def test_an_irish_address_without_an_eircode_is_refused_before_the_provider(world):
    """The provider rejects it anyway (W9C measured 21628), and a refusal before
    creation is clearer than one after."""
    r = await engine.ensure_address(tenant(),
                                   submitted={**GOOD_ADDRESS, "postal_code": ""})
    assert r["status"] == engine.INVALID_CUSTOMER_DATA
    assert "postal_code" in r["missing"]
    assert world["twilio"].created["address"] == 0


@pytest.mark.asyncio
async def test_an_incomplete_address_is_refused(world):
    r = await engine.ensure_address(tenant(), submitted={"city": "Dublin"})
    assert r["status"] == engine.INVALID_CUSTOMER_DATA
    assert set(r["missing"]) >= {"customer_name", "street", "postal_code"}


@pytest.mark.asyncio
async def test_provider_validation_failure_is_distinct_from_an_outage(world):
    """21628 means the customer's address could not be validated. Anything else means
    we do not know -- the two must not share a state."""
    world["twilio"].opts["address_error"] = ProviderError(code=21628, status=400)
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert r["status"] == engine.ADDRESS_VALIDATION_FAILED

    world["addresses"].clear()
    world["twilio"].opts["address_error"] = ProviderError(code=20500, status=500)
    r2 = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert r2["status"] == engine.PROVIDER_UNAVAILABLE
    assert r2["status"] != engine.ADDRESS_VALIDATION_FAILED


@pytest.mark.asyncio
async def test_a_validation_failure_never_logs_the_address(world, caplog):
    world["twilio"].opts["address_error"] = ProviderError(code=21628, status=400)
    with caplog.at_level("WARNING"):
        await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    for secret in ("1 Example Street", "D02 AB12", "DANI Ltd"):
        assert secret not in caplog.text


@pytest.mark.asyncio
async def test_a_retry_reuses_the_existing_address_rather_than_creating_a_second(world):
    first = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert first["reused"] is False
    second = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert second["reused"] is True
    assert world["twilio"].created["address"] == 1, "a duplicate filing was created"
    assert world["inserted_addresses"] == 1


@pytest.mark.asyncio
async def test_a_cross_tenant_location_is_refused(world):
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS,
                                    tenant_location_id="loc-of-another-tenant")
    assert r["status"] == engine.OWNERSHIP_CONFLICT
    assert r["detail"] == "tenant_location_not_owned"
    assert world["twilio"].created["address"] == 0


@pytest.mark.asyncio
async def test_a_tenant_owned_location_is_accepted(world):
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS,
                                    tenant_location_id="loc-1")
    assert r["ok"] and r["address"]["tenant_location_id"] == "loc-1"


@pytest.mark.asyncio
async def test_an_address_row_from_the_wrong_account_fails_closed(world):
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    world["addresses"][0]["provider_account_sid"] = WRONG_SUB
    r = await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    assert r["status"] == engine.OWNERSHIP_CONFLICT


@pytest.mark.asyncio
async def test_no_country_confirmed_means_no_address(world):
    r = await engine.ensure_address(tenant(business_country_code=None),
                                    submitted=GOOD_ADDRESS)
    assert r["status"] == engine.MISSING_COUNTRY


@pytest.mark.asyncio
async def test_missing_twilio_credentials_fail_closed(world):
    r = await engine.ensure_address(tenant(twilio_auth_token=""),
                                    submitted=GOOD_ADDRESS)
    assert r["status"] == engine.OWNERSHIP_CONFLICT


# ── EndUser ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_first_profile_creates_an_end_user(world):
    r = await engine.resolve_end_user(tenant(), requirements=REQS,
                                      attributes=GOOD_ATTRS,
                                      client=world["twilio"], sub_sid=SUB)
    assert r["ok"] and r["end_user_sid"] == EU_SID and r["reused"] is False
    assert world["twilio"].created["end_user"] == 1


@pytest.mark.asyncio
async def test_only_fields_the_current_regulation_asks_for_are_sent(world):
    """Sending an obsolete field would be submitting a statement the regulation does
    not define."""
    await engine.resolve_end_user(tenant(), requirements=REQS,
                                  attributes={**GOOD_ATTRS, "obsolete_field": "x",
                                              "vat_number": "y"},
                                  client=world["twilio"], sub_sid=SUB)
    sent = world["twilio"].last_end_user_attributes
    assert "obsolete_field" not in sent and "vat_number" not in sent
    assert set(sent) <= set(REQS.end_user_field_names)


@pytest.mark.asyncio
async def test_a_sibling_profile_reuses_the_same_end_user(world):
    world["profiles"].append({"id": "p1", "tenant_id": TENANT, "iso_country": "IE",
                              "end_user_type": "business", "end_user_sid": EU_SID,
                              "provider_account_sid": SUB, "number_type": "local"})
    r = await engine.resolve_end_user(tenant(), requirements=REQS,
                                      attributes=GOOD_ATTRS,
                                      client=world["twilio"], sub_sid=SUB)
    assert r["ok"] and r["reused"] is True and r["end_user_sid"] == EU_SID
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_two_conflicting_sibling_end_users_FAIL_CLOSED(world):
    """Picking one would file a bundle against an identity nobody chose."""
    for i, sid in enumerate(("IT_a", "IT_b")):
        world["profiles"].append({"id": f"p{i}", "tenant_id": TENANT,
                                  "iso_country": "IE", "end_user_type": "business",
                                  "end_user_sid": sid, "provider_account_sid": SUB,
                                  "number_type": "local"})
    r = await engine.resolve_end_user(tenant(), requirements=REQS,
                                      attributes=GOOD_ATTRS,
                                      client=world["twilio"], sub_sid=SUB)
    assert r["status"] == engine.REGULATORY_IDENTITY_CONFLICT
    assert r["count"] == 2
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_a_sibling_in_the_wrong_account_fails_closed(world):
    world["profiles"].append({"id": "p1", "tenant_id": TENANT, "iso_country": "IE",
                              "end_user_type": "business", "end_user_sid": EU_SID,
                              "provider_account_sid": WRONG_SUB, "number_type": "local"})
    r = await engine.resolve_end_user(tenant(), requirements=REQS,
                                      attributes=GOOD_ATTRS,
                                      client=world["twilio"], sub_sid=SUB)
    assert r["status"] == engine.OWNERSHIP_CONFLICT


@pytest.mark.asyncio
async def test_end_user_attributes_are_never_logged(world, caplog):
    world["twilio"].opts["end_user_error"] = ProviderError(code=400, status=400)
    with caplog.at_level("ERROR"):
        await engine.resolve_end_user(tenant(), requirements=REQS,
                                      attributes=GOOD_ATTRS,
                                      client=world["twilio"], sub_sid=SUB)
    for secret in ("Ann", "Byrne", "ann@dani.ie", "123456"):
        assert secret not in caplog.text


# ── supporting document ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_address_document_is_created_referencing_the_address_sid(world):
    addr = (await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS))["address"]
    r = await engine.ensure_supporting_document(tenant(), requirements=REQS,
                                               address_row=addr,
                                               client=world["twilio"], sub_sid=SUB)
    assert r["ok"] and r["supporting_document_sid"] == DOC_SID
    assert world["twilio"].last_document["attributes"] == {"address_sids": [ADDR_SID]}
    assert world["twilio"].last_document["type"] == "business_address"


@pytest.mark.asyncio
async def test_an_existing_document_is_reused(world):
    addr = (await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS))["address"]
    await engine.ensure_supporting_document(tenant(), requirements=REQS,
                                           address_row=addr, client=world["twilio"],
                                           sub_sid=SUB)
    again = await engine.ensure_supporting_document(
        tenant(), requirements=REQS, address_row=world["addresses"][0],
        client=world["twilio"], sub_sid=SUB)
    assert again["reused"] is True
    assert world["twilio"].created["document"] == 1


@pytest.mark.asyncio
async def test_a_file_upload_requirement_FAILS_CLOSED_rather_than_improvising(world):
    """If the provider starts requiring an actual identity document, that needs its
    own security design -- not a quiet files.create here."""
    file_reqs = rq.normalize_regulation(FakeRegulation(requirements={
        "end_user": IE_REQUIREMENTS["end_user"],
        "supporting_document": [[{"requirement_name": "id", "name": "Photo ID",
                                  "accepted_documents": [
                                      {"type": "passport", "fields": ["document_file"],
                                       "detailed_fields": []}]}]]}))
    addr = (await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS))["address"]
    r = await engine.ensure_supporting_document(tenant(), requirements=file_reqs,
                                               address_row=addr,
                                               client=world["twilio"], sub_sid=SUB)
    assert r["status"] == engine.UNSUPPORTED_DOCUMENT_REQUIREMENT
    assert "document upload" in r["next_requirement"]
    assert world["twilio"].created["document"] == 0


@pytest.mark.asyncio
async def test_two_required_documents_also_fail_closed(world):
    """W9C proved a bundle accepts exactly one business_address document (70002)."""
    two = rq.normalize_regulation(FakeRegulation(requirements={
        "end_user": IE_REQUIREMENTS["end_user"],
        "supporting_document": [
            IE_REQUIREMENTS["supporting_document"][0],
            [{"requirement_name": "second", "name": "Another",
              "accepted_documents": [{"type": "business_address",
                                      "fields": ["address_sids"]}]}]]}))
    addr = (await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS))["address"]
    r = await engine.ensure_supporting_document(tenant(), requirements=two,
                                               address_row=addr,
                                               client=world["twilio"], sub_sid=SUB)
    assert r["status"] == engine.UNSUPPORTED_DOCUMENT_REQUIREMENT


# ── bundle + assignments ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_bundle_is_created_with_the_callback_and_regulation(world):
    profile = {"id": "p1", "provider_account_sid": SUB}
    r = await engine.ensure_bundle(tenant(), profile=profile, requirements=REQS,
                                   end_user_sid=EU_SID, client=world["twilio"],
                                   sub_sid=SUB)
    assert r["ok"] and r["bundle_sid"] == BU_SID
    kw = world["twilio"].last_bundle
    assert kw["regulation_sid"] == REQS.regulation_sid
    assert kw["status_callback"].endswith("/webhooks/twilio/regulatory")
    assert kw["email"] == "owner@dani.ie"


@pytest.mark.asyncio
async def test_a_retry_reuses_the_existing_bundle(world):
    profile = {"id": "p1", "provider_account_sid": SUB, "bundle_sid": BU_SID}
    r = await engine.ensure_bundle(tenant(), profile=profile, requirements=REQS,
                                   end_user_sid=EU_SID, client=world["twilio"],
                                   sub_sid=SUB)
    assert r["reused"] is True
    assert world["twilio"].created["bundle"] == 0


@pytest.mark.asyncio
async def test_a_bundle_from_the_wrong_account_is_refused(world):
    profile = {"id": "p1", "provider_account_sid": WRONG_SUB, "bundle_sid": BU_SID}
    r = await engine.ensure_bundle(tenant(), profile=profile, requirements=REQS,
                                   end_user_sid=EU_SID, client=world["twilio"],
                                   sub_sid=SUB)
    assert r["status"] == engine.OWNERSHIP_CONFLICT


@pytest.mark.asyncio
async def test_assignments_are_created_once_and_reconciled_on_retry(world):
    first = await engine.ensure_item_assignments(
        bundle_sid=BU_SID, object_sids=[EU_SID, DOC_SID], client=world["twilio"])
    assert sorted(first["assigned"]) == sorted([EU_SID, DOC_SID])
    again = await engine.ensure_item_assignments(
        bundle_sid=BU_SID, object_sids=[EU_SID, DOC_SID], client=world["twilio"])
    assert again["assigned"] == []
    assert sorted(again["already_assigned"]) == sorted([EU_SID, DOC_SID])
    assert world["twilio"].created["assignment"] == 2


@pytest.mark.asyncio
async def test_a_provider_duplicate_error_is_treated_as_already_assigned(world):
    """W9C saw 22214 'EndUser already exists on bundle'."""
    world["twilio"].opts["assignment_error"] = ProviderError(code=22214, status=400)
    r = await engine.ensure_item_assignments(bundle_sid=BU_SID, object_sids=[EU_SID],
                                             client=world["twilio"])
    assert r["ok"] and r["already_assigned"] == [EU_SID]


# ── evaluation ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_compliant_evaluation_moves_the_profile_to_ready_to_submit(world):
    world["profiles"].append({"id": "p1", "tenant_id": TENANT, "bundle_sid": BU_SID,
                              "provider_account_sid": SUB,
                              "state": st.DETAILS_REQUIRED})
    r = await engine.evaluate_profile(tenant(), profile=world["profiles"][0])
    assert r["ok"] and r["compliant"] is True
    assert world["profiles"][0]["state"] == st.READY_TO_SUBMIT
    assert world["profiles"][0]["evaluation_status"] == "compliant"


@pytest.mark.asyncio
async def test_a_noncompliant_evaluation_records_the_reason_without_logging_it(world, caplog):
    world["twilio"].opts["compliant"] = False
    world["profiles"].append({"id": "p1", "tenant_id": TENANT, "bundle_sid": BU_SID,
                              "provider_account_sid": SUB,
                              "state": st.DETAILS_REQUIRED})
    with caplog.at_level("INFO"):
        r = await engine.evaluate_profile(tenant(), profile=world["profiles"][0])
    assert r["compliant"] is False
    p = world["profiles"][0]
    assert p["evaluation_status"] == "noncompliant"
    assert p["failure_reason"] and "business_address_info" in p["failure_reason"]
    assert p["failure_reason"] not in caplog.text


@pytest.mark.asyncio
async def test_a_provider_error_is_NOT_recorded_as_noncompliance(world):
    """Otherwise a customer is told their details are wrong because Twilio blipped."""
    world["twilio"].opts["evaluation_error"] = ProviderError(code=20500, status=500)
    world["profiles"].append({"id": "p1", "tenant_id": TENANT, "bundle_sid": BU_SID,
                              "provider_account_sid": SUB,
                              "state": st.DETAILS_REQUIRED,
                              "evaluation_status": None})
    r = await engine.evaluate_profile(tenant(), profile=world["profiles"][0])
    assert r["status"] == engine.PROVIDER_UNAVAILABLE
    assert world["profiles"][0]["evaluation_status"] is None
    assert world["profiles"][0]["state"] == st.DETAILS_REQUIRED


# ── submission gating ──────────────────────────────────────────────────────

def _profile(**over):
    base = {"id": "p1", "tenant_id": TENANT, "bundle_sid": BU_SID,
            "end_user_sid": EU_SID, "provider_account_sid": SUB,
            "iso_country": "IE", "number_type": "local", "end_user_type": "business",
            "regulation_sid": REQS.regulation_sid, "state": st.READY_TO_SUBMIT,
            "evaluation_status": "compliant", "regulatory_address_id": "addr-1",
            "requirements_fingerprint": REQS.fingerprint()}
    base.update(over)
    return base


def test_submission_is_blocked_until_the_evaluation_is_compliant():
    addr = {"validated": True, "supporting_document_sid": DOC_SID}
    blockers = engine.submission_blockers(
        profile=_profile(evaluation_status="noncompliant"), requirements=REQS,
        attributes=GOOD_ATTRS, address_row=addr)
    assert "evaluation_not_compliant" in blockers


def test_submission_is_blocked_by_the_unresolved_isv_declaration():
    """The one thing W9G refuses to guess: a declaration to an Irish regulator about
    the OpenLines/tenant relationship."""
    addr = {"validated": True, "supporting_document_sid": DOC_SID}
    attrs = {k: v for k, v in GOOD_ATTRS.items()
             if k not in ("business_identity", "is_subassigned")}
    blockers = engine.submission_blockers(profile=_profile(), requirements=REQS,
                                          attributes=attrs, address_row=addr)
    assert any(b.startswith(engine.UNRESOLVED_ISV_DECLARATION) for b in blockers)


def test_a_fully_answered_profile_has_no_blockers():
    addr = {"validated": True, "supporting_document_sid": DOC_SID}
    assert engine.submission_blockers(profile=_profile(), requirements=REQS,
                                      attributes=GOOD_ATTRS, address_row=addr) == []


@pytest.mark.parametrize("mutate,expected", [
    ({"bundle_sid": None}, "bundle_missing"),
    ({"end_user_sid": None}, "end_user_missing"),
])
def test_missing_provider_resources_block_submission(mutate, expected):
    addr = {"validated": True, "supporting_document_sid": DOC_SID}
    blockers = engine.submission_blockers(profile=_profile(**mutate), requirements=REQS,
                                          attributes=GOOD_ATTRS, address_row=addr)
    assert expected in blockers


def test_an_unvalidated_address_blocks_submission():
    blockers = engine.submission_blockers(
        profile=_profile(), requirements=REQS, attributes=GOOD_ATTRS,
        address_row={"validated": False, "supporting_document_sid": DOC_SID})
    assert "address_not_validated" in blockers


def _seed_details(world):
    """The durable answers a real workflow would already have stored."""
    world["details"].append({"id": "det-1", "tenant_id": TENANT, "iso_country": "IE",
                             "end_user_type": "business",
                             **{k: v for k, v in
                                {"business_name": GOOD_ATTRS["business_name"],
                                 "business_website": GOOD_ATTRS["business_website"],
                                 "business_registration_number":
                                     GOOD_ATTRS["business_registration_number"],
                                 "authorized_rep_first_name": GOOD_ATTRS["first_name"],
                                 "authorized_rep_last_name": GOOD_ATTRS["last_name"],
                                 "authorized_rep_email": GOOD_ATTRS["email"],
                                 "business_identity": GOOD_ATTRS["business_identity"],
                                 "is_subassigned": GOOD_ATTRS["is_subassigned"],
                                 }.items()},
                             "requirements_fingerprint": REQS.fingerprint()})


@pytest.mark.asyncio
async def test_submission_transitions_and_persists_the_provider_status(world):
    _seed_details(world)
    world["profiles"].append(_profile())
    world["addresses"].append({"id": "addr-1", "tenant_id": TENANT, "iso_country": "IE",
                               "validated": True, "supporting_document_sid": DOC_SID,
                               "address_sid": ADDR_SID, "provider_account_sid": SUB})
    r = await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert r["ok"] and r["state"] == st.PENDING_REVIEW
    assert r["bundle_status"] == "pending-review"
    p = world["profiles"][0]
    assert p["state"] == st.PENDING_REVIEW and p["submitted_at"]


@pytest.mark.asyncio
async def test_submitting_twice_is_idempotent(world):
    _seed_details(world)
    world["profiles"].append(_profile(state=st.PENDING_REVIEW,
                                      bundle_status="pending-review"))
    world["addresses"].append({"id": "addr-1", "tenant_id": TENANT, "iso_country": "IE",
                               "validated": True, "supporting_document_sid": DOC_SID,
                               "address_sid": ADDR_SID, "provider_account_sid": SUB})
    r = await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert r["ok"] and r["already_submitted"] is True


@pytest.mark.asyncio
async def test_a_changed_regulation_blocks_submission(world):
    """Submitting collected answers against a different regulation would file the
    wrong form."""
    world["twilio"].opts["regulations"] = [FakeRegulation(sid="RN_NEW")]
    world["profiles"].append(_profile())
    r = await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert r["status"] == engine.REQUIREMENTS_CHANGED
    assert r["regulation_sid"] == "RN_NEW"
    assert world["profiles"][0]["state"] == st.READY_TO_SUBMIT


@pytest.mark.asyncio
async def test_a_provider_failure_during_submission_returns_the_profile_for_retry(world):
    _seed_details(world)
    world["twilio"].opts["submit_error"] = ProviderError(code=20500, status=500)
    world["profiles"].append(_profile())
    world["addresses"].append({"id": "addr-1", "tenant_id": TENANT, "iso_country": "IE",
                               "validated": True, "supporting_document_sid": DOC_SID,
                               "address_sid": ADDR_SID, "provider_account_sid": SUB})
    r = await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert r["status"] == engine.PROVIDER_UNAVAILABLE
    assert world["profiles"][0]["state"] == st.READY_TO_SUBMIT, "must stay retryable"


# ── the whole preparation step ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prepare_builds_everything_once_and_is_resumable(world):
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    first = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert first["ok"]
    assert first["bundle_sid"] == BU_SID and first["end_user_sid"] == EU_SID
    assert first["supporting_document_sid"] == DOC_SID

    second = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert second["ok"]
    created = world["twilio"].created
    assert created["address"] == 1 and created["end_user"] == 1
    assert created["document"] == 1 and created["bundle"] == 1
    assert world["inserted_profiles"] == 1


@pytest.mark.asyncio
async def test_the_confirmed_declaration_is_supplied_by_the_system(world):
    """W9G.3. The customer never types these two values -- they are Twilio
    terminology about our commercial relationship, and Twilio Support confirmed the
    answer for exactly this context. The customer supplies facts about their
    business; OpenLines supplies the mapping of its own architecture."""
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    customer_only = {k: v for k, v in GOOD_ATTRS.items()
                     if k not in ("business_identity", "is_subassigned")}
    r = await engine.prepare_profile(tenant(), attributes=customer_only)
    assert r["ok"], r
    sent = world["twilio"].last_end_user_attributes
    assert sent["business_identity"] == "DIRECT_CUSTOMER"
    assert sent["is_subassigned"] == "NO"


@pytest.mark.asyncio
async def test_the_declaration_is_persisted_BEFORE_the_identity_is_filed(world):
    """Whatever the EndUser states must already be on our side, so a retry files the
    same thing and an audit can show what was declared."""
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    customer_only = {k: v for k, v in GOOD_ATTRS.items()
                     if k not in ("business_identity", "is_subassigned")}
    await engine.prepare_profile(tenant(), attributes=customer_only)
    stored = world["details"][0]
    assert stored["business_identity"] == "DIRECT_CUSTOMER"
    assert stored["is_subassigned"] == "NO"


@pytest.mark.asyncio
async def test_an_unconfirmed_CONTEXT_still_stops_before_any_provider_identity(world):
    """The block was never about these two field names -- it was about never filing
    an identity the regulation calls incomplete. Twilio answered for IE/local/
    business only, so a context it has not spoken about still fails closed."""
    world["twilio"].opts["regulations"] = [
        FakeRegulation(iso_country="GB", friendly_name="United Kingdom: Local - Business")]
    tn = tenant(business_country_code="GB")
    await engine.ensure_address(tn, submitted={**GOOD_ADDRESS, "postal_code": "SW1A 1AA"})
    customer_only = {k: v for k, v in GOOD_ATTRS.items()
                     if k not in ("business_identity", "is_subassigned")}
    r = await engine.prepare_profile(tn, attributes=customer_only)
    assert r["status"] == engine.DECLARATION_POLICY_UNRESOLVED
    assert r["context"] == "GB/local/business"
    assert r["details_stored"] is True
    created = world["twilio"].created
    assert created["end_user"] == 0 and created["document"] == 0 and created["bundle"] == 0
    profile = r["profile"]
    assert profile["state"] == st.DETAILS_REQUIRED
    assert not profile.get("end_user_sid") and not profile.get("bundle_sid")


@pytest.mark.asyncio
async def test_the_customers_answers_survive_an_unconfirmed_context(world):
    """They typed everything they can; a missing provider confirmation must not cost
    them their work."""
    world["twilio"].opts["regulations"] = [FakeRegulation(iso_country="GB")]
    tn = tenant(business_country_code="GB")
    await engine.ensure_address(tn, submitted={**GOOD_ADDRESS, "postal_code": "SW1A 1AA"})
    customer_only = {k: v for k, v in GOOD_ATTRS.items()
                     if k not in ("business_identity", "is_subassigned")}
    await engine.prepare_profile(tn, attributes=customer_only)
    stored = world["details"][0]
    assert stored["business_name"] == "DANI Ltd"
    assert stored["authorized_rep_email"] == "ann@dani.ie"
    assert stored.get("business_identity") is None
    assert stored.get("is_subassigned") is None


@pytest.mark.asyncio
async def test_a_regulation_that_no_longer_accepts_the_value_FAILS_CLOSED(world):
    """A support answer from the past is not licence to file a value the provider
    now rejects."""
    changed = {
        "end_user": [{**IE_REQUIREMENTS["end_user"][0],
                      "detailed_fields": [
                          {**d, "description": "Choose any one of the following "
                                               "values: [RESELLER, AGENCY]."}
                          if d["machine_name"] == "business_identity" else d
                          for d in IE_REQUIREMENTS["end_user"][0]["detailed_fields"]]}],
        "supporting_document": IE_REQUIREMENTS["supporting_document"]}
    world["twilio"].opts["regulations"] = [FakeRegulation(requirements=changed)]
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    # customer facts only -- the declaration is the system's to supply, and it is
    # the SYSTEM's value the changed regulation must reject.
    customer_only = {k: v for k, v in GOOD_ATTRS.items()
                     if k not in ("business_identity", "is_subassigned")}
    r = await engine.prepare_profile(tenant(), attributes=customer_only)
    assert r["status"] == engine.DECLARATION_REJECTED_BY_REGULATION
    assert "business_identity=DIRECT_CUSTOMER" in r["detail"]
    assert world["twilio"].created["end_user"] == 0


@pytest.mark.asyncio
async def test_a_regulation_that_drops_the_field_simply_omits_it(world):
    """Not every change is a failure: a field the provider stopped asking for is
    nothing to declare, and must not be sent."""
    dropped = {
        "end_user": [{**IE_REQUIREMENTS["end_user"][0],
                      "fields": [f for f in IE_REQUIREMENTS["end_user"][0]["fields"]
                                 if f != "is_subassigned"]}],
        "supporting_document": IE_REQUIREMENTS["supporting_document"]}
    world["twilio"].opts["regulations"] = [FakeRegulation(requirements=dropped)]
    # the provider now requires one field fewer, so the fake must too
    world["twilio"].opts["required_end_user_fields"] = tuple(
        dropped["end_user"][0]["fields"])
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["ok"], r
    sent = world["twilio"].last_end_user_attributes
    assert "is_subassigned" not in sent
    assert sent["business_identity"] == "DIRECT_CUSTOMER"


@pytest.mark.asyncio
async def test_an_already_declared_profile_keeps_its_historical_values(world):
    """A policy change later must not silently rewrite what an earlier filing
    actually declared to a regulator."""
    world["details"].append({"id": "det-1", "tenant_id": TENANT, "iso_country": "IE",
                             "end_user_type": "business",
                             "business_name": GOOD_ATTRS["business_name"],
                             "business_website": GOOD_ATTRS["business_website"],
                             "business_registration_number":
                                 GOOD_ATTRS["business_registration_number"],
                             "authorized_rep_first_name": GOOD_ATTRS["first_name"],
                             "authorized_rep_last_name": GOOD_ATTRS["last_name"],
                             "authorized_rep_email": GOOD_ATTRS["email"],
                             # what an earlier filing declared
                             "business_identity": "INDEPENDENT_SOFTWARE_VENDOR",
                             "is_subassigned": "YES"})
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes={})
    assert r["ok"], r
    sent = world["twilio"].last_end_user_attributes
    assert sent["business_identity"] == "INDEPENDENT_SOFTWARE_VENDOR"
    assert sent["is_subassigned"] == "YES"
    assert world["details"][0]["business_identity"] == "INDEPENDENT_SOFTWARE_VENDOR"


@pytest.mark.asyncio
async def test_prepare_refuses_before_the_address_is_validated(world):
    world["twilio"].opts["address_validated"] = False
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    assert r["status"] == engine.ADDRESS_VALIDATION_FAILED
    assert world["twilio"].created["bundle"] == 0


@pytest.mark.asyncio
async def test_an_out_of_enum_DECLARATION_from_a_customer_is_ignored_not_rejected(world):
    """W9G.3 changed this. The declaration fields are system-sourced, so a customer
    value for them is stripped before it reaches validation -- there is nothing to
    reject, and the policy's own value is filed instead. (A customer-supplied
    declaration being ignored is asserted directly in
    tests/test_w9g3_declaration_policy.py.)"""
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(
        tenant(), attributes={**GOOD_ATTRS, "business_identity": "RESELLER"})
    assert r["ok"], r
    assert world["twilio"].last_end_user_attributes["business_identity"] \
        == "DIRECT_CUSTOMER"


@pytest.mark.asyncio
async def test_the_enum_guard_still_protects_a_customer_facing_enum_field(world):
    """The guard is not dead code -- it still applies to any enum field the
    regulation asks the CUSTOMER to answer. Ireland currently has none, so this
    models a regulation that does."""
    with_enum = {
        "end_user": [{**IE_REQUIREMENTS["end_user"][0],
                      "fields": IE_REQUIREMENTS["end_user"][0]["fields"] + ["comments"],
                      "detailed_fields": [
                          {**d, "description": "Choose any one of the following "
                                               "values: [LTD, PLC]."}
                          if d["machine_name"] == "business_name" else d
                          for d in IE_REQUIREMENTS["end_user"][0]["detailed_fields"]]}],
        "supporting_document": IE_REQUIREMENTS["supporting_document"]}
    world["twilio"].opts["regulations"] = [FakeRegulation(requirements=with_enum)]
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    r = await engine.prepare_profile(
        tenant(), attributes={**GOOD_ATTRS, "business_name": "NOT_AN_OPTION"})
    assert r["status"] == engine.INVALID_CUSTOMER_DATA
    assert r["invalid_enum"] == ["business_name"]
    assert world["twilio"].created["end_user"] == 0


# ── no purchases, anywhere ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_whole_engine_never_purchases_a_number(world):
    await engine.ensure_address(tenant(), submitted=GOOD_ADDRESS)
    await engine.prepare_profile(tenant(), attributes=GOOD_ATTRS)
    await engine.evaluate_profile(tenant(), profile=world["profiles"][0])
    world["addresses"][0]["supporting_document_sid"] = DOC_SID
    await engine.submit_profile(tenant(), profile=world["profiles"][0])
    assert world["twilio"].purchases == 0


def test_no_module_in_the_w9g_path_calls_incoming_phone_numbers_create():
    """The fake raises if touched, but this asserts it statically too."""
    import pathlib
    root = pathlib.Path(engine.__file__).resolve().parent
    for name in ("regulatory_engine.py", "regulatory_requirements.py",
                 "regulatory_callback.py", "regulatory_reconcile.py",
                 "regulatory_ireland.py", "regulatory_state.py",
                 "business_country.py"):
        src = (root / name).read_text()
        assert "incoming_phone_numbers" not in src, name
