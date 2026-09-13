"""Two production defects found on a real Irish signup (CarsIreland).

DEFECT 1 — THE REGULATED EXIT DROPPED THE BILLING HAND-OFF
The customer completed the payment step: a Stripe Customer was created and
positively adopted into the payment session. But tenants.stripe_customer_id is
written only by create_trial_subscription, which the regulated exit skips, and
`plan` is excluded from provision_data. Weeks later permanent_activation reads
both off the tenant, finds neither, and returns BILLING_SETUP_REQUIRED --
leaving a customer who paid with a live number, no trial and no email.

DEFECT 2 — THE WRONG CLOCK GATED THE CALL
Every inbound call was gated on trial_status(), whose derived branch is 7 days
from created_at with a 30-minute cap. That would switch off a temporary TEST
line a week after signup, while the approved policy grants 60 minutes over 30
days -- and the tenant has no permanent number to fall back to.

Neither fix starts a trial, creates a Stripe object, or charges anything.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routers import onboarding, webhooks
from services import ireland_lifecycle as il
from services import phone_lifecycle as pl
from services import subscriptions, trial

TENANT = "a748f40d-7071-49b0-a221-a8d36ca136e9"
KEY = "087bb92e-11cb-4457-a689-1c19101e883b"
CUS = "cus_VFl3kiNV2bRTiV"


# ═══ DEFECT 1: the billing hand-off ═════════════════════════════════════

def _regulated_result():
    return {"tenant_id": TENANT, "onboarding_state": "regulatory_required",
            "next_step": "regulatory_information_required", "phone_number": ""}


async def _provision(plan="pro", *, token=True, customer=CUS):
    """Run the real /provision for a regulated tenant and capture tenant writes."""
    import os
    os.environ["ENCRYPTION_KEY_HEX"] = os.urandom(32).hex()
    writes, billing = [], []

    async def update_tenant(tid, patch):
        writes.append((tid, patch))
        if "stripe_customer_id" in patch or "subscription_plan" in patch:
            billing.append(patch)
        return {"id": tid}

    async def sub(**kw):
        raise AssertionError("CREATED A SUBSCRIPTION AT THE REGULATED EXIT")

    body = onboarding.ProvisionRequest(
        business_name="CarsIreland", industry="automotive", country="IE",
        email="t@x.ie", password="12345678", onboarding_key=KEY, plan=plan,
        payment_method_id="pm_x",
        card_setup_token=subscriptions.issue_card_setup_token(customer) if token else "")
    with patch.object(onboarding.country_access, "decide", new=AsyncMock(
             return_value={"access": onboarding.country_access.ALLOWED,
                           "reason": "publicly_open", "pilot_grant": False})), \
         patch.object(onboarding.payment_customer, "resolve_for_tenant",
                      new=AsyncMock(return_value=customer)), \
         patch("services.provisioning.provision_tenant",
               new=AsyncMock(return_value=_regulated_result())), \
         patch("db.supabase.create_auth_user", new=AsyncMock(return_value="u1")), \
         patch("db.supabase.update_tenant", new=update_tenant), \
         patch("services.subscriptions.create_trial_subscription", new=sub):
        out = await onboarding.provision(None, body)
    return out, writes, billing


@pytest.mark.asyncio
async def test_the_resolved_customer_is_persisted_before_the_regulated_exit():
    out, _, billing = await _provision()
    assert out["onboarding_state"] == "regulatory_required"
    assert any(p.get("stripe_customer_id") == CUS for p in billing), billing


@pytest.mark.asyncio
async def test_the_selected_plan_is_persisted_before_the_regulated_exit():
    _, _, billing = await _provision(plan="pro")
    assert any(p.get("subscription_plan") == "pro" for p in billing), billing


@pytest.mark.asyncio
async def test_the_regulated_exit_creates_no_subscription_and_no_trial():
    """The patched create_trial_subscription raises if reached."""
    out, writes, _ = await _provision()
    assert out["onboarding_state"] == "regulatory_required"
    for _tid, patch_ in writes:
        assert "stripe_subscription_id" not in patch_
        assert "stripe_trial_ends_at" not in patch_
        assert patch_.get("subscription_status") in (None, "none")


@pytest.mark.asyncio
async def test_it_creates_no_stripe_object_of_its_own():
    import sys
    stripe = MagicMock()
    with patch.dict(sys.modules, {"stripe": stripe}):
        await _provision()
    stripe.Customer.create.assert_not_called()
    stripe.Subscription.create.assert_not_called()
    stripe.PaymentIntent.create.assert_not_called()


@pytest.mark.asyncio
async def test_the_persisted_plan_is_the_server_validated_one():
    """Not a price, and not a client string: ProvisionRequest already validates
    plan, so an invalid one never reaches persistence."""
    with pytest.raises(Exception):
        onboarding.ProvisionRequest(business_name="X", industry="automotive",
                                    country="IE", email="t@x.ie",
                                    password="12345678", plan="enterprise")


@pytest.mark.asyncio
async def test_no_price_is_hardcoded_into_the_regulated_exit():
    import inspect
    src = inspect.getsource(onboarding.provision)
    for price in ("199", "99", "379", "CAD"):
        assert price not in src, price


@pytest.mark.asyncio
async def test_a_retry_reuses_the_same_customer_and_never_makes_another():
    """resolve_for_tenant reads the payment session, which holds exactly one
    Customer per onboarding key."""
    seen = []
    for _ in range(3):
        _, _, billing = await _provision()
        seen += [p.get("stripe_customer_id") for p in billing if p.get("stripe_customer_id")]
    assert set(seen) == {CUS}, seen


@pytest.mark.asyncio
async def test_a_signup_without_a_card_persists_no_billing_identity():
    _, _, billing = await _provision(token=False, customer="")
    assert not any(p.get("stripe_customer_id") for p in billing)


@pytest.mark.asyncio
async def test_a_failed_billing_write_does_not_fail_the_signup():
    """The tenant and the payment session both exist and the Customer is
    recoverable from the session, so this is reported, not fatal."""
    async def boom(tid, patch_):
        if "stripe_customer_id" in patch_:
            raise RuntimeError("db down")
        return {"id": tid}

    import os
    os.environ["ENCRYPTION_KEY_HEX"] = os.urandom(32).hex()
    body = onboarding.ProvisionRequest(
        business_name="CarsIreland", industry="automotive", country="IE",
        email="t@x.ie", password="12345678", onboarding_key=KEY, plan="pro",
        payment_method_id="pm_x",
        card_setup_token=subscriptions.issue_card_setup_token(CUS))
    with patch.object(onboarding.country_access, "decide", new=AsyncMock(
             return_value={"access": onboarding.country_access.ALLOWED,
                           "reason": "publicly_open", "pilot_grant": False})), \
         patch.object(onboarding.payment_customer, "resolve_for_tenant",
                      new=AsyncMock(return_value=CUS)), \
         patch("services.provisioning.provision_tenant",
               new=AsyncMock(return_value=_regulated_result())), \
         patch("db.supabase.create_auth_user", new=AsyncMock(return_value="u1")), \
         patch("db.supabase.update_tenant", new=boom):
        out = await onboarding.provision(None, body)
    assert out["onboarding_state"] == "regulatory_required"


def test_permanent_activation_reads_exactly_what_the_exit_now_writes():
    """The two ends of the hand-off, pinned to each other."""
    import inspect
    from services import permanent_activation as act
    src = inspect.getsource(act._ensure_trial)
    assert 'tenant.get("stripe_customer_id")' in src
    assert 'tenant.get("subscription_plan")' in src
    exit_src = inspect.getsource(onboarding.provision)
    assert '"stripe_customer_id"' in exit_src and '"subscription_plan"' in exit_src


# ═══ DEFECT 2: the call gate ════════════════════════════════════════════

def _tenant(**o):
    return {"id": TENANT, "business_name": "CarsIreland",
            "business_country_code": "IE", "subscription_status": "none",
            "created_at": "2020-01-01T00:00:00+00:00",   # derived trial LONG expired
            "minutes_used_this_period": 0, **o}


def _row(purpose, tenant_id=TENANT, e164="+14165550100"):
    return {"id": "r1", "tenant_id": tenant_id, "e164": e164,
            "purpose": purpose, "status": pl.STATUS_ACTIVE}


@pytest.mark.asyncio
async def test_a_temporary_line_ignores_the_expired_derived_trial():
    """THE defect. The derived 7-day clock expired years ago in this fixture;
    the temporary line must still answer."""
    assert trial.trial_status(_tenant())["line_active"] is False, "fixture is wrong"
    with patch.object(il.db_phones, "find_routable_by_e164",
                      new=AsyncMock(return_value=_row(pl.PURPOSE_TEMPORARY))), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=None)):
        assert await il.inbound_call_allowed(_tenant(), "+14165550100") is True


@pytest.mark.asyncio
async def test_a_suspended_temporary_line_is_blocked():
    with patch.object(il.db_phones, "find_routable_by_e164",
                      new=AsyncMock(return_value=_row(pl.PURPOSE_TEMPORARY))), \
         patch.object(il.ita, "get", new=AsyncMock(return_value={
             "suspended_at": "2026-09-20T00:00:00+00:00",
             "suspend_reason": il.SUSPEND_ALLOWANCE})):
        assert await il.inbound_call_allowed(_tenant(), "+14165550100") is False


@pytest.mark.parametrize("reason", [
    "test_allowance_exhausted", "pending_review_period_expired",
    "correction_window_expired", "registration_rejected",
])
@pytest.mark.asyncio
async def test_every_approved_limit_blocks_through_the_same_suspension(reason):
    """60 minutes, 30 days, the 14-day window and the 7-day grace all land as a
    suspension, so the call path reads one durable fact rather than recomputing
    four clocks."""
    with patch.object(il.db_phones, "find_routable_by_e164",
                      new=AsyncMock(return_value=_row(pl.PURPOSE_TEMPORARY))), \
         patch.object(il.ita, "get", new=AsyncMock(return_value={
             "suspended_at": "2026-09-20T00:00:00+00:00", "suspend_reason": reason})):
        assert await il.inbound_call_allowed(_tenant(), "+14165550100") is False


@pytest.mark.asyncio
async def test_a_permanent_line_still_uses_the_ordinary_trial_gate():
    """THE regression boundary. CA/US must not get a free bypass."""
    with patch.object(il.db_phones, "find_routable_by_e164",
                      new=AsyncMock(return_value=_row(pl.PURPOSE_PERMANENT))), \
         patch.object(il.ita, "get",
                      new=AsyncMock(side_effect=AssertionError("USED TEMP POLICY"))):
        assert await il.inbound_call_allowed(_tenant(), "+14165550100") is False


@pytest.mark.asyncio
async def test_a_permanent_line_with_an_active_subscription_answers():
    t = _tenant(subscription_status="active")
    with patch.object(il.db_phones, "find_routable_by_e164",
                      new=AsyncMock(return_value=_row(pl.PURPOSE_PERMANENT))):
        assert await il.inbound_call_allowed(t, "+14165550100") is True


@pytest.mark.asyncio
async def test_a_temporary_row_belonging_to_another_tenant_is_ignored():
    """Never take another tenant's row as authority for this call."""
    with patch.object(il.db_phones, "find_routable_by_e164", new=AsyncMock(
            return_value=_row(pl.PURPOSE_TEMPORARY, tenant_id="someone-else"))), \
         patch.object(il.ita, "get",
                      new=AsyncMock(side_effect=AssertionError("USED TEMP POLICY"))):
        assert await il.inbound_call_allowed(_tenant(), "+14165550100") is False


