"""Destination-number security helpers: masking, keyed hashing (dedup/loop),
and — when crypto is available — the encrypt/decrypt round-trip."""
import importlib
import os

import pytest

from services import routing_destinations as rd
from services.routing_destinations import DestinationSecurityError


def test_mask_never_reveals_full_number():
    m = rd.mask("+16475551234")
    assert m.endswith("1234") and "6475551234" not in m
    assert rd.mask("12") == "•••"


def test_normalize():
    assert rd.normalize("(647) 555-1234") == "+16475551234"
    assert rd.normalize("") == ""


def test_keyed_hash_requires_pepper(monkeypatch):
    monkeypatch.delenv("ROUTING_HASH_PEPPER", raising=False)
    with pytest.raises(DestinationSecurityError):
        rd.keyed_hash("+16475551234")


def test_keyed_hash_is_deterministic_and_pepper_bound(monkeypatch):
    monkeypatch.setenv("ROUTING_HASH_PEPPER", "pepper-A")
    h1 = rd.keyed_hash("+16475551234")
    h2 = rd.keyed_hash("(647) 555-1234")           # same number, different formatting
    assert h1 == h2 and len(h1) == 64
    assert "6475551234" not in h1                  # not the raw number
    monkeypatch.setenv("ROUTING_HASH_PEPPER", "pepper-B")
    assert rd.keyed_hash("+16475551234") != h1     # different pepper -> different hash


def test_is_same_number_loop_guard(monkeypatch):
    monkeypatch.setenv("ROUTING_HASH_PEPPER", "pepper")
    h = rd.keyed_hash("+16475551234")
    assert rd.is_same_number("+1 647 555 1234", h) is True
    assert rd.is_same_number("+16475559999", h) is False
    assert rd.is_same_number("+16475551234", "") is False


def _crypto_available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _crypto_available(), reason="cryptography not installed locally")
def test_secure_fields_roundtrip(monkeypatch):
    monkeypatch.setenv("ROUTING_HASH_PEPPER", "pepper")
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", os.urandom(32).hex())
    fields = rd.secure_fields("+16475551234")
    assert set(fields) == {"e164_encrypted", "e164_masked", "e164_hash", "country"}
    assert fields["e164_masked"].endswith("1234")
    assert fields["country"] == "NANP"
    assert rd.reveal(fields["e164_encrypted"]) == "+16475551234"   # recoverable


def test_validate_destination_number():
    assert rd.validate_destination_number("+16475551234")[0] is True
    assert rd.validate_destination_number("(647) 555-1234")[0] is True     # normalized
    assert rd.validate_destination_number("911") == (False, "emergency_number")
    assert rd.validate_destination_number("+19005551234") == (False, "premium_number")
    assert rd.validate_destination_number("+442071838750") == (False, "international_not_allowed")
    assert rd.validate_destination_number("12345") == (False, "short_code")


def test_secure_fields_rejects_empty(monkeypatch):
    monkeypatch.setenv("ROUTING_HASH_PEPPER", "pepper")
    with pytest.raises(DestinationSecurityError):
        rd.secure_fields("")
