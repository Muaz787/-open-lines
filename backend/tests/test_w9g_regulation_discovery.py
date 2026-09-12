"""W9G — the Regulation API is the requirement authority, not a hardcoded field list.

Ireland's current nine fields are an OUTPUT of discovery. These tests use a fixture
that reproduces the live provider response verified in W9G, and separately prove the
engine adapts when the provider's shape changes -- which is the whole reason the
normalized model exists.
"""
import pytest

from services import regulatory_ireland as ie_ux
from services import regulatory_requirements as rq

IE_SID = "RN5b82d0c001b4ef265770d022986f794f"

#: Reproduces the live IE/local/business response re-verified in W9G.
IE_REQUIREMENTS = {
    "end_user": [{
        "requirement_name": "business_info", "name": "Business", "type": "business",
        "fields": ["business_name", "business_website", "business_registration_number",
                   "first_name", "last_name", "email", "business_identity",
                   "is_subassigned", "comments"],
        "detailed_fields": [
            {"machine_name": "business_name", "friendly_name": "Business Name",
             "description": ""},
            {"machine_name": "business_website", "friendly_name": "Business Website",
             "description": ""},
            {"machine_name": "business_registration_number",
             "friendly_name": "Business Registration Number",
             "description": "Please provide your Company Registration Number (CRN) "
                            "issued by the Companies Registration Office (CRO)."},
            {"machine_name": "first_name",
             "friendly_name": "Authorized Representative's First Name",
             "description": "Authorized representative should be a senior manager."},
            {"machine_name": "last_name",
             "friendly_name": "Authorized Representative's Last Name",
             "description": "Authorized representative should be a senior manager."},
            {"machine_name": "email",
             "friendly_name": "Authorized Representative's Contact Email",
             "description": ""},
            {"machine_name": "business_identity",
             "friendly_name": "Business Classification",
             "description": "Choose any one of the following values: "
                            "[DIRECT_CUSTOMER, INDEPENDENT_SOFTWARE_VENDOR]."},
            {"machine_name": "is_subassigned",
             "friendly_name": "Is this number being assigned to the end customer ?",
             "description": "Choose any one of the following values : [YES, NO]."},
            {"machine_name": "comments", "friendly_name": "Comments (Optional)",
             "description": "This is an optional field."},
        ],
    }],
    "supporting_document": [[{
        "requirement_name": "business_address_info", "name": "Proof of Address",
        "description": "Must include Eircode and be within locality or region "
                       "covered by the phone number's prefix.",
        "accepted_documents": [{
            "type": "business_address", "name": "Business address",
            "fields": ["address_sids"],
            "detailed_fields": [{"machine_name": "address_sids",
                                 "friendly_name": "Business Address sid",
                                 "constraint": "List"}],
        }],
    }]],
}


class FakeRegulation:
    def __init__(self, sid=IE_SID, requirements=None, iso_country="IE",
                 number_type="local", end_user_type="business",
                 friendly_name="Ireland: Local - Business"):
        self.sid = sid
        self.requirements = requirements if requirements is not None else IE_REQUIREMENTS
        self.iso_country = iso_country
        self.number_type = number_type
        self.end_user_type = end_user_type
        self.friendly_name = friendly_name


class FakeRegulations:
    def __init__(self, rows=None, error=None):
        self._rows, self._error = rows, error
        self.calls = []
    def list(self, **kw):
        self.calls.append(kw)
        if self._error:
            raise self._error
        return self._rows if self._rows is not None else [FakeRegulation()]


class FakeClient:
    def __init__(self, rows=None, error=None):
        self.regulations = FakeRegulations(rows, error)
        self.numbers = self
        self.v2 = self
        self.regulatory_compliance = self


# ── discovery outcomes are all distinguished ───────────────────────────────

@pytest.mark.asyncio
async def test_exact_regulation_is_discovered():
    c = FakeClient()
    r = await rq.discover_regulation(iso_country="IE", number_type="local",
                                     end_user_type="business", client=c)
    assert r.ok and r.status == rq.OK
    assert r.requirements.regulation_sid == IE_SID
    assert c.regulations.calls == [{"iso_country": "IE", "number_type": "local",
                                    "end_user_type": "business", "limit": 20}]


@pytest.mark.asyncio
async def test_zero_regulations_is_NOT_FOUND():
    r = await rq.discover_regulation(iso_country="ZZ", number_type="local",
                                     end_user_type="business",
                                     client=FakeClient(rows=[]))
    assert r.status == rq.NOT_FOUND and not r.ok


@pytest.mark.asyncio
async def test_multiple_regulations_is_AMBIGUOUS_never_a_guess():
    """Which regulation applies is a compliance decision, so two matches is a stop."""
    rows = [FakeRegulation(sid="RN1"), FakeRegulation(sid="RN2")]
    r = await rq.discover_regulation(iso_country="IE", number_type="local",
                                     end_user_type="business",
                                     client=FakeClient(rows=rows))
    assert r.status == rq.AMBIGUOUS
    assert r.requirements is None


