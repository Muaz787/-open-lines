"""Public URLs used to build every link in every email.

A localhost value here mails dead links to real customers. It has happened twice
on two different Railway services — the web service and the scheduled cron
service have independent env vars, and they send different emails (welcome from
the web, trial reminders from the cron), so fixing one left the other broken and
nobody noticed until a customer clicked a reminder.
"""
from unittest.mock import patch

import pytest

from services import email


def _resolve(env_value, sending: bool, var="FRONTEND_URL", default="https://openlines.ai"):
    env = {} if env_value is None else {var: env_value}
    with patch.dict("os.environ", env, clear=False), \
         patch.object(email.resend, "api_key", "re_live_key" if sending else ""):
        if env_value is None:
            import os
            os.environ.pop(var, None)
        return email._resolve_public_url(var, default)


@pytest.mark.parametrize("local", [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://localhost",
    "http://0.0.0.0:3000",
    "http://mymac.local:3000",
])
def test_a_local_url_is_refused_when_we_are_actually_sending_mail(local):
    """Resend configured means real email to real people. A localhost link is a
    misconfiguration, never an intent."""
    assert _resolve(local, sending=True) == "https://openlines.ai"


@pytest.mark.parametrize("local", ["http://localhost:3000", "http://127.0.0.1:3000"])
def test_a_local_url_is_kept_in_dev_where_nothing_is_sent(local):
    """Without RESEND_API_KEY, _send() no-ops — so local links are harmless and a
    developer testing templates should still get their own dev server."""
    assert _resolve(local, sending=False) == local


def test_a_real_url_is_left_alone():
    assert _resolve("https://openlines.ai", sending=True) == "https://openlines.ai"
    assert _resolve("https://staging.openlines.ai", sending=True) == "https://staging.openlines.ai"


def test_a_bare_domain_gets_https():
    assert _resolve("openlines.ai", sending=True) == "https://openlines.ai"


def test_an_unset_var_uses_the_production_default():
    assert _resolve(None, sending=True) == "https://openlines.ai"


def test_an_empty_var_uses_the_production_default():
    assert _resolve("   ", sending=True) == "https://openlines.ai"


def test_the_backend_url_is_guarded_too():
    """It builds the one-click unsubscribe link, which CASL requires to work."""
    backend = "https://backend-production-71174.up.railway.app"
    assert _resolve("http://localhost:8000", sending=True,
                    var="APP_BACKEND_URL", default=backend) == backend


def test_the_live_constants_are_not_local():
    """Guards the module as actually imported, not just the helper."""
    for url in (email.FRONTEND_URL, email.BACKEND_URL):
        assert "localhost" not in url or not email.resend.api_key
