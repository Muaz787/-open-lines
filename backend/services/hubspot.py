"""
HubSpot CRM integration service for Open Lines.

Provides OAuth helpers, contact sync, and call-note creation via the
HubSpot CRM v3 API. Designed to be called non-fatally from the webhook
processor after every call.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_TOKEN_URL  = "https://api.hubapi.com/oauth/v1/token"
_TOKEN_INFO = "https://api.hubapi.com/oauth/v1/access-tokens"
_CRM_BASE   = "https://api.hubapi.com/crm/v3/objects"

_SCOPES = (
    "crm.objects.contacts.read "
    "crm.objects.contacts.write"
)


class HubSpotTokenError(Exception):
    """HubSpot token is missing, revoked, or cannot be refreshed."""


def _env() -> tuple[str, str, str]:
    client_id     = os.getenv("HUBSPOT_CLIENT_ID", "")
    client_secret = os.getenv("HUBSPOT_CLIENT_SECRET", "")
    redirect_uri  = os.getenv("HUBSPOT_REDIRECT_URI", "")
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError(
            "HUBSPOT_CLIENT_ID, HUBSPOT_CLIENT_SECRET, and HUBSPOT_REDIRECT_URI must be set"
        )
    return client_id, client_secret, redirect_uri


def build_auth_url(state: str) -> str:
    """`state` is the opaque OAuth state nonce (no longer the raw tenant_id)."""
    client_id, _, redirect_uri = _env()
    params = {
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "scope":         _SCOPES,
        "state":         state,
    }
    return f"https://app.hubspot.com/oauth/authorize?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    client_id, client_secret, redirect_uri = _env()
    async with httpx.AsyncClient() as http:
        res = await http.post(
            _TOKEN_URL,
            data={
                "grant_type":    "authorization_code",
                "client_id":     client_id,
                "client_secret": client_secret,
                "redirect_uri":  redirect_uri,
                "code":          code,
            },
            timeout=15.0,
        )
        res.raise_for_status()
        return res.json()


async def _do_refresh(refresh_token: str) -> dict:
    client_id, client_secret, redirect_uri = _env()
    async with httpx.AsyncClient() as http:
        res = await http.post(
            _TOKEN_URL,
            data={
                "grant_type":    "refresh_token",
                "client_id":     client_id,
                "client_secret": client_secret,
                "redirect_uri":  redirect_uri,
                "refresh_token": refresh_token,
            },
            timeout=15.0,
        )
        if res.status_code in (400, 401):
            raise HubSpotTokenError(f"HubSpot token refresh failed: {res.text[:200]}")
        res.raise_for_status()
        return res.json()


async def get_valid_access_token(tenant: dict) -> str:
    """Return a valid HubSpot access token for this tenant.

    Refreshes automatically when the stored token is within 60 seconds of
    expiry, then persists the new tokens to Supabase.
    """
    from db import supabase as db_mod

    access_token = tenant.get("hubspot_access_token", "")
    expires_at   = tenant.get("hubspot_token_expires_at")

    # Use the cached token if it's still fresh
    if access_token and expires_at:
        try:
            exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < exp - timedelta(seconds=60):
                return access_token
        except Exception:
            pass

    refresh_token = tenant.get("hubspot_refresh_token", "")
    if not refresh_token:
        raise HubSpotTokenError("No HubSpot refresh token stored for this tenant")

    tokens       = await _do_refresh(refresh_token)
    new_access   = tokens["access_token"]
    new_refresh  = tokens.get("refresh_token") or refresh_token
    expires_in   = int(tokens.get("expires_in", 1800))
    new_expiry   = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    await db_mod.update_tenant(tenant["id"], {
        "hubspot_access_token":    new_access,
        "hubspot_refresh_token":   new_refresh,
        "hubspot_token_expires_at": new_expiry,
    })
    logger.info("HubSpot token refreshed for tenant %s", tenant.get("id", "?")[:8])
    return new_access


async def get_account_info(access_token: str) -> dict:
    """Return portal/account info from HubSpot's token-info endpoint."""
    async with httpx.AsyncClient() as http:
        res = await http.get(
            f"{_TOKEN_INFO}/{access_token}",
            timeout=10.0,
        )
        res.raise_for_status()
        return res.json()


async def search_contact_by_phone(access_token: str, phone: str) -> str | None:
    """Return the HubSpot contact ID for this phone number, or None."""
    async with httpx.AsyncClient() as http:
        res = await http.post(
            f"{_CRM_BASE}/contacts/search",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={
                "filterGroups": [{
                    "filters": [{"propertyName": "phone", "operator": "EQ", "value": phone}]
                }],
                "properties": ["phone", "firstname", "lastname"],
                "limit": 1,
            },
            timeout=10.0,
        )
        if res.status_code != 200:
            return None
        results = res.json().get("results", [])
        return results[0]["id"] if results else None