@pytest.mark.asyncio
async def test_a_provider_outage_is_NOT_not_found():
    """Collapsing the two would tell a customer their country is unsupported because
    Twilio had a bad minute."""
    class Boom(Exception):
        status = 503
        code = 20500
    r = await rq.discover_regulation(iso_country="IE", number_type="local",
                                     end_user_type="business",
                                     client=FakeClient(error=Boom("down")))
    assert r.status == rq.UNAVAILABLE
    assert r.status != rq.NOT_FOUND
    assert "http=503" in r.detail
    assert "down" not in r.detail


@pytest.mark.asyncio
async def test_a_blank_country_is_refused_without_calling_the_provider():
    c = FakeClient()
    r = await rq.discover_regulation(iso_country="", number_type="local",
                                     end_user_type="business", client=c)
    assert r.status == rq.NOT_FOUND
    assert c.regulations.calls == []


@pytest.mark.asyncio
async def test_country_is_uppercased_for_the_provider():
    c = FakeClient()
    await rq.discover_regulation(iso_country="ie", number_type="local",
                                 end_user_type="business", client=c)
    assert c.regulations.calls[0]["iso_country"] == "IE"


# ── normalization ──────────────────────────────────────────────────────────

def test_the_nine_current_IE_fields_are_normalized_in_provider_order():
    reqs = rq.normalize_regulation(FakeRegulation())
    assert reqs.end_user_field_names == (
        "business_name", "business_website", "business_registration_number",
        "first_name", "last_name", "email", "business_identity",
        "is_subassigned", "comments")


def test_enum_options_are_parsed_from_the_providers_prose():
    reqs = rq.normalize_regulation(FakeRegulation())
    by = {f.name: f for f in reqs.end_user_fields}
    assert by["business_identity"].options == ("DIRECT_CUSTOMER",
                                              "INDEPENDENT_SOFTWARE_VENDOR")
    assert by["is_subassigned"].options == ("YES", "NO")
    assert by["business_name"].options == ()


def test_an_unparseable_enum_yields_no_options_rather_than_a_wrong_one():
    """Parsing prose is fragile, so failure must be safe: no options means free text."""
    assert rq._parse_options("no brackets here") == ()
    assert rq._parse_options("[only one]") == ()
    assert rq._parse_options("") == ()


def test_the_optional_comments_field_is_not_required():
    reqs = rq.normalize_regulation(FakeRegulation())
    by = {f.name: f for f in reqs.end_user_fields}
    assert by["comments"].required is False
    assert by["business_name"].required is True


def test_the_document_requirement_is_satisfied_by_address_sids():
    reqs = rq.normalize_regulation(FakeRegulation())
    assert len(reqs.documents) == 1
    doc = reqs.documents[0]
    assert doc.accepted_type == "business_address"
    assert [f.name for f in doc.fields] == ["address_sids"]
    assert doc.satisfied_by_address_sids is True


def test_a_document_needing_a_file_is_NOT_satisfied_by_address_sids():
    """This is what makes the engine stop rather than improvise file storage."""
    reqs = rq.normalize_regulation(FakeRegulation(requirements={
        "end_user": IE_REQUIREMENTS["end_user"],
        "supporting_document": [[{
            "requirement_name": "id_doc", "name": "Photo ID",
            "accepted_documents": [{"type": "passport", "fields": ["document_file"],
                                    "detailed_fields": []}]}]],
    }))
    assert reqs.documents[0].satisfied_by_address_sids is False


def test_a_field_the_provider_adds_later_flows_straight_through():
    """Nothing is filtered against an allow-list -- filtering would silently drop a
    new regulatory obligation."""
    payload = {"end_user": [{**IE_REQUIREMENTS["end_user"][0],
                             "fields": IE_REQUIREMENTS["end_user"][0]["fields"]
                                       + ["vat_number"],
                             "detailed_fields": IE_REQUIREMENTS["end_user"][0]["detailed_fields"]
                                       + [{"machine_name": "vat_number",
                                           "friendly_name": "VAT number",
                                           "description": ""}]}],
               "supporting_document": IE_REQUIREMENTS["supporting_document"]}
    reqs = rq.normalize_regulation(FakeRegulation(requirements=payload))
    assert "vat_number" in reqs.end_user_field_names
    ui = ie_ux.describe_fields(reqs)
    added = [f for f in ui if f["name"] == "vat_number"][0]
    # No friendly label written yet, so the provider's own label is used.
    assert added["label"] == "VAT number"
    assert added["source"] == ie_ux.CUSTOMER_SUPPLIED


def test_a_field_the_provider_removes_stops_being_asked_for():
    payload = {"end_user": [{**IE_REQUIREMENTS["end_user"][0],
                             "fields": ["business_name", "email"]}],
               "supporting_document": IE_REQUIREMENTS["supporting_document"]}
    reqs = rq.normalize_regulation(FakeRegulation(requirements=payload))
    assert reqs.end_user_field_names == ("business_name", "email")
    assert [f["name"] for f in ie_ux.describe_fields(reqs)] == ["business_name", "email"]


