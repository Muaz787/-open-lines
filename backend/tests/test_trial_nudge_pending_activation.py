"""The legacy trial nudge must not count down a trial that never started.

THE DEFECT THIS CLOSES
trial_status()'s derived branch computes a 7-day window from created_at for any
tenant without a Stripe subscription. A tenant in a regulated country waiting on
a regulator has no subscription, no charge and no working line -- so that window
is arithmetic about a trial that does not exist. Found in production on a real
Irish signup: the tenant was three days from being emailed "your free trial
ends in 2 days" while its filing had not even been submitted.

The dashboard banner already refuses to say this (it reads
trial_pending_activation). These tests hold the outbound mail to the same truth.

AND THE COLUMN LIST, WHICH IS THE PART THAT ACTUALLY BITES
Twice now a guard in this sweep has been written against a column the select
never fetched. Nothing raises: the key is absent, .get() returns None, and the
guard is silently false forever. So one test asserts the skip and another
asserts the SELECT -- deriving the required columns from the source of
_trial_pending_activation rather than restating them, because a hardcoded list
would drift in exactly the same way.
"""
import ast
import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import trial
import db.supabase as _supabase_mod  # noqa: F401  (registers the path for patch())


def _row(**over):
    """A legacy card-free tenant, old enough for the day-3 nudge to be due."""
    return {
        "id": "t1", "business_name": "Acme", "email": "a@b.com",
        "created_at": (datetime.now(timezone.utc) - timedelta(days=4)).isoformat(),
        "subscription_status": "none",
        "minutes_used_this_period": 0,
        "billing_exempt": False, "marketing_unsubscribed_at": None, "is_active": True,
        "trial_email_day3_sent": False, "trial_email_day6_sent": False,
        "trial_email_ended_sent": False,
        "business_country_code": "CA", "twilio_phone_number": "+14165550123",
        "stripe_trial_ends_at": None, "stripe_subscription_id": None,
        **over,
    }


def _db_returning(rows):
    q = MagicMock()
    for m in ("select", "eq", "is_", "gte", "limit"):
        getattr(q, m).return_value = q
    q.execute.return_value = MagicMock(data=rows)
    client = MagicMock()
    client.table.return_value = q
    return client


async def _run(rows):
    sends: list[dict] = []

    async def _send(**kw):
        sends.append(kw)
        return True

    with patch("db.supabase.get_client", return_value=_db_returning(rows)), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.email.send_trial_reminder_email", new=_send):
        result = await trial.process_trial_reminders()
    return result, sends


@pytest.mark.asyncio
async def test_an_ordinary_legacy_trial_is_still_nudged():
    """The control. Without this, a guard that skips EVERYONE also passes."""
    result, sends = await _run([_row()])
    assert result["active"] == 1
    assert [s["kind"] for s in sends] == ["active"]


@pytest.mark.asyncio
async def test_a_tenant_awaiting_regulatory_clearance_is_not_nudged():
    """No permanent number in a regulated country: no trial has begun."""
    result, sends = await _run([_row(business_country_code="IE",
                                     twilio_phone_number=None)])
    assert sends == []
    assert result == {"active": 0, "ending": 0, "ended": 0}


@pytest.mark.asyncio
async def test_the_same_tenant_is_nudged_once_its_number_is_live():
    """The condition is "no line yet", never "this tenant is Irish". An Irish
    tenant whose number went live is an ordinary tenant again, with no code
    change and no country list to edit."""
    result, sends = await _run([_row(business_country_code="IE",
                                     twilio_phone_number="+35316971234")])
    assert result["active"] == 1


@pytest.mark.asyncio
async def test_a_real_stripe_trial_in_a_regulated_country_is_untouched():
    """trial_pending_activation is about an absent trial, not a regulated one."""
    ends = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    _, sends = await _run([_row(business_country_code="IE",
                                twilio_phone_number=None,
                                stripe_subscription_id="sub_1",
                                stripe_trial_ends_at=ends)])
    assert [s["kind"] for s in sends] == ["active"]


def _columns_read_by(func) -> set[str]:
    """Every literal key the function passes to tenant.get(...).

    Parsed, not grepped, so prose in the docstring naming a column cannot
    satisfy this and a real read cannot hide from it.
    """
    tree = ast.parse(inspect.getsource(func).lstrip())
    found: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    return found


def _selected_columns(func) -> set[str]:
    """The column names actually requested by the .select(...) in a function.

    Read from the parsed call argument, not by searching the source text:
    matching substrings would be satisfied by a column named in a comment, and
    would miss one whose name happens to straddle the pieces of the implicitly
    concatenated literal — which is precisely how the first draft of this test
    reported a false failure.
    """
    tree = ast.parse(inspect.getsource(func).lstrip())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "select"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            return {c.strip() for c in node.args[0].value.split(",") if c.strip()}
    return set()


def test_trial_reminder_select_columns():
    """THE ONE THAT WOULD HAVE CAUGHT ALL THREE OCCURRENCES.

    A guard reading a column the query never fetched is not a failure — it is a
    guard that is permanently false. So assert the select actually asks for
    every column the pending-activation check consults.
    """
    required = (_columns_read_by(trial._trial_pending_activation)
                | _columns_read_by(trial.has_active_subscription)
                | _columns_read_by(trial.is_billing_exempt))
    assert required, "parsed no columns — the AST walk is broken, not the code"

    selected = _selected_columns(trial.process_trial_reminders)
    assert selected, "found no .select() — the AST walk is broken, not the code"

    missing = sorted(required - selected)
    assert not missing, (
        f"process_trial_reminders guards read {missing} but the select never "
        f"fetches them, so those guards can never fire")
