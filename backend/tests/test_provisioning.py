"""
Tests for provision_tenant().

All external API calls are mocked so the suite runs without
real credentials — no Twilio, Vapi, Firecrawl, Pinecone, or
Supabase keys are required.
"""
import contextlib
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Put the backend package root on sys.path before any project imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Module-level imports trigger sub-module registration on their parent packages,
# which is required for patch() to resolve dotted names like "services.telephony".
from services import telephony as _telephony_mod          # noqa: F401
from services import vapi as _vapi_mod                    # noqa: F401
from services import knowledge as _knowledge_mod          # noqa: F401
from services.provisioning import provision_tenant        # noqa: F401
import db.supabase as _supabase_mod                       # noqa: F401

FAKE_SUBACCOUNT_SID   = "AC_test_subaccount_sid"
FAKE_SUBACCOUNT_TOKEN = "test_subaccount_auth_token"
FAKE_PHONE_NUMBER     = "+14165550100"
FAKE_ASSISTANT_ID     = "vapi-assistant-test-id"
FAKE_TENANT_ID        = "00000000-0000-0000-0000-000000000001"
FAKE_NUMBER_SID       = "PN_test_number_sid"

REALTOR_PAYLOAD = {
    "business_name":   "Test Realty",
    "industry":        "realtor",
    "owner_name":      "Test Owner",
    "whatsapp_number": "+14165550199",
    "website_url":     "https://fake-test-realty.example.com",
    "agent_name":      "Alex",
}

FAKE_TENANT_ROW = {
    "id":                  FAKE_TENANT_ID,
    "business_name":       "Test Realty",
    "industry":            "realtor",
    "twilio_phone_number": FAKE_PHONE_NUMBER,
    "vapi_assistant_id":   FAKE_ASSISTANT_ID,
    "pinecone_namespace":  "test-realty",
    "is_active":           True,
}


# ── W9I-B ──────────────────────────────────────────────────────────────────
# provision_tenant now creates the tenant BEFORE any provider work and records
# the number in tenant_phone_numbers as well as the legacy scalar. These patches
# model both. They are fakes of the DATA LAYER, not of provisioning's decisions:
# if the canonical write were removed, `registered` would stay empty and the
# assertions below would fail.

def _w9ib_patches(registered: list, activated: list, seen: dict | None = None,
                  tenant_row: dict | None = None):
    row = dict(tenant_row or FAKE_TENANT_ROW)

    async def _insert_tenant(data):
        if seen is not None:
            seen.update(data)
        return {**row, **data, "id": FAKE_TENANT_ID}

    async def _update_tenant(tid, patch):
        # The tenant is created at Step 0 and completed at Step 12, so what the
        # tenant ENDS UP with is the union of both writes -- which is what the
        # assertions below should check, not which call happened to carry a field.
        if seen is not None:
            seen.update(patch)
        row.update(patch)
        return {**row, "id": tid}

    async def _register(**kw):
        registered.append(kw)
        return {"status": "ok",
                "row": {"id": "phone-row-1", **kw},
                "created": True}

    async def _mark_active(**kw):
        activated.append(kw)
        return {"status": "ok", "row": {"id": kw["number_row_id"],
                                        "status": "active"}}

    stack = contextlib.ExitStack()
    for cm in (
        patch("db.supabase.insert_tenant", AsyncMock(side_effect=_insert_tenant)),
        patch("db.supabase.update_tenant", AsyncMock(side_effect=_update_tenant)),
        patch("services.phone_registry.register_permanent",
              AsyncMock(side_effect=_register)),
        patch("services.phone_registry.mark_active",
              AsyncMock(side_effect=_mark_active)),
    ):
        stack.enter_context(cm)
    return stack

