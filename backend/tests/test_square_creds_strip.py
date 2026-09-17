"""
Square app credentials must be trimmed of whitespace before use.

A trailing newline/space pasted into a Railway variable is invisible in the UI
but is sent verbatim to Square's oauth2/token endpoint, which rejects it with
401 service.not_authorized — the value looks identical to the dashboard yet the
app-credential health check goes red and (worse) token refresh fails. These
tests pin that the module trims every Square secret at load.
"""
import importlib
import os


def _reload_with(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import services.square_service as sq
    return importlib.reload(sq)


def test_app_id_and_secret_are_stripped(monkeypatch):
    sq = _reload_with(
        monkeypatch,
        SQUARE_ENVIRONMENT="production\n",
        SQUARE_APP_ID="  sq0idp-realid  ",
        SQUARE_APP_SECRET="sq0csp-realsecret\n",
    )
    try:
        assert sq.SQUARE_ENVIRONMENT == "production"
        assert sq._app_id() == "sq0idp-realid"
        assert sq._app_secret() == "sq0csp-realsecret"
        # A stripped "production" must still select the production OAuth base.
        assert sq._oauth_base() == "https://connect.squareup.com"
    finally:
        importlib.reload(sq)  # restore module to the ambient env for other tests


def test_sandbox_creds_and_webhook_key_are_stripped(monkeypatch):
    sq = _reload_with(
        monkeypatch,
        SQUARE_ENVIRONMENT="sandbox",
        SQUARE_SANDBOX_APP_ID="sandbox-sq0idp-x\n",
        SQUARE_SANDBOX_APP_SECRET=" sandbox-secret ",
        SQUARE_WEBHOOK_SIGNATURE_KEY="whsig\n",
    )
    try:
        assert sq._app_id() == "sandbox-sq0idp-x"
        assert sq._app_secret() == "sandbox-secret"
        assert sq.SQUARE_WEBHOOK_SIGNATURE_KEY == "whsig"
    finally:
        importlib.reload(sq)
