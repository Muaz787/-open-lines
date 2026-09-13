"""W9I-G — taking a purchased +353 live, and everything that follows.

THE ORDER IS THE DESIGN, and this suite is arranged around it:

    health PASS          nothing is live yet; failing costs nothing
    canonical ACTIVE     calls now route; the customer has a working line
    scalar + onboarding  the rest of the product agrees the line is theirs
    Stripe trial         billing starts, and only now is that honest
    activation email     the customer is told, and only now is that true

Read backwards: never tell a customer something, or charge them for it, before
it is true. Read forwards: once the phone works, NOTHING later may undo it.
A Stripe outage does not roll back a working line, and an email failure does not
deactivate a number.
"""
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import activation_notification as notify
from services import permanent_activation as act
from services import phone_lifecycle as lifecycle
from tests.module_identifiers import identifiers

TENANT = "11111111-1111-1111-1111-111111111111"
ROW = "33333333-3333-3333-3333-333333333333"
REPLACEMENT = "44444444-4444-4444-4444-444444444444"
SUB = "AC" + "1" * 32
OTHER_SUB = "AC" + "2" * 32
PN = "PN" + "c" * 32
E164 = "+35315550123"
TEMP_E164 = "+442071234567"
TO = "owner@example.ie"


def _tenant(**over):
    return {"id": TENANT, "business_name": "Acme", "business_country_code": "IE",
            "onboarding_state": "regulatory_required", "email": TO,
            "notification_email": TO, "twilio_phone_number": None,
            "twilio_subaccount_sid": SUB, "twilio_auth_token": "tok",
            "vapi_assistant_id": "asst_1", "stripe_customer_id": "cus_123",
            "stripe_subscription_id": None, "subscription_plan": "starter", **over}


def _row(status=lifecycle.STATUS_PROVISIONING, purpose=lifecycle.PURPOSE_PERMANENT,
         e164=E164, rid=ROW, **over):
    return {"id": rid, "tenant_id": TENANT, "e164": e164, "purpose": purpose,
            "status": status, "provider": "twilio", "provider_account_sid": SUB,
            "provider_sid": PN, "iso_country": "IE", "vapi_phone_number_id": "vp_1",
            "activation_email_claimed_at": None, "activation_email_sent_at": None,
            "activation_email_provider_id": None, **over}


def _twilio_number(voice=True, e164=E164, sid=PN, url="https://api.vapi.ai/twilio/inbound_call"):
    return MagicMock(sid=sid, phone_number=e164, voice_url=url,
                     voice_application_sid="", capabilities={"voice": voice})


def _healthy_world(*, numbers=None, vapi_records=None):
    listing = MagicMock(ok=True, numbers=numbers if numbers is not None
                        else [_twilio_number()])
    records = vapi_records if vapi_records is not None else [
        {"id": "vp_1", "number": E164, "assistantId": "asst_1"}]
    return [
        patch.object(act.telephony, "fetch_subaccount_numbers",
                     new=AsyncMock(return_value=listing)),
        patch("services.vapi.list_phone_numbers", new=AsyncMock(return_value=records)),
        patch("services.vapi.get_tenant_vapi_key", return_value=None),
    ]


def _with(patches):
    import contextlib
    stack = contextlib.ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


# ═══ 1. health, before anything is live ════════════════════════════════════

@pytest.mark.asyncio
async def test_a_healthy_number_passes():
    with _with(_healthy_world()):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.HEALTHY


@pytest.mark.asyncio
async def test_a_provider_sid_no_longer_on_the_subaccount_is_broken():
    """An ownership question, not a routing one."""
    with _with(_healthy_world(numbers=[_twilio_number(sid="PNsomethingelse")])):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.BROKEN and out["reason"] == "provider_sid_not_on_subaccount"


@pytest.mark.asyncio
async def test_a_provider_e164_mismatch_is_broken():
    with _with(_healthy_world(numbers=[_twilio_number(e164="+35399999999")])):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.BROKEN and out["reason"] == "provider_e164_mismatch"


@pytest.mark.asyncio
async def test_a_number_without_voice_is_broken():
    with _with(_healthy_world(numbers=[_twilio_number(voice=False)])):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.BROKEN and out["reason"] == "no_voice_capability"


@pytest.mark.asyncio
async def test_a_missing_voice_route_is_repairable_not_broken():
    with _with(_healthy_world(numbers=[_twilio_number(url="")])):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.REPAIRABLE


@pytest.mark.asyncio
async def test_a_missing_vapi_record_is_repairable():
    with _with(_healthy_world(vapi_records=[])):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.REPAIRABLE and out["reason"] == "no_vapi_record_for_number"


