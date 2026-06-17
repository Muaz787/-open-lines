"""
Tests for branded short payment link service and redirect route.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# services/short_links
# ---------------------------------------------------------------------------

from services.short_links import (
    generate_short_code,
    is_valid_short_code,
    is_safe_stripe_url,
    build_branded_url,
    format_currency,
    _ALPHABET,
    _CODE_LEN,
)


class TestGenerateShortCode:
    def test_length(self):
        assert len(generate_short_code()) == _CODE_LEN

    def test_alphabet_only(self):
        for _ in range(100):
            code = generate_short_code()
            assert all(c in _ALPHABET for c in code), f"unexpected char in {code!r}"

    def test_unique_most_of_the_time(self):
        codes = {generate_short_code() for _ in range(200)}
        assert len(codes) > 195, "too many collisions in 200 codes"

    def test_no_ambiguous_chars(self):
        # Alphabet excludes 0/O (zero/oh) and 1/I (one/eye) — L is kept
        for _ in range(500):
            code = generate_short_code()
            assert "0" not in code
            assert "O" not in code
            assert "1" not in code
            assert "I" not in code


class TestIsValidShortCode:
    def test_valid_8_chars(self):
        assert is_valid_short_code("ABCD2345")

    def test_valid_10_chars(self):
        assert is_valid_short_code("ABCDE23456")

    def test_too_short(self):
        assert not is_valid_short_code("ABC123")

    def test_too_long(self):
        assert not is_valid_short_code("ABCDE234567")

    def test_lowercase_rejected(self):
        assert not is_valid_short_code("abcd2345")

    def test_special_chars_rejected(self):
        assert not is_valid_short_code("ABCD-234")

    def test_path_traversal_rejected(self):
        assert not is_valid_short_code("../etc/p")

    def test_zero_rejected(self):
        assert not is_valid_short_code("ABCD0345")  # 0 not in alphabet


class TestIsSafeStripeUrl:
    def test_checkout_stripe_allowed(self):
        assert is_safe_stripe_url("https://checkout.stripe.com/c/pay/cs_test_abc123")

    def test_buy_stripe_allowed(self):
        assert is_safe_stripe_url("https://buy.stripe.com/test_abc123")

    def test_tinyurl_blocked(self):
        assert not is_safe_stripe_url("https://tinyurl.com/abc123")

    def test_open_redirect_blocked(self):
        assert not is_safe_stripe_url("https://evil.com/checkout.stripe.com/pay")

    def test_http_stripe_blocked(self):
        assert not is_safe_stripe_url("http://checkout.stripe.com/pay/abc")

    def test_empty_blocked(self):
        assert not is_safe_stripe_url("")


class TestBuildBrandedUrl:
    def test_format(self):
        url = build_branded_url("ABCD2345")
        assert "/d/ABCD2345" in url
        assert url.startswith("http")

    def test_no_double_slash(self):
        url = build_branded_url("ABCD2345")
        assert "//d/" not in url


class TestFormatCurrency:
    def test_cad(self):
        assert format_currency("cad") == "CAD"

    def test_usd(self):
        assert format_currency("usd") == "USD"

    def test_eur(self):
        assert format_currency("eur") == "EUR"

    def test_gbp(self):
        assert format_currency("gbp") == "GBP"

    def test_aud(self):
        assert format_currency("aud") == "AUD"

    def test_nzd(self):
        assert format_currency("nzd") == "NZD"

    def test_already_uppercase(self):
        assert format_currency("CAD") == "CAD"

    def test_unknown_uppercased(self):
        assert format_currency("xxy") == "XXY"

    def test_empty_string(self):
        assert format_currency("") == ""


# ---------------------------------------------------------------------------
# routers/pay  (redirect route)
# ---------------------------------------------------------------------------

@pytest.fixture
def future_expires():
    return (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()


@pytest.fixture
def past_expires():
    return (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()


VALID_STRIPE_URL = "https://checkout.stripe.com/c/pay/cs_test_abc123"


@pytest.mark.asyncio
async def test_redirect_valid_link(future_expires):
    from routers.pay import redirect_payment_link
    from fastapi.responses import RedirectResponse

    mock_link = {
        "id": "link-id-1",
        "short_code": "ABCD2345",
        "stripe_checkout_url": VALID_STRIPE_URL,
        "expires_at": future_expires,
        "tenant_id": "tenant-1",
        "click_count": 0,
        "clicked_at": None,
    }

    with patch("routers.pay.db.get_payment_short_link_by_code", AsyncMock(return_value=mock_link)), \
         patch("routers.pay.db.increment_short_link_click", AsyncMock()):
        response = await redirect_payment_link("ABCD2345")

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 302
    assert response.headers["location"] == VALID_STRIPE_URL


@pytest.mark.asyncio
async def test_redirect_expired_link(past_expires):
    from routers.pay import redirect_payment_link
    from fastapi.responses import HTMLResponse

    mock_link = {
        "id": "link-id-2",
        "short_code": "ABCD2346",
        "stripe_checkout_url": VALID_STRIPE_URL,
        "expires_at": past_expires,
        "tenant_id": "tenant-1",
        "click_count": 0,
    }

    with patch("routers.pay.db.get_payment_short_link_by_code", AsyncMock(return_value=mock_link)):
        response = await redirect_payment_link("ABCD2346")

    assert isinstance(response, HTMLResponse)
    assert response.status_code == 410
    assert "expired" in response.body.decode().lower()


@pytest.mark.asyncio
async def test_redirect_not_found():
    from routers.pay import redirect_payment_link
    from fastapi.responses import HTMLResponse

    with patch("routers.pay.db.get_payment_short_link_by_code", AsyncMock(return_value=None)):
        response = await redirect_payment_link("XXXXXXXX")

    assert isinstance(response, HTMLResponse)
    assert response.status_code == 404
    assert "not found" in response.body.decode().lower()


@pytest.mark.asyncio
async def test_redirect_invalid_code_format():
    from routers.pay import redirect_payment_link
    from fastapi.responses import HTMLResponse

    response = await redirect_payment_link("../etc/passwd")
    assert isinstance(response, HTMLResponse)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_redirect_unsafe_url(future_expires):
    from routers.pay import redirect_payment_link
    from fastapi.responses import HTMLResponse

    mock_link = {
        "id": "link-id-3",
        "short_code": "ABCD2347",
        "stripe_checkout_url": "https://evil.com/steal-money",
        "expires_at": future_expires,
        "tenant_id": "tenant-1",
        "click_count": 0,
    }

    with patch("routers.pay.db.get_payment_short_link_by_code", AsyncMock(return_value=mock_link)):
        response = await redirect_payment_link("ABCD2347")

    assert isinstance(response, HTMLResponse)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# SMS content checks
# ---------------------------------------------------------------------------

def test_sms_contains_branded_domain():
    url = build_branded_url("ABCD2345")
    assert "checkout.stripe.com" not in url
    assert "tinyurl.com" not in url
    assert "/d/ABCD2345" in url


def test_sms_does_not_contain_stripe_directly():
    url = build_branded_url("XY3K9P2Q")
    assert "checkout.stripe.com" not in url


# ---------------------------------------------------------------------------
# Multi-currency
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    ("cad", "CAD"),
    ("usd", "USD"),
    ("eur", "EUR"),
    ("gbp", "GBP"),
    ("aud", "AUD"),
    ("nzd", "NZD"),
    ("aed", "AED"),
    ("sgd", "SGD"),
])
def test_multi_currency_formatting(code, expected):
    assert format_currency(code) == expected
