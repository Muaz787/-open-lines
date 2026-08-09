"""Base-URL normalization for Stripe onboarding/checkout links. Guards against the
Railway footgun where a pasted multi-line value (two env lines mashed together)
made FRONTEND_URL invalid -> Stripe 'Not a valid URL'."""
from services.stripe_service import _clean_base_url

DEF = "https://openlines.ai"


def test_normal_url_unchanged():
    assert _clean_base_url("https://openlines.ai", DEF) == "https://openlines.ai"


def test_none_and_empty_fall_back_to_default():
    assert _clean_base_url(None, DEF) == DEF
    assert _clean_base_url("", DEF) == DEF
    assert _clean_base_url("   ", DEF) == DEF


def test_strips_surrounding_whitespace_and_newlines():
    assert _clean_base_url("  https://openlines.ai  ", DEF) == "https://openlines.ai"
    assert _clean_base_url("https://openlines.ai\n", DEF) == "https://openlines.ai"


def test_the_actual_bug_two_env_lines_mashed_into_one_value():
    # exactly what was in Railway: FRONTEND_URL value spanned two lines
    raw = "https://openlines.ai\nAPP_BACKEND_URL=https://backend-production-71174.up.railway.app"
    assert _clean_base_url(raw, DEF) == "https://openlines.ai"


def test_drops_trailing_slash():
    assert _clean_base_url("https://openlines.ai/", DEF) == "https://openlines.ai"


def test_adds_scheme_when_missing():
    assert _clean_base_url("openlines.ai", DEF) == "https://openlines.ai"


def test_upgrades_http_to_https_for_real_hosts():
    # Stripe LIVE rejects http:// — upgrade real hosts
    assert _clean_base_url("http://openlines.ai", DEF) == "https://openlines.ai"


def test_preserves_http_localhost_for_test_mode():
    # local dev + Stripe TEST mode allows http://localhost
    assert _clean_base_url("http://localhost:3000", DEF) == "http://localhost:3000"
    assert _clean_base_url("http://127.0.0.1:3000", DEF) == "http://127.0.0.1:3000"


def test_resulting_url_has_no_whitespace():
    raw = "https://openlines.ai APP_BACKEND_URL=https://x"
    out = _clean_base_url(raw, DEF)
    assert " " not in out and "\n" not in out and out == "https://openlines.ai"
