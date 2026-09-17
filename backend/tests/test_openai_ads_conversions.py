"""
OpenAI/ChatGPT Ads server-side Conversions API (services/openai_ads.py).

Load-bearing behaviour:
  * no key configured -> no request at all (safe until the key is set);
  * with a key -> a correct POST: pixel id in the query, Bearer auth, the event
    id (the dedup key shared with the browser pixel), type and data;
  * a transport failure never raises into the caller (a signup must not fail
    because a marketing ping did).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services import openai_ads


class _Resp:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


def _mock_client(captured: dict, resp=None, exc=None):
    client = MagicMock()

    async def _post(url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        if exc:
            raise exc
        return resp or _Resp()

    client.post = AsyncMock(side_effect=_post)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def test_no_key_sends_nothing(monkeypatch):
    monkeypatch.delenv("OPENAI_ADS_CONVERSION_KEY", raising=False)
    with patch("httpx.AsyncClient") as ac:
        await openai_ads.send_conversion("trial_started", event_id="t1",
                                         data={"type": "plan_enrollment"})
    ac.assert_not_called()
    assert openai_ads.is_configured() is False


async def test_sends_correct_request_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_ADS_CONVERSION_KEY", "sk-conv-123")
    monkeypatch.setenv("FRONTEND_URL", "https://www.openlines.ai")
    captured: dict = {}
    with patch("httpx.AsyncClient", return_value=_mock_client(captured)):
        await openai_ads.send_conversion(
            "trial_started", event_id="tenant-abc",
            data={"type": "plan_enrollment", "plan_id": "pro"})

    assert openai_ads.DEFAULT_PIXEL_ID in captured["url"]
    assert captured["url"].endswith(f"pid={openai_ads.DEFAULT_PIXEL_ID}")
    assert captured["headers"]["Authorization"] == "Bearer sk-conv-123"
    ev = captured["json"]["events"][0]
    assert captured["json"]["validate_only"] is False
    assert ev["id"] == "tenant-abc"          # dedup key shared with the pixel
    assert ev["type"] == "trial_started"
    assert ev["data"] == {"type": "plan_enrollment", "plan_id": "pro"}
    assert ev["action_source"] == "web"
    assert isinstance(ev["timestamp_ms"], int)
    assert ev["source_url"] == "https://www.openlines.ai"


async def test_source_url_is_always_present_even_without_frontend_url(monkeypatch):
    """OpenAI rejects a web event without source_url. It must be sent even when
    FRONTEND_URL is unset — falling back to the production URL."""
    monkeypatch.setenv("OPENAI_ADS_CONVERSION_KEY", "sk-conv-123")
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    captured: dict = {}
    with patch("httpx.AsyncClient", return_value=_mock_client(captured)):
        await openai_ads.send_conversion("trial_started", event_id="t1",
                                         data={"type": "plan_enrollment"})
    ev = captured["json"]["events"][0]
    assert ev.get("source_url"), "web events must always carry source_url"
    assert ev["source_url"].startswith("http")


async def test_missing_event_id_does_not_send(monkeypatch):
    monkeypatch.setenv("OPENAI_ADS_CONVERSION_KEY", "sk-conv-123")
    with patch("httpx.AsyncClient") as ac:
        await openai_ads.send_conversion("trial_started", event_id="")
    ac.assert_not_called()


async def test_transport_failure_never_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_ADS_CONVERSION_KEY", "sk-conv-123")
    captured: dict = {}
    with patch("httpx.AsyncClient",
               return_value=_mock_client(captured, exc=httpx.ConnectError("down"))):
        # Must not raise.
        await openai_ads.send_conversion("trial_started", event_id="t1")


async def test_api_error_status_never_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_ADS_CONVERSION_KEY", "sk-conv-123")
    captured: dict = {}
    with patch("httpx.AsyncClient",
               return_value=_mock_client(captured, resp=_Resp(401, "unauthorized"))):
        await openai_ads.send_conversion("trial_started", event_id="t1")
    assert captured["json"]["events"][0]["id"] == "t1"