@pytest.mark.asyncio
async def test_a_vapi_record_on_another_assistant_is_broken_not_repaired():
    """Repairing blindly could steal a number another tenant is routing."""
    with _with(_healthy_world(vapi_records=[
            {"id": "vp_x", "number": E164, "assistantId": "someone_elses"}])):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.BROKEN
    assert out["reason"] == "vapi_record_maps_to_another_assistant"


@pytest.mark.asyncio
async def test_two_vapi_records_for_one_number_is_broken():
    """Calls could land on either. Not something to resolve by picking."""
    with _with(_healthy_world(vapi_records=[
            {"id": "vp_1", "number": E164, "assistantId": "asst_1"},
            {"id": "vp_2", "number": E164, "assistantId": "asst_1"}])):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.BROKEN


@pytest.mark.asyncio
async def test_a_canonical_vapi_id_mismatch_is_broken():
    with _with(_healthy_world(vapi_records=[
            {"id": "vp_different", "number": E164, "assistantId": "asst_1"}])):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.BROKEN and out["reason"] == "canonical_vapi_id_mismatch"


@pytest.mark.parametrize("failure", [
    TimeoutError("read timed out"), RuntimeError("HTTP 500"),
    ConnectionResetError("reset"),
])
@pytest.mark.asyncio
async def test_an_unreadable_provider_is_unknown_not_healthy(failure):
    with patch.object(act.telephony, "fetch_subaccount_numbers",
                      new=AsyncMock(side_effect=failure)):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.UNKNOWN


@pytest.mark.asyncio
async def test_an_unreadable_vapi_is_unknown_not_healthy():
    with _with(_healthy_world()[:1]), \
         patch("services.vapi.list_phone_numbers",
               new=AsyncMock(side_effect=TimeoutError("timeout"))), \
         patch("services.vapi.get_tenant_vapi_key", return_value=None):
        out = await act.health_check(tenant=_tenant(), row=_row(), sub_sid=SUB,
                                     sub_tok="tok")
    assert out["state"] == act.UNKNOWN


def test_health_never_releases_the_number():
    """A +353 took a regulator's approval to obtain. It is not thrown away
    because a webhook points at the wrong place."""
    referenced = identifiers(act)
    assert "release_number" not in referenced
    assert "mark_released" not in referenced


# ═══ 2. nothing is live before health passes ══════════════════════════════

def _activation_world(*, rows, tenant=None, health=None, promoted=None):
    t = tenant or _tenant()
    return [
        patch.object(act, "_tenant", new=AsyncMock(return_value=t)),
        patch.object(act.db_phones, "list_for_tenant", new=AsyncMock(return_value=rows)),
        patch.object(act, "health_check",
                     new=AsyncMock(return_value=health or {"state": act.HEALTHY,
                                                           "reason": ""})),
        patch.object(act.db_phones, "promote_permanent_cas",
                     new=AsyncMock(return_value=promoted if promoted is not None
                                   else [_row(status=lifecycle.STATUS_ACTIVE)])),
        patch.object(act, "_finish",
                     new=AsyncMock(return_value={"status": act.OK, "activated": True})),
    ]


@pytest.mark.parametrize("state,expected", [
    (act.BROKEN, act.HEALTH_FAILED),
    (act.UNKNOWN, act.HEALTH_UNKNOWN),
])
@pytest.mark.asyncio
async def test_an_unhealthy_number_is_never_promoted(state, expected):
    with _with(_activation_world(rows=[_row()],
                                 health={"state": state, "reason": "x"})), \
         patch.object(act.db_phones, "promote_permanent_cas", new=AsyncMock()) as cas, \
         patch.object(act, "_finish", new=AsyncMock()) as fin:
        out = await act.activate_permanent_irish_number(TENANT)
    assert out["status"] == expected
    cas.assert_not_called(); fin.assert_not_called()