async def create_contact(access_token: str, phone: str, name: str | None = None) -> str:
    """Create a HubSpot contact and return the new contact ID."""
    props: dict = {"phone": phone}
    if name:
        parts = name.strip().split(" ", 1)
        props["firstname"] = parts[0]
        if len(parts) > 1:
            props["lastname"] = parts[1]

    async with httpx.AsyncClient() as http:
        res = await http.post(
            f"{_CRM_BASE}/contacts",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"properties": props},
            timeout=10.0,
        )
        res.raise_for_status()
        return res.json()["id"]


async def update_contact(access_token: str, contact_id: str, props: dict) -> None:
    """Update properties on an existing HubSpot contact."""
    async with httpx.AsyncClient() as http:
        res = await http.patch(
            f"{_CRM_BASE}/contacts/{contact_id}",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"properties": props},
            timeout=10.0,
        )
        if res.status_code not in (200, 204):
            logger.warning("HubSpot update_contact %s returned %s", contact_id, res.status_code)


async def create_note_for_contact(access_token: str, contact_id: str, body: str) -> None:
    """Create a HubSpot note and associate it with a contact in one call."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with httpx.AsyncClient() as http:
        res = await http.post(
            f"{_CRM_BASE}/notes",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={
                "properties": {
                    "hs_note_body": body,
                    "hs_timestamp": ts,
                },
                "associations": [{
                    "to": {"id": contact_id},
                    "types": [{
                        "associationCategory": "HUBSPOT_DEFINED",
                        "associationTypeId": 202,
                    }],
                }],
            },
            timeout=10.0,
        )
        if res.status_code not in (200, 201):
            logger.warning("HubSpot create_note for contact %s returned %s", contact_id, res.status_code)


def _build_note_body(caller_phone: str, analysis: dict, call_id: str) -> str:
    """Build a safe, structured note body — no full transcript, no tokens."""
    urgency   = analysis.get("urgency", "unknown")
    summary   = analysis.get("summary", "No summary available.")
    next_step = analysis.get("suggested_next_step", "")
    date_str  = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

    # Detect whether an appointment was booked from key_details
    key_details: dict = analysis.get("key_details") or {}
    appt_booked = any(
        "appointment" in str(v).lower() or "book" in str(v).lower()
        for v in key_details.values()
    )
    appt_line = "Yes" if appt_booked else "No"

    lines = [
        f"📞 Call Summary — Open Lines AI",
        f"Date: {date_str}",
        f"Caller phone: {caller_phone}" if caller_phone else "",
        f"Urgency: {urgency.title()}",
        f"Appointment booked: {appt_line}",
        "",
        f"Summary: {summary}",
    ]
    if next_step:
        lines.append(f"Suggested next step: {next_step}")
    if key_details:
        lines.append("")
        lines.append("Key details:")
        for k, v in key_details.items():
            lines.append(f"  • {k.replace('_', ' ').title()}: {v}")

    return "\n".join(l for l in lines if l is not None)


async def sync_call_to_hubspot(
    tenant: dict,
    caller_phone: str,
    caller_name: str | None,
    analysis: dict,
    call_id: str,
) -> None:
    """Create/update a HubSpot contact and add a call-summary note.

    Non-fatal: all errors are caught by the caller (webhook_processor).
    """
    if not caller_phone:
        logger.info("HubSpot sync skipped — no caller phone (call %s)", call_id)
        return

    access_token = await get_valid_access_token(tenant)

    # Find existing contact by phone, or create one
    contact_id = await search_contact_by_phone(access_token, caller_phone)
    if contact_id:
        # Update name if we extracted one and it's new
        if caller_name:
            parts = caller_name.strip().split(" ", 1)
            update_props: dict = {"firstname": parts[0]}
            if len(parts) > 1:
                update_props["lastname"] = parts[1]
            await update_contact(access_token, contact_id, update_props)
        logger.info("HubSpot: found existing contact %s for call %s", contact_id[:8], call_id)
    else:
        contact_id = await create_contact(access_token, caller_phone, caller_name)
        logger.info("HubSpot: created contact %s for call %s", contact_id[:8], call_id)

    # Add the call-summary note
    note_body = _build_note_body(caller_phone, analysis, call_id)
    await create_note_for_contact(access_token, contact_id, note_body)
    logger.info("HubSpot: note added to contact %s (call %s)", contact_id[:8], call_id)
