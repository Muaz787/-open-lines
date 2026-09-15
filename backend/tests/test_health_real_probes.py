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


def test_square_treats_rejected_credentials_as_an_error():
    """Verified against the live API: junk credentials return 401, so Square
    checks them before the code. Confusing that with the deliberate bad-code
    400 would turn a dead integration green."""
    src = _strip_docstrings(_health_src())
    i = src.index("_chk_square")
    body = src[i:i + 1800]
    assert "401" in body and "403" in body
    err = body[body.index("401"):body.index("401") + 400]
    assert "'error'" in err or '"error"' in err, "a 401 from Square must be an error"


def test_square_only_passes_on_the_anticipated_status():
    """Anything unanticipated degrades to a warning rather than a tick — the
    pass branch is the narrow one, which is the safe direction for a status
    this code did not foresee."""
    src = _strip_docstrings(_health_src())
    i = src.index("_chk_square")
    body = src[i:i + 1800]
    assert "'warning'" in body, "Square has no fallback branch"
    ok_at = body.index("'ok'")
    assert "400" in body[max(0, ok_at - 200):ok_at], \
        "the Square pass must be tied to the 400 that means 'credentials accepted'"
