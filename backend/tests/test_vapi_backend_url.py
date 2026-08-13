"""APP_BACKEND_URL must never reach Vapi as a local address.

Vapi is a cloud service — it cannot call localhost, not even in dev (main.py
substitutes an ngrok tunnel for exactly that reason). A local value baked into an
assistant's tool definitions silently breaks caller lookup and appointment
booking on live calls.

This happened: the scheduled cron service had APP_BACKEND_URL=http://localhost:8000
(a dev-shaped value, harmless in the web service because main.py rewrites it, but
the cron never runs main.py). Its daily re-crawl pushes `tools`, so every
re-crawled tenant got localhost tool URLs written into their live assistant.
"""
from unittest.mock import patch

import pytest

from services import vapi


PROD = "https://backend-production-71174.up.railway.app"


@pytest.mark.parametrize("bad", [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://localhost",
    "http://0.0.0.0:8000",
    "http://mymac.local:8000",
    "",
])
def test_a_local_backend_url_is_refused(bad):
    with patch.object(vapi, "APP_BACKEND_URL", bad):
        with pytest.raises(RuntimeError):
            vapi.build_caller_lookup_tool("t1")
        with pytest.raises(RuntimeError):
            vapi.build_calendar_tools("t1")


def test_refusing_beats_writing_a_broken_tool_url():
    """The re-crawl reprompt treats a raised error as non-fatal and leaves the
    assistant's existing, working tools in place. Skipping an update is strictly
    better than pushing one Vapi can never call."""
    with patch.object(vapi, "APP_BACKEND_URL", "http://localhost:8000"):
        with pytest.raises(RuntimeError, match="Vapi cannot reach it"):
            vapi.build_calendar_tools("t1")


def test_a_public_url_builds_real_tool_endpoints():
    with patch.object(vapi, "APP_BACKEND_URL", PROD):
        tools = vapi.build_calendar_tools("t1")
    urls = [t["server"]["url"] for t in tools if "server" in t]
    assert urls, "expected tool server URLs"
    for u in urls:
        assert u.startswith(f"{PROD}/tools/t1")


def test_an_ngrok_tunnel_is_accepted():
    """Local dev goes through ngrok, which is a real public host."""
    tunnel = "https://abc123.ngrok-free.app"
    with patch.object(vapi, "APP_BACKEND_URL", tunnel):
        tool = vapi.build_caller_lookup_tool("t1")
    assert tool["server"]["url"].startswith(tunnel)