async def test_provision_tenant_realtor_happy_path():
    """Full provision_tenant() run for a realtor — all external calls mocked."""

    mock_create_subaccount     = AsyncMock(return_value={"sid": FAKE_SUBACCOUNT_SID, "auth_token": FAKE_SUBACCOUNT_TOKEN})
    mock_find_available_number = AsyncMock(return_value=FAKE_PHONE_NUMBER)
    # W9I-B: provisioning now needs the provider SID for the canonical row.
    mock_purchase_number       = AsyncMock(return_value=(FAKE_PHONE_NUMBER, FAKE_NUMBER_SID))
    mock_scrape_website        = AsyncMock(return_value="Test Realty offers premium homes in Toronto.")
    mock_embed_and_store       = AsyncMock(return_value=12)
    mock_build_config          = MagicMock(return_value={"name": "Alex", "model": {}})
    mock_create_assistant      = AsyncMock(return_value=FAKE_ASSISTANT_ID)
    registered: list = []
    activated: list = []
    seen: dict = {}

    with (
        _w9ib_patches(registered, activated, seen),
        patch("services.telephony.create_subaccount",     mock_create_subaccount),
        patch("services.telephony.find_available_number", mock_find_available_number),
        patch("services.telephony.purchase_number_with_sid", mock_purchase_number),
        patch("services.knowledge.scrape_website",        mock_scrape_website),
        patch("services.knowledge.embed_and_store",       mock_embed_and_store),
        patch("services.vapi.build_assistant_config",     mock_build_config),
        patch("services.vapi.create_assistant",           mock_create_assistant),
        patch("services.vapi.import_twilio_number",        AsyncMock(return_value="fake_vapi_phone_id")),
    ):
        result = await provision_tenant({**REALTOR_PAYLOAD, "country": "CA"})

    # Core return value assertions
    assert result["tenant_id"]    == FAKE_TENANT_ID
    assert result["phone_number"] == FAKE_PHONE_NUMBER
    assert result["assistant_id"] == FAKE_ASSISTANT_ID
    assert result["status"]       == "live"
    assert "dashboard_url" in result
    assert FAKE_TENANT_ID in result["dashboard_url"]

    # Every external service was called exactly once
    mock_create_subaccount.assert_awaited_once_with("Test Realty")
    # find_available_number also takes country + optional preferred area code;
    # assert it ran once with the subaccount creds, tolerant of the extra args.
    mock_find_available_number.assert_awaited_once()
    assert mock_find_available_number.call_args.args[:2] == (FAKE_SUBACCOUNT_SID, FAKE_SUBACCOUNT_TOKEN)
    mock_purchase_number.assert_awaited_once_with(FAKE_SUBACCOUNT_SID, FAKE_SUBACCOUNT_TOKEN, FAKE_PHONE_NUMBER)
    mock_scrape_website.assert_awaited_once_with("https://fake-test-realty.example.com")
    mock_embed_and_store.assert_awaited_once()
    mock_create_assistant.assert_awaited_once()

    assert registered[0]["provider_sid"] == FAKE_NUMBER_SID
    # W9I-B: the canonical row is written, and only made routable afterwards.
    assert len(registered) == 1, "the canonical phone row was not written"
    assert registered[0]["e164"] == FAKE_PHONE_NUMBER
    assert registered[0]["provider_account_sid"] == FAKE_SUBACCOUNT_SID
    assert registered[0]["iso_country"] == "CA"
    assert len(activated) == 1, "the number was never marked active"
    assert activated[0]["e164"] == FAKE_PHONE_NUMBER

    # The tenant ends up with the right fields, across Step 0 + Step 12.
    inserted = seen
    assert inserted["business_name"]       == "Test Realty"
    assert inserted["industry"]            == "realtor"
    # twilio_phone_number is now mirrored by phone_registry.mark_active -- the one
    # path that owns both the canonical row and the legacy scalar -- so it is
    # asserted through `activated` above rather than here.
    assert inserted["vapi_assistant_id"]   == FAKE_ASSISTANT_ID
    assert inserted["pinecone_namespace"]  == "test-realty"
    assert inserted["is_active"]           is True
    assert inserted["business_country_code"] == "CA", \
        "the explicit signup country must be captured as the compliance country"
    assert inserted["onboarding_state"]    == "active"
    assert "qualification_fields" in inserted
    assert set(inserted["qualification_fields"].keys()) == {"budget", "pre_approved", "timeline"}