@pytest.mark.asyncio
async def test_an_unreadable_canonical_row_falls_back_to_existing_behaviour():
    """Fails to what happened before this function existed."""
    with patch.object(il.db_phones, "find_routable_by_e164",
                      new=AsyncMock(side_effect=RuntimeError("db down"))):
        assert await il.inbound_call_allowed(_tenant(), "+14165550100") is False
        assert await il.inbound_call_allowed(
            _tenant(subscription_status="active"), "+14165550100") is True


@pytest.mark.asyncio
async def test_no_country_or_prefix_decides_anything():
    import ast, inspect, textwrap
    fn = ast.parse(textwrap.dedent(inspect.getsource(il.inbound_call_allowed))).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    code = ast.unparse(fn)
    for smell in ('"IE"', "'IE'", "+353", "+1", "business_country_code",
                  "iso_country", "twilio_phone_number", "startswith"):
        assert smell not in code, smell


@pytest.mark.asyncio
async def test_the_policy_is_not_duplicated_in_the_webhook():
    import ast, inspect, textwrap
    fn = ast.parse(textwrap.dedent(
        inspect.getsource(webhooks._calls_allowed))).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]      # the docstring may NAME what the code calls
    code = ast.unparse(fn)
    for calc in ("60", "3600", "timedelta", "FREE_SECONDS", "PENDING_DAYS",
                 "suspended_at"):
        assert calc not in code, calc
    assert "inbound_call_allowed" in code
    assert "trial_status" not in code


