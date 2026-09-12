"""W9F.1 — /health must be able to say which commit it is running.

Three gates in a row could not answer "which commit is Railway serving?", so every
release had to be verified by inference. This adds one field.

The property that matters most is the negative one: /health is public and
unauthenticated, so a value is published ONLY if it is a well-formed git SHA. A
mis-set environment variable must not become an information leak, and a missing one
must not make the service look unhealthy.
"""
import pytest

from services import deployment


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in deployment.COMMIT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


FULL = "89c1e404fc11a01f9c587174e50942bafc79f80a"
SHORT = "89c1e40"


# ── the variable Railway actually injects ──────────────────────────────────

def test_railway_git_commit_sha_is_the_first_source(monkeypatch):
    """RAILWAY_GIT_COMMIT_SHA is Railway's own auto-injected variable, provided
    without opt-in when the deploy came from a GitHub trigger."""
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", FULL)
    assert deployment.deployment_commit() == FULL


def test_railway_wins_over_the_generic_alias(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", FULL)
    monkeypatch.setenv("GIT_COMMIT_SHA", "0" * 40)
    assert deployment.deployment_commit() == FULL


def test_the_generic_alias_works_off_railway(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT_SHA", FULL)
    assert deployment.deployment_commit() == FULL


def test_only_two_variable_names_are_consulted():
    """A long list of guesses would widen the surface for a mis-set variable."""
    assert deployment.COMMIT_ENV_VARS == ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA")


# ── absent ─────────────────────────────────────────────────────────────────

def test_absent_env_yields_None():
    assert deployment.deployment_commit() is None


def test_health_is_still_200_shaped_when_the_commit_is_unknown():
    """An unknown commit is a gap in observability, not an unhealthy service."""
    body = deployment.health_payload(environment="production")
    assert body["status"] == "ok"
    assert body["environment"] == "production"
    assert body["version"] == "0.1.0"
    assert "commit" not in body


def test_health_carries_the_commit_when_it_is_known(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", FULL)
    body = deployment.health_payload(environment="production")
    assert body["commit"] == FULL
    assert body["status"] == "ok"


def test_the_existing_health_keys_are_unchanged(monkeypatch):
    """Anything already parsing /health must keep working."""
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", FULL)
    body = deployment.health_payload(environment="development")
    assert set(body) == {"status", "version", "environment", "commit"}


# ── malformed / unexpected values are NEVER echoed ─────────────────────────

@pytest.mark.parametrize("value", [
    "",                       # set but empty
    "   ",                    # whitespace
    "unknown",                # a placeholder someone wired in
    "HEAD",
    "main",                   # a branch name in the wrong variable
    "not-a-sha",
    "89c1e4",                 # 6 chars: too short to be an abbreviated SHA
    "8" * 41,                 # too long
    "89c1e404g011a01f9c587174e50942bafc79f80a",   # 'g' is not hex
    "acdeadbeefdeadbeefdeadbeefdeadbeef",         # 34 all-hex: Twilio-SID shaped
    "d41d8cd98f00b204e9800998ecf8427e",           # 32 all-hex: an MD5 digest
    "89c1e404fc11a01f9c58",                       # 20 hex: in the excluded band
    "89c1e404 fc11a01",       # embedded space
    "postgres://user:pw@host/db",                 # a connection string
    "sk-live-0123456789abcdef",                   # a credential-shaped value
    "89c1e404fc11a01f9c587174e50942bafc79f80a extra",
])
def test_a_value_that_is_not_a_sha_is_treated_as_absent(monkeypatch, value):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", value)
    assert deployment.deployment_commit() is None
    assert "commit" not in deployment.health_payload(environment="production")


def test_a_secret_shaped_value_is_never_published(monkeypatch):
    """The whole reason for validating the shape rather than passing it through."""
    # Shaped exactly like a Twilio Account SID ("AC" + 32 hex) but synthetic. Never
    # put a real one in a test file: GitHub push protection rejected the first draft
    # of this test for exactly that, and it was right to.
    secret = "ACdeadbeefdeadbeefdeadbeefdeadbeef"
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", secret)
    body = deployment.health_payload(environment="production")
    assert secret not in str(body)
    assert "commit" not in body


def test_an_uppercase_sha_is_normalised_not_rejected(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", FULL.upper())
    assert deployment.deployment_commit() == FULL


def test_surrounding_whitespace_is_tolerated(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", f"  {FULL}\n")
    assert deployment.deployment_commit() == FULL


def test_an_abbreviated_sha_is_accepted(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", SHORT)
    assert deployment.deployment_commit() == SHORT


# A null byte is not in this list because os.environ itself refuses to store one --
# the OS makes that case unreachable, so a test for it would be testing CPython.
@pytest.mark.parametrize("weird", ["89c1e40\u200b", "89c1e40\n\n89c1e40",
                                   "ＳＨＡ", "89c1e40;rm -rf /", "0x89c1e40"])
def test_odd_input_is_rejected_without_raising(monkeypatch, weird):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", weird)
    assert deployment.deployment_commit() is None


def test_the_excluded_hex_band_is_explicit():
    """13-39 all-hex characters are refused on purpose: that is where all-hex secrets
    such as a Twilio Account SID (34) or an MD5 digest (32) fall."""
    for n in (13, 20, 32, 34, 39):
        assert deployment._SHA.match("a" * n) is None, f"length {n} must be refused"
    for n in (7, 8, 12, 40):
        assert deployment._SHA.match("a" * n), f"length {n} must be accepted"


def test_no_other_environment_variable_can_leak_through(monkeypatch):
    """Only the two named variables are read -- nothing else in the environment
    reaches the payload."""
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "super-secret")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "also-secret")
    body = deployment.health_payload(environment="production")
    assert "super-secret" not in str(body)
    assert "also-secret" not in str(body)
    assert set(body) == {"status", "version", "environment"}