@pytest.mark.asyncio
async def test_a_repairable_number_is_repaired_then_rechecked():
    calls = []

    async def health(**kw):
        calls.append("health")
        return ({"state": act.REPAIRABLE, "reason": "no_vapi_record_for_number"}
                if len(calls) == 1 else {"state": act.HEALTHY, "reason": ""})

    async def repair(**kw):
        calls.append("repair")
        return True

    with patch.object(act, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(act.db_phones, "list_for_tenant", new=AsyncMock(return_value=[_row()])), \
         patch.object(act, "health_check", new=health), \
         patch.object(act, "_repair", new=repair), \
         patch.object(act.db_phones, "promote_permanent_cas",
                      new=AsyncMock(return_value=[_row(status="active")])), \
         patch.object(act, "_finish", new=AsyncMock(return_value={"status": act.OK})):
        out = await act.activate_permanent_irish_number(TENANT)
    assert calls == ["health", "repair", "health"]
    assert out["status"] == act.OK


def test_repair_only_ever_restores_the_intended_state():
    """A repair that can do more than restore is a second way to reach the
    wrong state."""
    import inspect
    src = inspect.getsource(act._repair)
    assert "create_assistant" not in src and "create_suborg" not in src
    assert "release" not in src
    assert 'assistant_id=str(tenant.get("vapi_assistant_id")' in src


# ═══ 3. eligibility ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_ca_row_is_never_promoted_through_the_ireland_path():
    """Its billing and messaging are different."""
    with patch.object(act, "_tenant",
                      new=AsyncMock(return_value=_tenant(business_country_code="CA"))), \
         patch.object(act.db_phones, "promote_permanent_cas", new=AsyncMock()) as cas:
        out = await act.activate_permanent_irish_number(TENANT)
    assert out["status"] == act.NOT_ELIGIBLE
    assert out["reason"] == "country_is_not_regulated"
    cas.assert_not_called()


@pytest.mark.asyncio
async def test_a_non_irish_number_is_refused():
    with _with(_activation_world(rows=[_row(e164="+14165550100")])), \
         patch.object(act.db_phones, "promote_permanent_cas", new=AsyncMock()) as cas:
        out = await act.activate_permanent_irish_number(TENANT)
    assert out["reason"] == "not_an_irish_number"
    cas.assert_not_called()


@pytest.mark.asyncio
async def test_a_number_on_another_account_is_refused():
    with _with(_activation_world(rows=[_row(provider_account_sid=OTHER_SUB)])), \
         patch.object(act.db_phones, "promote_permanent_cas", new=AsyncMock()) as cas:
        out = await act.activate_permanent_irish_number(TENANT)
    assert out["reason"] == "number_is_on_another_account"
    cas.assert_not_called()


@pytest.mark.asyncio
async def test_nothing_to_activate_is_not_an_error():
    with patch.object(act, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(act.db_phones, "list_for_tenant", new=AsyncMock(return_value=[])):
        out = await act.activate_permanent_irish_number(TENANT)
    assert out["status"] == act.NOTHING_TO_ACTIVATE


# ═══ 4. the promotion fence ═══════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_promotion_is_fenced_on_the_full_identity():
    """A stalled worker waking after the row was replaced must not promote the
    replacement on a decision made about a different number."""
    from db import phone_numbers as dbp

    class Rec:
        # `filters` rather than `eq`: naming the dict `eq` shadows the method
        # PostgREST calls, and the recorder silently records nothing.
        def __init__(self): self.filters = {}; self.patch = None
        def table(self, n): self.t = n; return self
        def update(self, p): self.patch = p; return self
        def eq(self, c, v): self.filters[c] = v; return self
        def execute(self): return type("R", (), {"data": [_row(status="active")]})()

    rec = Rec()
    with patch.object(dbp, "get_client", return_value=rec):
        await dbp.promote_permanent_cas(number_id=ROW, tenant_id=TENANT, e164=E164,
                                        provider_sid=PN, provider_account_sid=SUB)
    assert rec.filters == {"id": ROW, "tenant_id": TENANT, "e164": E164,
                           "provider_sid": PN, "provider_account_sid": SUB,
                           "status": lifecycle.STATUS_PROVISIONING}
    assert rec.patch["status"] == lifecycle.STATUS_ACTIVE
    assert rec.patch["activated_at_source"] == "promotion"


@pytest.mark.asyncio
async def test_a_lost_promotion_race_finishes_the_winners_work():
    """Both workers must end up describing the same activation."""
    with patch.object(act, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(act.db_phones, "list_for_tenant", new=AsyncMock(return_value=[_row()])), \
         patch.object(act, "health_check",
                      new=AsyncMock(return_value={"state": act.HEALTHY, "reason": ""})), \
         patch.object(act.db_phones, "promote_permanent_cas", new=AsyncMock(return_value=[])), \
         patch.object(act.db_phones, "get_by_id",
                      new=AsyncMock(return_value=_row(status=lifecycle.STATUS_ACTIVE))), \
         patch.object(act, "_finish",
                      new=AsyncMock(return_value={"status": act.OK})) as fin:
        out = await act.activate_permanent_irish_number(TENANT)
    assert out["status"] == act.OK
    fin.assert_called_once()


@pytest.mark.asyncio
async def test_a_stale_worker_whose_row_moved_stops():
    with patch.object(act, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(act.db_phones, "list_for_tenant", new=AsyncMock(return_value=[_row()])), \
         patch.object(act, "health_check",
                      new=AsyncMock(return_value={"state": act.HEALTHY, "reason": ""})), \
         patch.object(act.db_phones, "promote_permanent_cas", new=AsyncMock(return_value=[])), \
         patch.object(act.db_phones, "get_by_id",
                      new=AsyncMock(return_value=_row(status="released"))), \
         patch.object(act, "_finish", new=AsyncMock()) as fin:
        out = await act.activate_permanent_irish_number(TENANT)
    assert out["status"] == act.PROMOTION_LOST
    fin.assert_not_called()


# ═══ 5. the scalar, written with onboarding in one row ═══════════════════

@pytest.mark.asyncio
async def test_the_scalar_mirror_is_fenced_and_carries_onboarding():
    from db import supabase as dbs

    calls = []

    class Rec:
        def table(self, n): self.cur = {"eq": {}, "is": {}}; calls.append(self.cur); return self
        def update(self, p): self.cur["patch"] = p; return self
        def eq(self, c, v): self.cur["eq"][c] = v; return self
        def is_(self, c, v): self.cur["is"][c] = v; return self
        def execute(self): return type("R", (), {"data": [{"id": TENANT}]})()

    with patch.object(dbs, "get_client", return_value=Rec()):
        out = await dbs.mirror_permanent_number_fenced(TENANT, E164)
    assert out
    first = calls[0]
    assert first["patch"]["twilio_phone_number"] == E164
    assert first["patch"]["onboarding_state"] == "active"
    assert first["eq"] == {"id": TENANT}
    assert first["is"] == {"twilio_phone_number": "null"}


@pytest.mark.asyncio
async def test_a_tenant_pointing_at_another_number_is_not_clobbered():
    """That line may be ringing."""
    with patch.object(act.db, "mirror_permanent_number_fenced",
                      new=AsyncMock(return_value=[])), \
         patch.object(act, "_tenant",
                      new=AsyncMock(return_value=_tenant(twilio_phone_number="+353OTHER"))), \
         patch.object(act, "_ensure_trial", new=AsyncMock()) as trial:
        out = await act._finish(tenant=_tenant(), row=_row(status="active"))
    assert out["status"] == act.SCALAR_CONFLICT
    trial.assert_not_called()


# ═══ 6. billing — after activation, exactly once, never rolling back ═════

@pytest.mark.asyncio
async def test_no_trial_is_started_before_promotion():
    """Pinned structurally AND by order: _ensure_trial is reachable only from
    _finish, which only runs after a promotion committed."""
    import inspect
    src = inspect.getsource(act.activate_permanent_irish_number)
    assert "_ensure_trial" not in src
    finish = inspect.getsource(act._finish)
    assert finish.index("mirror_permanent_number_fenced") < finish.index("_ensure_trial")
    assert finish.index("_ensure_trial") < finish.index("ensure_activation_email")


@pytest.mark.asyncio
async def test_an_existing_subscription_is_never_recreated():
    with patch.object(act, "_existing_subscription", new=AsyncMock()) as look:
        out = await act._ensure_trial(_tenant(stripe_subscription_id="sub_1"))
    assert out["status"] == act.OK and out["reason"] == "already_subscribed"
    look.assert_not_called()


@pytest.mark.asyncio
async def test_stripe_is_reconciled_before_a_subscription_is_created():
    """Stripe's idempotency key is remembered for 24 hours, so it cannot be the
    only durable proof: an activation retried a day later would create a second
    trial."""
    from services import subscriptions
    with patch.object(act, "_default_payment_method", new=AsyncMock(return_value="pm_1")), \
         patch.object(act, "_existing_subscription",
                      new=AsyncMock(return_value={"id": "sub_found", "status": "trialing"})), \
         patch.object(act.db, "update_tenant", new=AsyncMock()) as upd, \
         patch.object(subscriptions, "create_trial_subscription", new=AsyncMock()) as create:
        out = await act._ensure_trial(_tenant())
    assert out["reason"] == "adopted_existing_subscription"
    create.assert_not_called()
    assert upd.call_args.args[1]["stripe_subscription_id"] == "sub_found"


@pytest.mark.asyncio
async def test_an_unreadable_stripe_does_not_create_a_second_trial():
    """THE bug this suite caught during development: returning None on a failed
    lookup would have let a create proceed on 'we could not check'."""
    from services import subscriptions
    with patch.object(act, "_default_payment_method", new=AsyncMock(return_value="pm_1")), \
         patch.object(act, "_existing_subscription",
                      new=AsyncMock(return_value={"id": "", "status": act.RECONCILE_UNKNOWN})), \
         patch.object(subscriptions, "create_trial_subscription", new=AsyncMock()) as create:
        out = await act._ensure_trial(_tenant())
    assert out["status"] == act.BILLING_PENDING
    create.assert_not_called()


@pytest.mark.asyncio
async def test_the_ireland_path_never_creates_a_stripe_customer():
    """The /setup-card duplicate-Customer defect is carried debt; a second
    creation site would make it worse and harder to find."""
    referenced = identifiers(act)
    assert "Customer" not in referenced or "create" not in referenced
    import inspect
    src = inspect.getsource(act)
    assert "Customer.create" not in src
    assert "stripe.Customer.create" not in src


@pytest.mark.asyncio
async def test_no_stripe_customer_is_a_controlled_state_not_an_invented_one():
    with patch.object(act, "_default_payment_method", new=AsyncMock(return_value="pm")):
        out = await act._ensure_trial(_tenant(stripe_customer_id=None))
    assert out["status"] == act.BILLING_SETUP_REQUIRED
    assert out["reason"] == "no_stripe_customer"


@pytest.mark.asyncio
async def test_a_billing_failure_never_deactivates_the_phone():
    with patch.object(act.db, "mirror_permanent_number_fenced",
                      new=AsyncMock(return_value=[{"id": TENANT}])), \
         patch.object(act, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(act, "_ensure_trial",
                      new=AsyncMock(return_value={"status": act.BILLING_PENDING,
                                                  "reason": "stripe_error"})), \
         patch.object(act.db_phones, "promote_permanent_cas", new=AsyncMock()) as cas, \
         patch.object(act, "ensure_activation_email", new=AsyncMock()) as mail:
        out = await act._finish(tenant=_tenant(), row=_row(status="active"))
    assert out["status"] == act.BILLING_PENDING
    assert out["row"]["status"] == lifecycle.STATUS_ACTIVE
    cas.assert_not_called()          # nothing rolled back
    mail.assert_not_called()         # and the customer is not told yet


# ═══ 7. the activation email ═════════════════════════════════════════════

def _mail_world(outcome):
    return patch("services.email.send_with_outcome", return_value=outcome)


@pytest.mark.asyncio
async def test_a_successful_send_is_confirmed_with_its_provider_id():
    with patch.object(act.db_phones, "claim_activation_email",
                      new=AsyncMock(return_value=[_row()])), \
         patch.object(act.db_phones, "confirm_activation_email",
                      new=AsyncMock(return_value=[_row()])) as confirm, \
         _mail_world({"ok": True, "provider_id": "resend_123", "error": None}):
        out = await act.ensure_activation_email(tenant=_tenant(), row=_row(status="active"))
    assert out["status"] == act.OK and out["sent"] is True
    assert confirm.call_args.args[1] == "resend_123"


@pytest.mark.asyncio
async def test_an_already_sent_notification_is_never_sent_again():
    with _mail_world({"ok": True, "provider_id": "x", "error": None}) as send:
        out = await act.ensure_activation_email(
            tenant=_tenant(),
            row=_row(status="active", activation_email_sent_at="2026-09-12T00:00:00+00:00"))
    assert out["status"] == act.OK and out["sent"] is False
    send.assert_not_called()


@pytest.mark.asyncio
async def test_losing_the_claim_means_not_sending():
    """One logical event, one sender."""
    with patch.object(act.db_phones, "claim_activation_email",
                      new=AsyncMock(return_value=[])), \
         _mail_world({"ok": True, "provider_id": "x", "error": None}) as send:
        out = await act.ensure_activation_email(tenant=_tenant(), row=_row(status="active"))
    assert out["sent"] is False
    send.assert_not_called()


@pytest.mark.asyncio
async def test_the_send_carries_the_deterministic_key():
    seen = {}

    def send(**kw):
        seen.update(kw)
        return {"ok": True, "provider_id": "r1", "error": None}

    with patch.object(act.db_phones, "claim_activation_email",
                      new=AsyncMock(return_value=[_row()])), \
         patch.object(act.db_phones, "confirm_activation_email",
                      new=AsyncMock(return_value=[])), \
         patch("services.email.send_with_outcome", new=send):
        await act.ensure_activation_email(tenant=_tenant(), row=_row(status="active"))
    assert seen["idempotency_key"] == f"openlines-ie-activation/{TENANT}/{ROW}"
    assert E164 in seen["html_body"]
    assert seen["to"] == TO


@pytest.mark.asyncio
async def test_a_replacement_number_gets_its_own_notification():
    """The reason 032 is scoped to the phone row. A tenant-global flag would
    have suppressed this entirely."""
    seen = []

    def send(**kw):
        seen.append(kw["idempotency_key"])
        return {"ok": True, "provider_id": "r", "error": None}

    with patch.object(act.db_phones, "claim_activation_email",
                      new=AsyncMock(return_value=[_row()])), \
         patch.object(act.db_phones, "confirm_activation_email",
                      new=AsyncMock(return_value=[])), \
         patch("services.email.send_with_outcome", new=send):
        await act.ensure_activation_email(tenant=_tenant(), row=_row(status="active"))
        await act.ensure_activation_email(
            tenant=_tenant(),
            row=_row(status="active", rid=REPLACEMENT, e164="+35315559999"))
    assert len(seen) == 2 and seen[0] != seen[1]


@pytest.mark.asyncio
async def test_a_timeout_keeps_the_claim_so_nobody_sends_outside_the_window():
    """The send may have landed. Releasing the claim would let another worker
    send outside the provider's deduplication."""
    with patch.object(act.db_phones, "claim_activation_email",
                      new=AsyncMock(return_value=[_row()])), \
         patch.object(act.db_phones, "release_activation_email_claim",
                      new=AsyncMock()) as release, \
         _mail_world({"ok": False, "provider_id": "", "error": TimeoutError("t")}):
        out = await act.ensure_activation_email(tenant=_tenant(), row=_row(status="active"))
    assert out["status"] == act.EMAIL_PENDING
    release.assert_not_called()


@pytest.mark.asyncio
async def test_an_unconfirmed_claim_inside_the_window_retries_with_the_same_key(monkeypatch):
    monkeypatch.delenv(notify.SAFE_RETRY_WINDOW_ENV, raising=False)
    from datetime import datetime, timedelta, timezone
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    seen = {}

    def send(**kw):
        seen.update(kw)
        return {"ok": True, "provider_id": "r2", "error": None}

    with patch.object(act.db_phones, "claim_activation_email",
                      new=AsyncMock()) as claim, \
         patch.object(act.db_phones, "confirm_activation_email",
                      new=AsyncMock(return_value=[])), \
         patch("services.email.send_with_outcome", new=send):
        out = await act.ensure_activation_email(
            tenant=_tenant(),
            row=_row(status="active", activation_email_claimed_at=recent))
    assert out["sent"] is True
    claim.assert_not_called()         # taken over, not re-claimed
    assert seen["idempotency_key"] == f"openlines-ie-activation/{TENANT}/{ROW}"


@pytest.mark.asyncio
async def test_an_unconfirmed_claim_beyond_the_window_never_resends(monkeypatch):
    monkeypatch.delenv(notify.SAFE_RETRY_WINDOW_ENV, raising=False)
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(hours=22)).isoformat()
    with _mail_world({"ok": True, "provider_id": "x", "error": None}) as send:
        out = await act.ensure_activation_email(
            tenant=_tenant(),
            row=_row(status="active", activation_email_claimed_at=old))
    assert out["status"] == notify.NEEDS_REVIEW
    send.assert_not_called()


@pytest.mark.asyncio
async def test_an_unparseable_claim_timestamp_is_not_treated_as_fresh():
    with _mail_world({"ok": True, "provider_id": "x", "error": None}) as send:
        out = await act.ensure_activation_email(
            tenant=_tenant(),
            row=_row(status="active", activation_email_claimed_at="not-a-date"))
    assert out["status"] == notify.NEEDS_REVIEW
    send.assert_not_called()


@pytest.mark.asyncio
async def test_a_changed_payload_under_a_used_key_goes_to_review():
    class Err(Exception):
        error_type = "invalid_idempotent_request"
    with patch.object(act.db_phones, "claim_activation_email",
                      new=AsyncMock(return_value=[_row()])), \
         patch.object(act.db_phones, "release_activation_email_claim",
                      new=AsyncMock()) as release, \
         _mail_world({"ok": False, "provider_id": "", "error": Err()}):
        out = await act.ensure_activation_email(tenant=_tenant(), row=_row(status="active"))
    assert out["status"] == notify.NEEDS_REVIEW and out["reason"] == "payload_changed"
    release.assert_not_called()


@pytest.mark.asyncio
async def test_a_fatal_refusal_releases_the_claim_for_a_clean_retry():
    class Err(Exception):
        error_type = "invalid_api_key"
    with patch.object(act.db_phones, "claim_activation_email",
                      new=AsyncMock(return_value=[_row()])), \
         patch.object(act.db_phones, "release_activation_email_claim",
                      new=AsyncMock()) as release, \
         _mail_world({"ok": False, "provider_id": "", "error": Err()}):
        out = await act.ensure_activation_email(tenant=_tenant(), row=_row(status="active"))
    assert out["status"] == notify.NEEDS_REVIEW
    release.assert_called_once()


@pytest.mark.asyncio
async def test_no_recipient_goes_to_review_rather_than_sending_nowhere():
    with _mail_world({"ok": True, "provider_id": "x", "error": None}) as send:
        out = await act.ensure_activation_email(
            tenant=_tenant(email="", notification_email=""),
            row=_row(status="active"))
    assert out["status"] == notify.NEEDS_REVIEW
    send.assert_not_called()


@pytest.mark.asyncio
async def test_an_empty_number_can_never_be_emailed():
    with patch.object(act.db_phones, "claim_activation_email",
                      new=AsyncMock(return_value=[_row()])), \
         _mail_world({"ok": True, "provider_id": "x", "error": None}) as send:
        out = await act.ensure_activation_email(tenant=_tenant(),
                                                row=_row(status="active", e164=""))
    assert out["status"] == notify.NEEDS_REVIEW
    send.assert_not_called()


def test_an_email_failure_cannot_touch_the_phone():
    import inspect
    src = inspect.getsource(act.ensure_activation_email)
    for forbidden in ("promote_permanent_cas", "update_number", "release_number",
                      "mark_released", "status"):
        assert f"db_phones.{forbidden}" not in src or forbidden.startswith("claim") \
            or forbidden.startswith("confirm") or forbidden.startswith("release_activation")


# ═══ 8. the temporary line ═══════════════════════════════════════════════

def test_a_temporary_number_stays_until_the_permanent_is_active():
    rows = [_row(purpose=lifecycle.PURPOSE_TEMPORARY, status="active", e164=TEMP_E164),
            _row(status=lifecycle.STATUS_PROVISIONING)]
    out = act.temporary_retirement_state(rows)
    assert out["eligible"] is False
    assert out["reason"] == "permanent_number_not_active_yet"


def test_an_active_permanent_makes_the_temporary_eligible_but_not_retired():
    rows = [_row(purpose=lifecycle.PURPOSE_TEMPORARY, status="active", e164=TEMP_E164),
            _row(status=lifecycle.STATUS_ACTIVE)]
    out = act.temporary_retirement_state(rows)
    assert out["eligible"] is True
    assert out["reason"] == "awaiting_grace_policy"


def test_no_grace_duration_is_invented():
    """Defaulting to the trial's seven days -- an unrelated number that happens
    to be nearby -- would quietly make that the policy."""
    import inspect
    src = inspect.getsource(act.temporary_retirement_state)
    for smell in ("timedelta", "days=", "hours=", "GRACE", "7", "30"):
        assert smell not in src, smell


def test_activation_never_retires_or_releases_the_temporary():
    referenced = identifiers(act)
    for forbidden in ("release_number", "mark_released", "release_tenant_number",
                      "retire"):
        assert forbidden not in referenced, forbidden


# ═══ 9. the customer status contract ═════════════════════════════════════

LEAKS = re.compile(
    r"\b(?:AC|AD|RN|PN|BU|IT)[0-9a-f]{32}\b|\bcus_|\bsub_|\bpm_|\bre_|"
    r"BundleSid|AddressSid|twilio|stripe|resend|vapi|HTTP \d{3}", re.I)


@pytest.mark.parametrize("status", [
    act.OK, act.HEALTH_UNKNOWN, act.HEALTH_FAILED, act.PROMOTION_LOST,
    act.SCALAR_CONFLICT, act.BILLING_SETUP_REQUIRED, act.BILLING_PENDING,
    act.NOTHING_TO_ACTIVATE, act.NOT_ELIGIBLE, act.NOT_FOUND,
    notify.NEEDS_REVIEW, act.EMAIL_PENDING, "something_new",
])
def test_every_outcome_has_a_safe_customer_status(status):
    view = act.customer_status(status, _row(status="active"))
    assert view["message"]
    assert not LEAKS.search(str(view)), view


def test_a_notification_problem_does_not_read_as_a_broken_number():
    """The customer's number is live, which is what they care about. The email
    is our problem."""
    for status in (notify.NEEDS_REVIEW, act.EMAIL_PENDING):
        view = act.customer_status(status, _row(status="active"))
        assert view["active"] is True
        assert view["status"] == act.ACTIVE_STATE


def test_a_number_is_shown_only_once_it_is_live():
    assert "number" not in act.customer_status(act.HEALTH_UNKNOWN, _row())
    assert act.customer_status(act.OK, _row(status="active"))["number"] == E164


# ═══ 10. nothing else changed ════════════════════════════════════════════

def test_the_activation_module_is_the_only_trial_starter_for_ireland():
    from routers import onboarding
    import inspect
    src = inspect.getsource(onboarding.provision)
    exit_at = src.index("REGULATORY_REQUIRED")
    assert exit_at < src.index("create_trial_subscription")


def test_flags_remain_off(monkeypatch):
    from services import onboarding_lifecycle as ob
    from services import permanent_numbers as perm
    from services import temporary_numbers as tmp
    for var in ("IRELAND_ONBOARDING_ENABLED", "IRELAND_PERMANENT_NUMBER_PURCHASE_ENABLED",
                "TEMP_NUMBER_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    assert ob.ireland_onboarding_enabled() is False
    assert perm.purchase_enabled() is False
    assert tmp.source_problem(tmp.source_policy()) == "temporary_numbers_disabled"


# ═══ 11. the real queries, not a fake standing in for them ═══════════════
#
# The sections above patch the repository so the ORCHESTRATION can be tested.
# Mutation testing found what that leaves unguarded twice over: deleting the
# fence from the notification claim, and rolling the phone back through a
# repository call the tests did not happen to watch. Both left everything green.

class _QueryRecorder:
    """Records the query built, and returns `rows`."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.calls = []
        self._cur = None

    def table(self, name):
        self._cur = {"table": name, "eq": {}, "is": {}, "not_is": {}, "patch": None}
        self.calls.append(self._cur)
        return self

    def update(self, patch):
        self._cur["patch"] = patch
        return self

    def eq(self, c, v):
        self._cur["eq"][c] = v
        return self

    def is_(self, c, v):
        self._cur["is"][c] = v
        return self

    @property
    def not_(self):
        outer = self

        class _Not:
            def is_(self, c, v):
                outer._cur["not_is"][c] = v
                return outer
        return _Not()

    def execute(self):
        return type("R", (), {"data": self.rows})()


@pytest.mark.asyncio
async def test_the_notification_claim_is_fenced_on_being_unclaimed():
    """WITHOUT `.is_("activation_email_claimed_at", "null")` every concurrent
    worker gets a row back, every one of them believes it won, and the customer
    gets an email per worker."""
    from db import phone_numbers as dbp
    rec = _QueryRecorder([_row()])
    with patch.object(dbp, "get_client", return_value=rec):
        await dbp.claim_activation_email(ROW)
    q = rec.calls[0]
    assert q["table"] == "tenant_phone_numbers"
    assert q["eq"] == {"id": ROW}
    assert q["is"] == {"activation_email_claimed_at": "null"}
    assert q["patch"]["activation_email_claimed_at"]


@pytest.mark.asyncio
async def test_the_confirm_is_fenced_against_overwriting_a_completed_send():
    from db import phone_numbers as dbp
    rec = _QueryRecorder([_row()])
    with patch.object(dbp, "get_client", return_value=rec):
        await dbp.confirm_activation_email(ROW, "resend_1")
    q = rec.calls[0]
    assert q["eq"] == {"id": ROW}
    assert q["is"] == {"activation_email_sent_at": "null"}
    assert q["not_is"] == {"activation_email_claimed_at": "null"}
    assert q["patch"]["activation_email_provider_id"] == "resend_1"


@pytest.mark.asyncio
async def test_releasing_a_claim_can_never_erase_a_recorded_send():
    from db import phone_numbers as dbp
    rec = _QueryRecorder([])
    with patch.object(dbp, "get_client", return_value=rec):
        await dbp.release_activation_email_claim(ROW)
    q = rec.calls[0]
    assert q["is"] == {"activation_email_sent_at": "null"}
    assert q["patch"]["activation_email_claimed_at"] is None


@pytest.mark.asyncio
async def test_no_repository_write_can_deactivate_a_live_number_after_billing_fails():
    """Broader than watching one function: the phone is live, and NOTHING in the
    post-promotion path may write to its row at all."""
    with patch.object(act.db, "mirror_permanent_number_fenced",
                      new=AsyncMock(return_value=[{"id": TENANT}])), \
         patch.object(act, "_tenant", new=AsyncMock(return_value=_tenant())), \
         patch.object(act, "_ensure_trial",
                      new=AsyncMock(return_value={"status": act.BILLING_PENDING,
                                                  "reason": "stripe_error"})), \
         patch.object(act.db_phones, "update_number", new=AsyncMock()) as upd, \
         patch.object(act.db_phones, "promote_permanent_cas", new=AsyncMock()) as cas, \
         patch.object(act.db_phones, "release_activation_email_claim",
                      new=AsyncMock()) as rel:
        out = await act._finish(tenant=_tenant(), row=_row(status="active"))
    assert out["status"] == act.BILLING_PENDING
    upd.assert_not_called()
    cas.assert_not_called()
    rel.assert_not_called()


def test_the_activation_path_never_writes_a_phone_status_outside_the_fence():
    """promote_permanent_cas is the ONLY status writer, and it only ever writes
    provisioning -> active."""
    referenced = identifiers(act)
    assert "update_number" not in referenced
    assert "promote_permanent_cas" in referenced
