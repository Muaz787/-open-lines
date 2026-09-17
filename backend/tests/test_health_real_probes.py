"""The health page may not tick a service it has not actually called.

THE DEFECT THIS CLOSES
OpenAI, Vapi and Square were checked with os.getenv alone. A revoked, expired
or rotated key showed green under a heading that read "All checks passing" —
for the three services a live call depends on most. A key that exists and a key
that works are different facts, and only one of them is worth a tick.

Parsed rather than grepped: the prose above names the old behaviour, and must
not be able to satisfy or fail an assertion about the new one.
"""
import ast
import re
from pathlib import Path

import pytest

ADMIN = (Path(__file__).resolve().parents[1] / "routers" / "admin.py").read_text()

#: Services whose credentials can be verified by a call that costs nothing.
PROBED = ("openai", "vapi", "square")


def _health_src() -> str:
    tree = ast.parse(ADMIN)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
              and n.name == "system_health")
    return ast.unparse(fn)


def _strip_docstrings(src: str) -> str:
    """Drop every docstring, so an explanation of what a probe does NOT do
    cannot be mistaken for what it does."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


@pytest.mark.parametrize("service", PROBED)
def test_the_service_has_a_probe_function(service):
    assert f"_chk_{service}" in _health_src(), f"{service} has no probe"


@pytest.mark.parametrize("service", PROBED)
def test_the_probe_is_actually_gathered(service):
    """A probe defined and never awaited is worth less than none: it looks like
    coverage and reports nothing."""
    src = _strip_docstrings(_health_src())
    gather = src[src.index("asyncio.gather("):]
    assert f"_chk_{service}()" in gather[:600], f"{service}'s probe is never run"


@pytest.mark.parametrize("service", PROBED)
def test_the_service_is_no_longer_an_env_check(service):
    """_env() reports presence. These three must not appear in that list."""
    src = _strip_docstrings(_health_src())
    for line in src.splitlines():
        if "_env(" in line:
            assert service not in line.lower(), f"{service} is still an env check"


@pytest.mark.parametrize("service", PROBED)
def test_the_probe_makes_a_real_request(service):
    """Each must reach the provider — via the shared _ping, or its own client."""
    src = _strip_docstrings(_health_src())
    i = src.index(f"_chk_{service}")
    body = src[i:i + 1400]
    assert "_ping(" in body or "httpx.AsyncClient" in body, \
        f"{service}'s probe never calls anything"


def test_a_missing_key_is_reported_before_any_request():
    """An absent key is a configuration fault, not an outage, and must not be
    reported as one — nor should we call a provider with an empty credential."""
    src = _strip_docstrings(_health_src())
    for service in PROBED:
        i = src.index(f"_chk_{service}")
        body = src[i:i + 1400]
        assert "Not configured" in body, f"{service} does not handle an absent key"


# Square's ACTUAL /oauth2/token responses to the health probe (junk code),
# captured against the live production API 2026-09-17. Both are HTTP 401.
_SQUARE_BAD_CREDS = '{"message": "Not Authorized", "type": "service.not_authorized"}'
_SQUARE_GOOD_CREDS_BAD_CODE = (
    '{"errors":[{"category":"AUTHENTICATION_ERROR","code":"UNAUTHORIZED",'
    '"detail":"Authorization code not found for app sq0idp-w5OgvTbvj_7nKw8Et3rWJw"}]}'
)


def test_square_good_credentials_pass_despite_a_401():
    """The bug this fixes: Square returns 401 for good creds + a junk code
    ('Authorization code not found'), NOT the 400 the old check assumed, so
    healthy production credentials were reported as rejected."""
    from routers.admin import _classify_square_probe
    status, msg = _classify_square_probe(401, _SQUARE_GOOD_CREDS_BAD_CODE, "production")
    assert status == "ok", f"good creds must pass, got {status}: {msg}"


def test_square_bad_credentials_are_an_error():
    """A real credential rejection (service.not_authorized) must still fail,
    at either 401 or 403."""
    from routers.admin import _classify_square_probe
    for code in (401, 403):
        status, msg = _classify_square_probe(code, _SQUARE_BAD_CREDS, "production")
        assert status == "error", f"bad creds at {code} must error, got {status}"
        assert "credentials rejected" in msg.lower()


def test_square_400_still_passes_and_unexpected_is_a_warning():
    from routers.admin import _classify_square_probe
    assert _classify_square_probe(400, '{"errors":[]}', "production")[0] == "ok"
    assert _classify_square_probe(500, "upstream boom", "production")[0] == "warning"
