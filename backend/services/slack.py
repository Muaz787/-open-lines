"""
Slack integration service for Open Lines.

Uses the Incoming Webhooks OAuth flow (scope: incoming-webhook).
After every call, posts a structured summary to the tenant's chosen channel.
"""

import os
import logging
from urllib.parse import urlencode
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
_TOKEN_URL     = "https://slack.com/api/oauth.v2.access"


def _env() -> tuple[str, str, str]:
    client_id     = os.getenv("SLACK_CLIENT_ID", "")
    client_secret = os.getenv("SLACK_CLIENT_SECRET", "")
    redirect_uri  = os.getenv("SLACK_REDIRECT_URI", "")
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError(
            "SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, and SLACK_REDIRECT_URI must be set"
        )
    return client_id, client_secret, redirect_uri


def build_auth_url(state: str) -> str:
    """`state` is the opaque OAuth state nonce (no longer the raw tenant_id)."""
    client_id, _, redirect_uri = _env()
    params = {
        "client_id":    client_id,
        "scope":        "incoming-webhook",
        "redirect_uri": redirect_uri,
        "state":        state,
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """Exchange OAuth code for tokens. Returns the full Slack response dict."""
    client_id, client_secret, redirect_uri = _env()
    async with httpx.AsyncClient() as http:
        res = await http.post(
            _TOKEN_URL,
            data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "redirect_uri":  redirect_uri,
                "code":          code,
            },
            timeout=15.0,
        )
        res.raise_for_status()
        data = res.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack OAuth error: {data.get('error', 'unknown')}")
        return data


async def post_call_summary(
    webhook_url: str,
    business_name: str,
    analysis: dict,
    caller_number: str,
) -> None:
    """Post a structured call summary to a Slack channel via incoming webhook."""
    urgency     = (analysis.get("urgency") or "unknown").lower()
    caller_name = analysis.get("caller_name") or "Unknown caller"
    summary     = analysis.get("summary") or "No summary available."
    next_step   = analysis.get("suggested_next_step") or ""
    key_details: dict = analysis.get("key_details") or {}
    date_str    = datetime.now(timezone.utc).strftime("%b %d, %Y · %I:%M %p UTC")

    urgency_emoji = {"hot": "🔴", "warm": "🟡", "cold": "🔵"}.get(urgency, "⚪")

    appt_booked = any(
        "appointment" in str(v).lower() or "book" in str(v).lower()
        for v in key_details.values()
    )

    fields = [
        {"type": "mrkdwn", "text": f"*Caller*\n{caller_name}"},
        {"type": "mrkdwn", "text": f"*Phone*\n{caller_number or '—'}"},
        {"type": "mrkdwn", "text": f"*Urgency*\n{urgency_emoji} {urgency.title()}"},
        {"type": "mrkdwn", "text": f"*Appointment*\n{'✅ Booked' if appt_booked else '—'}"},
    ]

    detail_lines = "\n".join(
        f"• *{k.replace('_', ' ').title()}:* {v}" for k, v in key_details.items()
    ) if key_details else ""

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📞 New Call — {business_name}", "emoji": True},
        },
        {
            "type": "section",
            "fields": fields,
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary*\n{summary}"},
        },
    ]

    if next_step:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Suggested next step*\n{next_step}"},
        })

    if detail_lines:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Key details*\n{detail_lines}"},
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Open Lines AI · {date_str}"}],
    })

    async with httpx.AsyncClient() as http:
        res = await http.post(webhook_url, json={"blocks": blocks}, timeout=10.0)
        if res.status_code != 200 or res.text != "ok":
            logger.warning("Slack webhook post returned %s: %s", res.status_code, res.text[:200])