@pytest.mark.asyncio
async def test_the_gate_passes_the_called_number_through():
    import inspect
    src = inspect.getsource(webhooks)
    assert "_calls_allowed(tenant, called_number)" in src


def test_a_temporary_line_cannot_start_or_extend_a_paid_trial():
    from tests.module_identifiers import identifiers
    refs = identifiers(il)
    for forbidden in ("create_trial_subscription", "stripe_trial_ends_at",
                      "Subscription", "_ensure_trial"):
        assert forbidden not in refs, forbidden


@pytest.mark.asyncio
async def test_the_webhook_helper_itself_honours_phone_purpose():
    """Behavioural, not structural: the helper the call path actually invokes
    must let a temporary line through despite a long-expired derived trial."""
    with patch.object(il.db_phones, "find_routable_by_e164",
                      new=AsyncMock(return_value=_row(pl.PURPOSE_TEMPORARY))), \
         patch.object(il.ita, "get", new=AsyncMock(return_value=None)):
        assert await webhooks._calls_allowed(_tenant(), "+14165550100") is True


@pytest.mark.asyncio
async def test_the_webhook_helper_still_gates_a_permanent_line():
    with patch.object(il.db_phones, "find_routable_by_e164",
                      new=AsyncMock(return_value=_row(pl.PURPOSE_PERMANENT))):
        assert await webhooks._calls_allowed(_tenant(), "+14165550100") is False
        assert await webhooks._calls_allowed(
            _tenant(subscription_status="active"), "+14165550100") is True
