"""A subscription that cannot start yet is not a subscription the customer lacks.

THE DEFECT THIS CLOSES
A regulated signup chooses Pro, gives us a card, and gets no subscription: there
is no billable line until a regulator approves their number, so
subscription_status sits at 'none' for as long as the filing takes. Every
plan gate read that status directly, so for the whole of that wait the customer
was refused Square, Stripe Connect and deposits, and quietly demoted to trial
knowledge-base caps -- charged, in effect, for someone else's queue.

Production at the time: three Irish tenants on Pro, all blocked, all with a
Stripe Customer on file.

AND THE GATES DISAGREED
Four modules each decided the plan question for themselves, with three
different status sets between them. These tests pin the single resolver and
assert no gate has grown its own copy back.
"""
import ast
import inspect
import re
from pathlib import Path

import pytest

from services import entitlements, kb_limits

BACKEND = Path(__file__).resolve().parents[1]


def _t(**over):
    """A regulated tenant that has completed payment and is awaiting a number."""
    return {
        "subscription_plan": "pro", "subscription_status": "none",
        "stripe_customer_id": "cus_1", "business_country_code": "IE",
        "twilio_phone_number": None, "stripe_subscription_id": None,
        "stripe_trial_ends_at": None, **over,
    }


# ── the new branch ──────────────────────────────────────────────────────

def test_a_regulated_tenant_awaiting_a_number_holds_the_plan_it_paid_for():
    assert entitlements.entitled_plan(_t()) == "pro"
    assert entitlements.entitled_plan(_t(subscription_plan="business")) == "business"


def test_completing_payment_is_required_evidence():
    """Without a Stripe Customer nothing was chosen — an abandoned signup in a
    regulated country must not collect a paid plan by simply existing."""
    assert entitlements.entitled_plan(_t(stripe_customer_id=None)) is None
    assert entitlements.entitled_plan(_t(stripe_customer_id="  ")) is None


def test_the_grant_ends_when_the_number_goes_live():
    """The condition is "no line yet", never "this tenant is Irish", so it stops
    holding on its own — no code change, no country list to edit."""
    assert entitlements.entitled_plan(_t(twilio_phone_number="+35316971234")) is None


def test_an_unregulated_tenant_gains_nothing_from_this():
    """A CA tenant with no subscription is simply a tenant with no subscription."""
    assert entitlements.entitled_plan(
        _t(business_country_code="CA", twilio_phone_number=None)) is None


def test_a_real_subscription_is_unchanged():
    """The control. A card trial is a real Stripe subscription and always passed;
    if this regressed, the new branch would be masking it."""
    assert entitlements.entitled_plan(
        {"subscription_plan": "pro", "subscription_status": "trialing"}) == "pro"
    assert entitlements.entitled_plan(
        {"subscription_plan": "business", "subscription_status": "active"}) == "business"


@pytest.mark.parametrize("status", ["canceled", "unpaid", "incomplete_expired", ""])
def test_a_dead_subscription_grants_nothing(status):
    assert entitlements.entitled_plan(
        {"subscription_plan": "pro", "subscription_status": status,
         "stripe_customer_id": "cus_1"}) is None


def test_a_free_plan_grants_nothing_however_it_is_waiting():
    for plan in ("starter", "trial", "", None):
        assert entitlements.entitled_plan(_t(subscription_plan=plan)) is None


# ── the gates that read it ──────────────────────────────────────────────

def test_knowledge_base_caps_follow_the_plan_through_the_wait():
    assert kb_limits.kb_limits(_t())["tier"] == "pro"
    assert kb_limits.kb_limits(_t(subscription_plan="business"))["tier"] == "business"


def test_starter_still_resolves_to_starter():
    """entitled_plan answers only the PAID-tier question. Routing Starter through
    it would drop those tenants to trial caps, which is the opposite of the point."""
    assert kb_limits.kb_limits(
        {"subscription_plan": "starter", "subscription_status": "active"}
    )["tier"] == "starter"


def test_a_tenant_with_nothing_still_gets_trial_caps():
    assert kb_limits.kb_limits({})["tier"] == "trial"


# ── no gate may decide the plan question for itself again ───────────────

GATES = ["routers/square_connect.py", "routers/stripe_connect.py", "routers/payments.py"]


@pytest.mark.parametrize("rel", GATES)
def test_no_gate_reimplements_the_status_test(rel):
    """Four modules each answering this separately is how they came to admit
    different sets of tenants. Parsed rather than grepped so the comment
    explaining why the local copy was removed cannot fail its own assertion.
    """
    src = (BACKEND / rel).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "trialing":
            raise AssertionError(
                f"{rel} tests subscription status itself; use entitlements.entitled_plan")


@pytest.mark.parametrize("rel", GATES)
def test_every_gate_reads_the_resolver(rel):
    src = (BACKEND / rel).read_text()
    assert "entitled_plan" in src, f"{rel} does not consult the resolver"


def test_the_routing_tier_is_built_on_the_same_answer():
    """tier_for used to hold its own copy of the status test."""
    src = inspect.getsource(entitlements.tier_for)
    assert "entitled_plan" in src
    assert "trialing" not in src
