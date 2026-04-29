"""
Tests for provision_tenant().

All external API calls are mocked so the suite runs without
real credentials — no Twilio, Vapi, Firecrawl, Pinecone, or
Supabase keys are required.
"""
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


async def test_provision_tenant_realtor_happy_path():
    """Full provision_tenant() run for a realtor — all external calls mocked."""

    mock_create_subaccount     = AsyncMock(return_value={"sid": FAKE_SUBACCOUNT_SID, "auth_token": FAKE_SUBACCOUNT_TOKEN})
    mock_find_available_number = AsyncMock(return_value=FAKE_PHONE_NUMBER)
    mock_purchase_number       = AsyncMock(return_value=FAKE_PHONE_NUMBER)
    mock_scrape_website        = AsyncMock(return_value="Test Realty offers premium homes in Toronto.")
    mock_embed_and_store       = AsyncMock(return_value=12)
    mock_build_config          = MagicMock(return_value={"name": "Alex", "model": {}})
    mock_create_assistant      = AsyncMock(return_value=FAKE_ASSISTANT_ID)
    mock_insert_tenant         = AsyncMock(return_value=FAKE_TENANT_ROW)

    with (
        patch("services.telephony.create_subaccount",     mock_create_subaccount),
        patch("services.telephony.find_available_number", mock_find_available_number),
        patch("services.telephony.purchase_number",       mock_purchase_number),
        patch("services.knowledge.scrape_website",        mock_scrape_website),
        patch("services.knowledge.embed_and_store",       mock_embed_and_store),
        patch("services.vapi.build_assistant_config",     mock_build_config),
        patch("services.vapi.create_assistant",           mock_create_assistant),
        patch("db.supabase.insert_tenant",                mock_insert_tenant),
    ):
        result = await provision_tenant(REALTOR_PAYLOAD)

    # Core return value assertions
    assert result["tenant_id"]    == FAKE_TENANT_ID
    assert result["phone_number"] == FAKE_PHONE_NUMBER
    assert result["assistant_id"] == FAKE_ASSISTANT_ID
    assert result["status"]       == "live"
    assert "dashboard_url" in result
    assert FAKE_TENANT_ID in result["dashboard_url"]

    # Every external service was called exactly once
    mock_create_subaccount.assert_awaited_once_with("Test Realty")
    mock_find_available_number.assert_awaited_once_with(FAKE_SUBACCOUNT_SID, FAKE_SUBACCOUNT_TOKEN)
    mock_purchase_number.assert_awaited_once_with(FAKE_SUBACCOUNT_SID, FAKE_SUBACCOUNT_TOKEN, FAKE_PHONE_NUMBER)
    mock_scrape_website.assert_awaited_once_with("https://fake-test-realty.example.com")
    mock_embed_and_store.assert_awaited_once()
    mock_create_assistant.assert_awaited_once()
    mock_insert_tenant.assert_awaited_once()

    # Supabase insert received the right fields
    inserted = mock_insert_tenant.call_args[0][0]
    assert inserted["business_name"]       == "Test Realty"
    assert inserted["industry"]            == "realtor"
    assert inserted["twilio_phone_number"] == FAKE_PHONE_NUMBER
    assert inserted["vapi_assistant_id"]   == FAKE_ASSISTANT_ID
    assert inserted["pinecone_namespace"]  == "test-realty"
    assert inserted["is_active"]           is True
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
        patch("services.telephony.purchase_number",       AsyncMock(return_value=FAKE_PHONE_NUMBER)),
        patch("services.knowledge.scrape_website",        mock_scrape),
        patch("services.knowledge.embed_and_store",       mock_embed),
        patch("services.vapi.build_assistant_config",     MagicMock(return_value={})),
        patch("services.vapi.create_assistant",           AsyncMock(return_value=FAKE_ASSISTANT_ID)),
        patch("db.supabase.insert_tenant",                AsyncMock(return_value={"id": FAKE_TENANT_ID})),
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

    with (
        patch("services.telephony.create_subaccount",     AsyncMock(return_value={"sid": FAKE_SUBACCOUNT_SID, "auth_token": FAKE_SUBACCOUNT_TOKEN})),
        patch("services.telephony.find_available_number", AsyncMock(return_value=FAKE_PHONE_NUMBER)),
        patch("services.telephony.purchase_number",       AsyncMock(return_value=FAKE_PHONE_NUMBER)),
        patch("services.knowledge.scrape_website",        AsyncMock(return_value="")),
        patch("services.knowledge.embed_and_store",       AsyncMock(return_value=0)),
        patch("services.vapi.build_assistant_config",     MagicMock(return_value={})),
        patch("services.vapi.create_assistant",           AsyncMock(return_value=FAKE_ASSISTANT_ID)),
        patch("db.supabase.insert_tenant",                AsyncMock(return_value={"id": FAKE_TENANT_ID})) as mock_insert,
    ):
        await provision_tenant(payload)

    inserted = mock_insert.call_args[0][0]
    namespace = inserted["pinecone_namespace"]
    assert " " not in namespace, "namespace must not contain spaces"
    assert namespace == namespace.lower(), "namespace must be lowercase"
    assert namespace.startswith("shahid"), "namespace must start with the business name"
