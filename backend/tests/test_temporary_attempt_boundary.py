"""A failure that reaches no provider must not consume the purchase attempt.

THE DEFECT THIS CLOSES
_ensure_temporary recorded the provider attempt and THEN called
ensure_temporary_number, on the principle that everything after that write is
recoverable because the write committed first. That is exactly right for a
provider failure: Twilio may hold a number we never saw, and only a positive
reconciliation may attach it.

But it also consumed the attempt for failures that reached no provider at all.
An unset TEMP_NUMBER_SOURCE_COUNTRY returns UNAVAILABLE from inside that call
having contacted nobody -- and ireland_temp_access offers no route back from
"attempted" to "may buy", because retake_unattempted is gated on
provider_attempt_at being null, deliberately, since elapsed time is not
evidence of anything.

So a configuration gap on ONE of the two services would permanently cost a
customer their temporary test line, on BOTH services, with no error raised
anywhere. The web service could mark the attempt and refuse, and the correctly
configured cron could then never buy.

A configuration gap is not a provider failure. These tests hold that line.
"""
import ast
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from services import ireland_lifecycle as il
from services import temporary_numbers as temp


def _tenant():
    return {"id": "t-1", "business_country_code": "IE",
            "twilio_subaccount_sid": "AC1", "twilio_auth_token": "tok"}


async def _run(*, preflight_ok: bool, refusal=None):
    """Drive _ensure_temporary with everything below it stubbed."""
    marked, bought = [], []

    async def _mark(tid):
        marked.append(tid)
        return True

    async def _buy(*a, **k):
        bought.append(k)
        return {"status": temp.OK, "e164": "+14165550100", "row": {"provider_sid": "PN1"}}

    verdict = ({"ok": True, "tenant": _tenant(), "policy": None} if preflight_ok
               else {"ok": False, "refusal": refusal})

    with patch.object(il.ita, "claim", new=AsyncMock(return_value=True)), \
         patch.object(il.ita, "get", new=AsyncMock(return_value={})), \
         patch.object(il.ita, "mark_attempt", new=_mark), \
         patch.object(il.ita, "attach_number", new=AsyncMock(return_value=True)), \
         patch.object(il.ita, "start_access", new=AsyncMock(return_value=True)), \
         patch.object(il.temporary_numbers, "preflight",
                      new=AsyncMock(return_value=verdict)), \
         patch.object(il.temporary_numbers, "ensure_temporary_number", new=_buy):
        out = await il._ensure_temporary(_tenant(), verified_status="pending-review")
    return out, marked, bought


# ── the defect ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [
    "temporary_numbers_disabled",
    "no_source_country_configured",
    "source_country_not_supported:ZZ",
    "source_country_is_regulated:IE",
])
async def test_a_configuration_gap_leaves_the_attempt_unspent(reason):
    """Every source_problem() value. None of them reaches a provider, so none
    of them may cost the customer their one chance to buy."""
    out, marked, bought = await _run(
        preflight_ok=False, refusal={"status": temp.UNAVAILABLE, "reason": reason})
    assert marked == [], f"{reason} consumed the purchase attempt"
    assert bought == []
    assert out["outcome"] == il.TEMP_BLOCKED
    assert out["reason"] == reason


@pytest.mark.asyncio
async def test_an_ineligible_tenant_leaves_the_attempt_unspent():
    """Eligibility is read-only and spends nothing, so it cannot justify
    burning the attempt either."""
    out, marked, _ = await _run(
        preflight_ok=False,
        refusal={"status": temp.NOT_ELIGIBLE, "reason": "no_regulatory_filing"})
    assert marked == []
    assert out["outcome"] == il.TEMP_BLOCKED


@pytest.mark.asyncio
async def test_a_refusal_says_the_attempt_survived():
    """An operator reading this outcome needs to know a retry is still possible.
    Silence would read identically to the unrecoverable case."""
    out, _, _ = await _run(
        preflight_ok=False,
        refusal={"status": temp.UNAVAILABLE, "reason": "no_source_country_configured"})
    assert out.get("attempt_preserved") is True