async def test_provision_tenant_skips_scrape_when_no_website():
    """When website_url is empty, scrape_website and embed_and_store must not be called."""

    payload = {**REALTOR_PAYLOAD, "website_url": ""}
    mock_scrape  = AsyncMock()
    mock_embed   = AsyncMock(return_value=0)

    with (
        patch("services.telephony.create_subaccount",     AsyncMock(return_value={"sid": FAKE_SUBACCOUNT_SID, "auth_token": FAKE_SUBACCOUNT_TOKEN})),
        patch("services.telephony.find_available_number", AsyncMock(return_value=FAKE_PHONE_NUMBER)),
        patch("services.telephony.purchase_number_with_sid",
              AsyncMock(return_value=(FAKE_PHONE_NUMBER, FAKE_NUMBER_SID))),
        patch("services.knowledge.scrape_website",        mock_scrape),
        patch("services.knowledge.embed_and_store",       mock_embed),
        patch("services.vapi.build_assistant_config",     MagicMock(return_value={})),
        patch("services.vapi.create_assistant",           AsyncMock(return_value=FAKE_ASSISTANT_ID)),
        patch("services.vapi.import_twilio_number",        AsyncMock(return_value="fake_vapi_phone_id")),
        _w9ib_patches([], []),
    ):
        result = await provision_tenant(payload)

    mock_scrape.assert_not_awaited()
    mock_embed.assert_not_awaited()
    assert result["status"] == "live"


async def test_provision_tenant_raises_on_twilio_failure():
    """A Twilio failure at step 3 must surface as HTTPException 500."""
    from fastapi import HTTPException

    with (
        patch("services.telephony.create_subaccount",     AsyncMock(side_effect=RuntimeError("Twilio down"))),
        patch("services.knowledge.scrape_website",        AsyncMock()),
        patch("services.vapi.create_assistant",           AsyncMock()),
        patch("db.supabase.insert_tenant",                AsyncMock()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await provision_tenant(REALTOR_PAYLOAD)

    assert exc_info.value.status_code == 500
    assert "Step 3" in exc_info.value.detail


async def test_provision_tenant_namespace_slugified():
    """Business names with spaces, mixed case, and special chars produce a clean namespace."""

    payload = {**REALTOR_PAYLOAD, "business_name": "Shahid's Real Estate & Co."}
    seen: dict = {}

    with (
        patch("services.telephony.create_subaccount",     AsyncMock(return_value={"sid": FAKE_SUBACCOUNT_SID, "auth_token": FAKE_SUBACCOUNT_TOKEN})),
        patch("services.telephony.find_available_number", AsyncMock(return_value=FAKE_PHONE_NUMBER)),
        patch("services.telephony.purchase_number_with_sid",
              AsyncMock(return_value=(FAKE_PHONE_NUMBER, FAKE_NUMBER_SID))),
        patch("services.knowledge.scrape_website",        AsyncMock(return_value="")),
        patch("services.knowledge.embed_and_store",       AsyncMock(return_value=0)),
        patch("services.vapi.build_assistant_config",     MagicMock(return_value={})),
        patch("services.vapi.create_assistant",           AsyncMock(return_value=FAKE_ASSISTANT_ID)),
        patch("services.vapi.import_twilio_number",        AsyncMock(return_value="fake_vapi_phone_id")),
        _w9ib_patches([], [], seen),
    ):
        await provision_tenant(payload)

    inserted = seen
    namespace = inserted["pinecone_namespace"]
    assert " " not in namespace, "namespace must not contain spaces"
    assert namespace == namespace.lower(), "namespace must be lowercase"
    assert namespace.startswith("shahid"), "namespace must start with the business name"