def test_an_empty_provider_payload_does_not_crash():
    reqs = rq.normalize_regulation(FakeRegulation(requirements={}))
    assert reqs.end_user_fields == () and reqs.documents == ()


# ── drift fingerprint ──────────────────────────────────────────────────────

def test_the_fingerprint_is_stable_for_identical_requirements():
    a = rq.normalize_regulation(FakeRegulation())
    b = rq.normalize_regulation(FakeRegulation())
    assert a.fingerprint() == b.fingerprint()


def test_a_changed_field_list_changes_the_fingerprint():
    """The regulation SID alone is not enough: Twilio can alter a regulation's fields
    without reissuing it, and submitting stale answers would file the wrong form."""
    base = rq.normalize_regulation(FakeRegulation())
    changed = rq.normalize_regulation(FakeRegulation(requirements={
        "end_user": [{**IE_REQUIREMENTS["end_user"][0],
                      "fields": IE_REQUIREMENTS["end_user"][0]["fields"] + ["vat_number"]}],
        "supporting_document": IE_REQUIREMENTS["supporting_document"]}))
    assert base.fingerprint() != changed.fingerprint()


def test_a_changed_document_requirement_changes_the_fingerprint():
    base = rq.normalize_regulation(FakeRegulation())
    changed = rq.normalize_regulation(FakeRegulation(requirements={
        "end_user": IE_REQUIREMENTS["end_user"],
        "supporting_document": [[{"requirement_name": "id", "name": "ID",
                                  "accepted_documents": [
                                      {"type": "passport", "fields": ["document_file"]}]}]]}))
    assert base.fingerprint() != changed.fingerprint()


# ── IE UX mapping ──────────────────────────────────────────────────────────

def test_the_ireland_mapping_gives_every_current_field_a_friendly_label():
    reqs = rq.normalize_regulation(FakeRegulation())
    for f in ie_ux.describe_fields(reqs):
        assert f["label"] and f["label"] != f["name"]
        assert f["help"]


def test_the_two_declaration_fields_are_marked_unresolved_and_operator_supplied():
    """business_identity and is_subassigned are a compliance declaration about the
    OpenLines/tenant relationship. W9G re-read Twilio's current docs and the two enum
    values remain ambiguous, so they are never pre-filled with a guess."""
    reqs = rq.normalize_regulation(FakeRegulation())
    ui = {f["name"]: f for f in ie_ux.describe_fields(reqs)}
    for name in ("business_identity", "is_subassigned"):
        assert ui[name]["source"] == ie_ux.OPERATOR_SUPPLIED
        assert ui[name]["resolved"] is False
        assert ui[name]["state"] == ie_ux.UNRESOLVED
    for name in ("business_name", "email", "first_name"):
        assert ui[name]["source"] == ie_ux.CUSTOMER_SUPPLIED
        assert ui[name]["resolved"] is True


def test_the_providers_own_words_are_always_carried_through():
    """So a UI can show them verbatim and nobody has to trust our paraphrase."""
    reqs = rq.normalize_regulation(FakeRegulation())
    ui = {f["name"]: f for f in ie_ux.describe_fields(reqs)}
    assert "Companies Registration Office" in ui["business_registration_number"]["provider_description"]
    assert ui["business_identity"]["provider_label"] == "Business Classification"


def test_missing_required_fields_are_reported_in_provider_order():
    reqs = rq.normalize_regulation(FakeRegulation())
    missing = ie_ux.missing_fields(reqs, {"business_name": "DANI", "email": "a@b.c"})
    assert missing[0] == "business_website"
    assert "comments" not in missing            # optional
    assert "business_name" not in missing


def test_whitespace_is_not_a_supplied_value():
    reqs = rq.normalize_regulation(FakeRegulation())
    assert "business_name" in ie_ux.missing_fields(reqs, {"business_name": "   "})


def test_a_value_outside_the_providers_enum_is_reported():
    reqs = rq.normalize_regulation(FakeRegulation())
    assert ie_ux.invalid_enum_fields(reqs, {"business_identity": "RESELLER"}) \
        == ["business_identity"]
    assert ie_ux.invalid_enum_fields(reqs, {"business_identity": "DIRECT_CUSTOMER"}) == []


def test_unresolved_declarations_are_reported_only_when_the_regulation_asks_for_them():
    reqs = rq.normalize_regulation(FakeRegulation())
    assert ie_ux.unresolved_declarations(reqs, {}) == ["business_identity", "is_subassigned"]
    assert ie_ux.unresolved_declarations(
        reqs, {"business_identity": "DIRECT_CUSTOMER"}) == ["is_subassigned"]
    assert ie_ux.unresolved_declarations(
        reqs, {"business_identity": "DIRECT_CUSTOMER", "is_subassigned": "NO"}) == []
    # A regulation that does not ask for them produces nothing to resolve.
    no_decl = rq.normalize_regulation(FakeRegulation(requirements={
        "end_user": [{**IE_REQUIREMENTS["end_user"][0], "fields": ["business_name"]}],
        "supporting_document": []}))
    assert ie_ux.unresolved_declarations(no_decl, {}) == []