# ── the control: the boundary must still exist ──────────────────────────

@pytest.mark.asyncio
async def test_a_clean_preflight_still_records_the_attempt_before_buying():
    """The provider-attempt boundary is the whole safety property. Moving the
    configuration checks in front of it must not remove it."""
    out, marked, bought = await _run(preflight_ok=True)
    assert marked == ["t-1"], "the attempt must be recorded before any purchase"
    assert len(bought) == 1
    assert out["outcome"] == il.TEMP_PROVISIONED


def test_the_attempt_is_marked_after_the_preflight_not_before():
    """An ORDER, and the defect was that this order was reversed. Parsed from
    the source, because the two calls are three lines apart and a future edit
    that swaps them would pass every behavioural test above."""
    src = inspect.getsource(il._ensure_temporary)
    tree = ast.parse(src.lstrip())
    order = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name.endswith("preflight"):
                order.append(("preflight", node.lineno))
            elif name.endswith("mark_attempt"):
                order.append(("mark_attempt", node.lineno))
    assert [n for n, _ in order][:2] == ["preflight", "mark_attempt"], \
        f"the attempt is recorded before the provider-free checks: {order}"


# ── one implementation, two callers ─────────────────────────────────────

def test_the_acquisition_uses_the_same_preflight():
    """Two copies of "what is refusable without spending" would drift, and the
    drift would only show as a customer losing a line."""
    src = inspect.getsource(temp.ensure_temporary_number)
    assert "preflight(" in src, "the acquisition re-implements its own preflight"


def test_the_preflight_contacts_no_provider():
    """The property that makes it safe to run before the attempt is recorded."""
    src = inspect.getsource(temp.preflight)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            for banned in ("tenant_subaccount.ensure", "purchase_number",
                           "held_numbers", "regulatory_client", "httpx"):
                assert banned not in name, f"preflight reaches a provider via {name}"


# ── the real preflight, against the real configuration reader ───────────

@pytest.mark.asyncio
async def test_the_real_preflight_refuses_an_unset_source_country(monkeypatch):
    """Not a stub. This is the exact production condition that cost the line:
    TEMP_NUMBER_ENABLED on, no source country, nothing to contact."""
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", "true")
    monkeypatch.delenv("TEMP_NUMBER_SOURCE_COUNTRY", raising=False)

    client = type("C", (), {})()
    client.table = lambda *_a, **_k: client
    for m in ("select", "eq", "limit"):
        setattr(client, m, lambda *_a, **_k: client)
    client.execute = lambda: type("R", (), {"data": [_tenant()]})()

    with patch.object(temp, "get_client", return_value=client), \
         patch.object(temp, "eligibility",
                      new=AsyncMock(return_value={"eligible": True, "reason": "",
                                                  "detail": "", "profile": None})):
        out = await temp.preflight("t-1", verified_provider_status="pending-review")

    assert out["ok"] is False
    assert out["refusal"]["reason"] == "no_source_country_configured"
    assert out["refusal"]["status"] == temp.UNAVAILABLE


@pytest.mark.asyncio
async def test_the_real_preflight_passes_a_usable_source(monkeypatch):
    """The control. Without it, a preflight that refused everything would also
    satisfy the test above."""
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_SOURCE_COUNTRY", "CA")

    client = type("C", (), {})()
    client.table = lambda *_a, **_k: client
    for m in ("select", "eq", "limit"):
        setattr(client, m, lambda *_a, **_k: client)
    client.execute = lambda: type("R", (), {"data": [_tenant()]})()

    with patch.object(temp, "get_client", return_value=client), \
         patch.object(temp, "eligibility",
                      new=AsyncMock(return_value={"eligible": True, "reason": "",
                                                  "detail": "", "profile": None})):
        out = await temp.preflight("t-1", verified_provider_status="pending-review")

    assert out["ok"] is True
    assert out["policy"].iso_country == "CA"
