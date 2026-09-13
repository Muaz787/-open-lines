"""Call-summary delivery preferences: what a tenant may choose, and where it goes.

TWO SEMANTICS, AND ONE TIMESTAMP DECIDES

    notification_prefs_set_at IS NULL      LEGACY   -- never asked
    notification_prefs_set_at IS NOT NULL  EXPLICIT -- the tenant chose

A production audit found 2 tenants depending on the legacy shared-destination
fallback for WhatsApp. Removing it without the legacy path would have stopped
their summaries silently, which is why the path exists and why these tests pin
it as tightly as the new behaviour.

CAPABILITY, NOT COUNTRY. SMS is sent FROM the tenant's own number; a voice-only
line cannot send one. No test here mentions a country, and neither does the code.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import notification_channels as nch

TENANT = "11111111-2222-4333-8444-555555555555"
EXPLICIT_AT = "2026-09-13T12:00:00+00:00"


def _t(**o):
    return {"id": TENANT, "business_name": "Acme", "email": "account@acme.com",
            "twilio_subaccount_sid": "AC_sub", "twilio_auth_token": "tok", **o}


def _explicit(**o):
    return _t(notification_prefs_set_at=EXPLICIT_AT, **o)


def _caps(sms: bool):
    return AsyncMock(return_value={"voice": True, "sms": sms, "mms": sms})


def _perm(e164="+14165550100"):
    return AsyncMock(return_value={"e164": e164, "purpose": "permanent",
                                   "status": "active"})


@pytest.fixture(autouse=True)
def _clear_cache():
    nch._capability_cache.clear()
    yield
    nch._capability_cache.clear()


# ═══ 1. explicit: no fallback of any kind ════════════════════════════════

def test_email_uses_its_own_destination_never_the_account_email():
    p = nch.preferences(_explicit(email_enabled=True,
                                  notification_email="alerts@acme.com"))
    assert p["channels"][nch.EMAIL]["destination"] == "alerts@acme.com"
    assert p["semantics"] == "explicit"


def test_an_explicit_tenant_never_falls_back_to_the_registration_email():
    """email is the account login; notification_email is the choice."""
    p = nch.preferences(_explicit(email_enabled=True, notification_email=""))
    assert p["channels"][nch.EMAIL]["enabled"] is False
    assert p["channels"][nch.EMAIL]["destination"] == ""


def test_sms_never_falls_back_to_the_business_phone():
    p = nch.preferences(_explicit(sms_enabled=True, sms_alert_number="",
                                  business_phone="+14165559999"))
    assert p["channels"][nch.SMS]["enabled"] is False
    assert p["channels"][nch.SMS]["destination"] == ""


def test_whatsapp_never_borrows_the_sms_number():
    p = nch.preferences(_explicit(whatsapp_enabled=True,
                                  sms_alert_number="+14165551111",
                                  whatsapp_alert_number=""))
    assert p["channels"][nch.WHATSAPP]["enabled"] is False


def test_whatsapp_never_falls_back_to_the_business_phone():
    p = nch.preferences(_explicit(whatsapp_enabled=True, whatsapp_alert_number="",
                                  business_phone="+14165559999"))
    assert p["channels"][nch.WHATSAPP]["enabled"] is False


def test_sms_and_whatsapp_keep_independent_destinations():
    p = nch.preferences(_explicit(
        sms_enabled=True, sms_alert_number="+14165551111",
        whatsapp_enabled=True, whatsapp_alert_number="+353871234567"))
    assert p["channels"][nch.SMS]["destination"] == "+14165551111"
    assert p["channels"][nch.WHATSAPP]["destination"] == "+353871234567"


@pytest.mark.parametrize("combo", [
    {"email_enabled": True, "notification_email": "a@b.com"},
    {"sms_enabled": True, "sms_alert_number": "+14165551111"},
    {"whatsapp_enabled": True, "whatsapp_alert_number": "+353871234567"},
    {"email_enabled": True, "notification_email": "a@b.com",
     "sms_enabled": True, "sms_alert_number": "+14165551111"},
    {"email_enabled": True, "notification_email": "a@b.com",
     "whatsapp_enabled": True, "whatsapp_alert_number": "+353871234567"},
    {"sms_enabled": True, "sms_alert_number": "+14165551111",
     "whatsapp_enabled": True, "whatsapp_alert_number": "+353871234567"},
    {"email_enabled": True, "notification_email": "a@b.com",
     "sms_enabled": True, "sms_alert_number": "+14165551111",
     "whatsapp_enabled": True, "whatsapp_alert_number": "+353871234567"},
])
def test_every_channel_combination_round_trips(combo):
    p = nch.preferences(_explicit(**combo))["channels"]
    for name in nch.CHANNELS:
        expected = bool(combo.get(f"{name if name != 'email' else 'email'}_enabled"))
        assert p[name]["enabled"] is expected, name


def test_dashboard_only_is_an_explicit_choice_with_nothing_enabled():
    p = nch.preferences(_explicit(email_enabled=False, sms_enabled=False,
                                  whatsapp_enabled=False))
    assert p["dashboard_only"] is True
    assert not any(c["enabled"] for c in p["channels"].values())


def test_dashboard_only_sends_nothing_even_with_destinations_on_file():
    """Turning a channel off must not be undone by a leftover destination."""
    p = nch.preferences(_explicit(
        email_enabled=False, notification_email="alerts@acme.com",
        sms_enabled=False, sms_alert_number="+14165551111",
        whatsapp_enabled=False, whatsapp_alert_number="+353871234567"))
    assert p["dashboard_only"] is True


# ═══ 2. legacy: today's behaviour, preserved exactly ═════════════════════

def test_a_legacy_tenant_is_never_called_dashboard_only():
    """They were never asked. Calling their silence a choice would assert
    something they did not say -- and would justify a future default."""
    p = nch.preferences(_t(email_enabled=False, sms_enabled=False,
                           whatsapp_enabled=False))
    assert p["semantics"] == "legacy"
    assert p["dashboard_only"] is False


def test_legacy_whatsapp_still_uses_the_shared_sms_number():
    """The 2 production tenants this exists for."""
    p = nch.preferences(_t(whatsapp_enabled=True,
                           sms_alert_number="+14165551111"))
    assert p["channels"][nch.WHATSAPP]["enabled"] is True
    assert p["channels"][nch.WHATSAPP]["destination"] == "+14165551111"


def test_legacy_sms_still_falls_back_to_the_business_phone():
    p = nch.preferences(_t(sms_enabled=True, business_phone="+14165559999"))
    assert p["channels"][nch.SMS]["enabled"] is True
    assert p["channels"][nch.SMS]["destination"] == "+14165559999"


def test_legacy_email_still_defaults_to_enabled():
    p = nch.preferences(_t(notification_email="owner@acme.com"))
    assert p["channels"][nch.EMAIL]["enabled"] is True


def test_a_legacy_tenant_given_an_explicit_whatsapp_number_is_honoured():
    p = nch.preferences(_t(whatsapp_enabled=True, sms_alert_number="+14165551111",
                           whatsapp_alert_number="+353871234567"))
    assert p["channels"][nch.WHATSAPP]["destination"] == "+353871234567"


def test_the_legacy_path_is_quarantined_in_one_function():
    import inspect
    explicit = inspect.getsource(nch._explicit_channels)
    for fallback in ("business_phone", "or shared", "sms_alert_number"):
        assert fallback not in explicit or fallback == "sms_alert_number"
    assert "business_phone" not in explicit
    assert "business_phone" in inspect.getsource(nch._legacy_channels)


# ═══ 3. SMS capability: from the LONG-TERM number ═══════════════════════

@pytest.mark.asyncio
async def test_sms_is_offered_when_the_permanent_number_supports_it():
    with patch.object(nch, "_capability_cache", {}), \
         patch("db.phone_numbers.get_current_permanent", new=_perm()), \
         patch("services.telephony.number_capabilities", new=_caps(True)):
        out = await nch.eligible_channels(_t())
    assert out[nch.SMS]["eligible"] is True


@pytest.mark.asyncio
async def test_sms_is_not_offered_for_a_voice_only_number():
    with patch("db.phone_numbers.get_current_permanent", new=_perm("+353871234567")), \
         patch("services.telephony.number_capabilities", new=_caps(False)):
        out = await nch.eligible_channels(_t())
    assert out[nch.SMS]["eligible"] is False
    assert out[nch.SMS]["reason"] == nch.NOT_SMS_CAPABLE


@pytest.mark.asyncio
async def test_a_temporary_test_number_never_makes_sms_appear():
    """THE trap. A regulated tenant may hold a Canadian test line for weeks; its
    SMS capability must not advertise a channel that dies the day their
    voice-only permanent number arrives."""
    probed = []

    async def caps(sub_sid, sub_tok, e164):
        probed.append(e164)
        return {"voice": True, "sms": True, "mms": True}

    # The canonical permanent row is the only source; there is no permanent
    # number yet, so nothing is probed and nothing is offered.
    with patch("db.phone_numbers.get_current_permanent", new=AsyncMock(return_value=None)), \
         patch("services.telephony.number_capabilities", new=caps):
        out = await nch.eligible_channels(_t(twilio_phone_number="+14165550100"))
    assert out[nch.SMS]["eligible"] is False
    assert out[nch.SMS]["reason"] == nch.NO_LONG_TERM_NUMBER
    assert probed == [], "probed a number that is not the long-term one"


@pytest.mark.asyncio
async def test_an_unreadable_provider_does_not_offer_sms():
    """Unknown is not eligible. An outage is not evidence of capability."""
    with patch("db.phone_numbers.get_current_permanent", new=_perm()), \
         patch("services.telephony.number_capabilities",
               new=AsyncMock(return_value=None)):
        out = await nch.eligible_channels(_t())
    assert out[nch.SMS]["eligible"] is False
    assert out[nch.SMS]["reason"] == nch.CAPABILITY_UNKNOWN


@pytest.mark.asyncio
async def test_capability_is_cached_rather_than_probed_per_render():
    calls = []

    async def caps(sub_sid, sub_tok, e164):
        calls.append(e164)
        return {"voice": True, "sms": True, "mms": False}

    with patch("db.phone_numbers.get_current_permanent", new=_perm()), \
         patch("services.telephony.number_capabilities", new=caps):
        for _ in range(5):
            await nch.eligible_channels(_t())
    assert len(calls) == 1, calls


@pytest.mark.asyncio
async def test_a_failed_probe_is_not_cached():
    calls = []

    async def caps(sub_sid, sub_tok, e164):
        calls.append(e164)
        return None

    with patch("db.phone_numbers.get_current_permanent", new=_perm()), \
         patch("services.telephony.number_capabilities", new=caps):
        await nch.eligible_channels(_t())
        await nch.eligible_channels(_t())
    assert len(calls) == 2, "an outage was cached"


def test_no_country_appears_in_the_capability_logic():
    import ast, inspect, textwrap
    for fn in (nch._sms_eligibility, nch.eligible_channels):
        fn_ast = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
        if (fn_ast.body and isinstance(fn_ast.body[0], ast.Expr)
                and isinstance(fn_ast.body[0].value, ast.Constant)):
            fn_ast.body = fn_ast.body[1:]
        code = ast.unparse(fn_ast)
        for smell in ('"IE"', "'IE'", "iso_country", "business_country_code",
                      "needs_regulatory_clearance", "+353"):
            assert smell not in code, f"{fn.__name__}: {smell}"


# ═══ 4. WhatsApp availability comes from the real sender ════════════════

@pytest.mark.asyncio
async def test_whatsapp_is_offered_only_when_sender_and_template_exist(monkeypatch):
    from services import telephony
    monkeypatch.setattr(telephony, "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    monkeypatch.setattr(telephony, "TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID", "HX123")
    with patch("db.phone_numbers.get_current_permanent", new=AsyncMock(return_value=None)):
        out = await nch.eligible_channels(_t())
    assert out[nch.WHATSAPP]["eligible"] is True


@pytest.mark.asyncio
async def test_whatsapp_is_withheld_when_the_template_is_missing(monkeypatch):
    from services import telephony
    monkeypatch.setattr(telephony, "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    monkeypatch.setattr(telephony, "TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID", "")
    with patch("db.phone_numbers.get_current_permanent", new=AsyncMock(return_value=None)):
        out = await nch.eligible_channels(_t())
    assert out[nch.WHATSAPP]["eligible"] is False
    assert out[nch.WHATSAPP]["reason"] == nch.SENDER_NOT_CONFIGURED


def test_whatsapp_availability_is_the_real_dependency_not_a_new_flag():
    import inspect
    src = inspect.getsource(nch.eligible_channels)
    assert "TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID" in src and "_wa_from" in src
    assert "getenv" not in src


# ═══ 5. validation ══════════════════════════════════════════════════════

@pytest.mark.parametrize("patch_,current", [
    ({"email_enabled": True}, {}),
    ({"sms_enabled": True}, {}),
    ({"whatsapp_enabled": True}, {}),
    ({"email_enabled": True, "notification_email": ""}, {}),
    ({"sms_enabled": True}, {"sms_alert_number": None}),
])
def test_enabling_a_channel_without_a_destination_is_refused(patch_, current):
    with pytest.raises(nch.PreferenceError):
        nch.validate_explicit(patch_, current=current)


def test_a_destination_supplied_earlier_satisfies_a_later_enable():
    nch.validate_explicit({"sms_enabled": True},
                          current={"sms_alert_number": "+14165551111"})


def test_dashboard_only_needs_no_destination():
    nch.validate_explicit({"email_enabled": False, "sms_enabled": False,
                           "whatsapp_enabled": False}, current={})


def test_validation_never_repairs_by_falling_back():
    import inspect
    src = inspect.getsource(nch.validate_explicit)
    assert "business_phone" not in src


# ═══ 6. masking ═════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw", ["owner@acme.com", "+353871234567", "+14165551111"])
def test_operational_logs_never_carry_a_full_destination(raw):
    masked = nch.mask(raw)
    assert raw not in masked
    assert "***" in masked


# ═══ 7. tenant isolation, and the server-owned timestamp ════════════════

@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import onboarding
    app = FastAPI()
    app.include_router(onboarding.router)
    monkeypatch.setattr(onboarding.limiter, "enabled", False, raising=False)
    return TestClient(app, raise_server_exceptions=False)


OTHER = "99999999-8888-4777-8666-555555555555"


def test_the_timestamp_is_not_on_the_request_model():
    """A client cannot forge, choose or clear it because there is no field to
    put it in -- nothing to strip, and nothing to forget to strip."""
    from routers import onboarding
    assert "notification_prefs_set_at" not in onboarding.SettingsUpdateRequest.model_fields


def test_a_forged_timestamp_in_the_payload_is_ignored(client):
    from routers import onboarding
    saved = {}

    async def update(tid, patch):
        saved.update(patch); return {"id": tid}

    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.get_tenant_by_id",
               new=AsyncMock(return_value={"id": TENANT})), \
         patch("db.supabase.update_tenant", new=update):
        r = client.patch(f"/onboarding/settings/{TENANT}", json={
            "email_enabled": True, "notification_email": "a@b.com",
            "notification_prefs_set_at": "1999-01-01T00:00:00+00:00"})
    assert r.status_code == 200
    assert saved["notification_prefs_set_at"] != "1999-01-01T00:00:00+00:00"
    assert saved["notification_prefs_set_at"].startswith("20")


def test_the_timestamp_cannot_be_cleared_to_regain_legacy_behaviour(client):
    from routers import onboarding
    saved = {}

    async def update(tid, patch):
        saved.update(patch); return {"id": tid}

    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.get_tenant_by_id",
               new=AsyncMock(return_value={"id": TENANT,
                                           "notification_prefs_set_at": EXPLICIT_AT})), \
         patch("db.supabase.update_tenant", new=update):
        r = client.patch(f"/onboarding/settings/{TENANT}", json={
            "email_enabled": True, "notification_email": "a@b.com",
            "notification_prefs_set_at": None})
    assert r.status_code == 200
    # Already explicit: not restamped, and certainly not cleared.
    assert "notification_prefs_set_at" not in saved


def test_an_already_explicit_tenant_is_not_restamped(client):
    from routers import onboarding
    saved = {}

    async def update(tid, patch):
        saved.update(patch); return {"id": tid}

    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.get_tenant_by_id",
               new=AsyncMock(return_value={"id": TENANT,
                                           "notification_prefs_set_at": EXPLICIT_AT,
                                           "notification_email": "a@b.com"})), \
         patch("db.supabase.update_tenant", new=update):
        client.patch(f"/onboarding/settings/{TENANT}", json={"email_enabled": True})
    assert "notification_prefs_set_at" not in saved


def test_the_first_explicit_save_stamps_the_timestamp(client):
    from routers import onboarding
    saved = {}

    async def update(tid, patch):
        saved.update(patch); return {"id": tid}

    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.get_tenant_by_id",
               new=AsyncMock(return_value={"id": TENANT})), \
         patch("db.supabase.update_tenant", new=update):
        client.patch(f"/onboarding/settings/{TENANT}", json={
            "email_enabled": False, "sms_enabled": False, "whatsapp_enabled": False})
    assert saved["notification_prefs_set_at"]


@pytest.mark.parametrize("path", ["/onboarding/settings/{t}",
                                  "/onboarding/notification-options/{t}"])
def test_every_preference_route_is_tenant_authenticated(path):
    """Asserted structurally: a route added later without the check fails here."""
    import inspect
    from routers import onboarding
    target = path.split("/")[-2] if path.endswith("{t}") else path
    for route in onboarding.router.routes:
        if getattr(route, "path", "") == path.replace("/{t}", "/{tenant_id}"):
            src = inspect.getsource(route.endpoint)
            assert "verify_tenant_owner" in src, route.path
            return
    raise AssertionError(f"route not found: {path}")


def test_a_cross_tenant_write_is_refused_by_the_owner_check(client):
    from routers import onboarding
    from fastapi import HTTPException

    async def deny(tid, auth):
        raise HTTPException(status_code=403, detail="Forbidden")

    with patch.object(onboarding, "verify_tenant_owner", new=deny), \
         patch("db.supabase.update_tenant",
               new=AsyncMock(side_effect=AssertionError("WROTE ANOTHER TENANT"))):
        r = client.patch(f"/onboarding/settings/{OTHER}",
                         json={"email_enabled": True, "notification_email": "a@b.com"})
    assert r.status_code == 403


def test_a_cross_tenant_read_is_refused(client):
    from routers import onboarding
    from fastapi import HTTPException

    async def deny(tid, auth):
        raise HTTPException(status_code=403, detail="Forbidden")

    with patch.object(onboarding, "verify_tenant_owner", new=deny):
        r = client.get(f"/onboarding/notification-options/{OTHER}")
    assert r.status_code == 403
    assert "destination" not in r.text


def test_the_write_is_scoped_to_the_path_tenant_only(client):
    """The body carries no tenant identifier, so there is nothing to disagree
    with the authenticated path."""
    from routers import onboarding
    assert not any("tenant" in f for f in onboarding.SettingsUpdateRequest.model_fields)


def test_enabling_a_channel_with_no_destination_is_refused_server_side(client):
    from routers import onboarding
    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.get_tenant_by_id",
               new=AsyncMock(return_value={"id": TENANT})), \
         patch("db.supabase.update_tenant",
               new=AsyncMock(side_effect=AssertionError("STORED AN EMPTY CHANNEL"))):
        r = client.patch(f"/onboarding/settings/{TENANT}",
                         json={"whatsapp_enabled": True})
    assert r.status_code == 400


@pytest.mark.parametrize("bad", ["not-a-phone", "+1", "abc123", "12345678901234567890"])
def test_a_malformed_phone_destination_is_refused(client, bad):
    from routers import onboarding
    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.update_tenant",
               new=AsyncMock(side_effect=AssertionError("STORED A BAD NUMBER"))):
        r = client.patch(f"/onboarding/settings/{TENANT}",
                         json={"whatsapp_alert_number": bad})
    assert r.status_code == 422


def test_changing_the_account_email_does_not_rewrite_the_notification_email():
    """Two different fields, and only one of them is the tenant's choice."""
    from routers import onboarding
    assert "email" not in onboarding.SettingsUpdateRequest.model_fields
    p = nch.preferences(_explicit(email_enabled=True,
                                  notification_email="alerts@acme.com",
                                  email="new-login@acme.com"))
    assert p["channels"][nch.EMAIL]["destination"] == "alerts@acme.com"


# ═══ 8. the dispatcher obeys the model, and nothing else ════════════════

async def _dispatch(tenant, *, email_fails=False, sms_fails=False, wa_fails=False):
    """Run the real end-of-call notification block and record what was sent."""
    from services import webhook_processor as wp
    sent = {"email": [], "sms": [], "whatsapp": []}

    async def send_email(**kw):
        if email_fails:
            raise RuntimeError("resend down")
        sent["email"].append(kw["to"])

    async def send_sms(**kw):
        if sms_fails:
            raise RuntimeError("twilio down")
        sent["sms"].append(kw["to_number"])
        return True

    async def send_wa(to, sid, variables):
        if wa_fails:
            raise RuntimeError("whatsapp down")
        sent["whatsapp"].append(to)
        return True

    import services.email as email_mod
    with patch.object(email_mod, "send_call_summary_email", new=send_email), \
         patch.object(wp.telephony, "send_sms", new=send_sms), \
         patch.object(wp.telephony, "send_whatsapp_template", new=send_wa), \
         patch.object(wp.telephony, "TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID", "HX1"):
        await wp._dispatch_call_summary(
            tenant=tenant, business_name="Acme",
            analysis={"summary": "Caller asked about hours."},
            caller_number="+14165550000", tenant_id=TENANT, _distinct="d")
    return sent


@pytest.mark.asyncio
async def test_only_selected_channels_receive_the_summary():
    sent = await _dispatch(_explicit(
        email_enabled=True, notification_email="alerts@acme.com",
        whatsapp_enabled=True, whatsapp_alert_number="+353871234567",
        sms_enabled=False, sms_alert_number="+14165551111",
        twilio_subaccount_sid="AC", twilio_auth_token="tok",
        twilio_phone_number="+14165550100"))
    assert sent["email"] == ["alerts@acme.com"]
    assert sent["whatsapp"] == ["+353871234567"]
    assert sent["sms"] == [], "sent to an unselected channel"


@pytest.mark.asyncio
async def test_dashboard_only_sends_nothing_externally():
    sent = await _dispatch(_explicit(
        email_enabled=False, sms_enabled=False, whatsapp_enabled=False,
        notification_email="alerts@acme.com", sms_alert_number="+14165551111",
        whatsapp_alert_number="+353871234567", business_phone="+14165559999",
        email="account@acme.com"))
    assert sent == {"email": [], "sms": [], "whatsapp": []}


@pytest.mark.asyncio
async def test_whatsapp_uses_its_own_number_not_the_sms_one():
    sent = await _dispatch(_explicit(
        whatsapp_enabled=True, whatsapp_alert_number="+353871234567",
        sms_alert_number="+14165551111"))
    assert sent["whatsapp"] == ["+353871234567"]


@pytest.mark.asyncio
async def test_a_failing_channel_does_not_divert_to_another():
    """WhatsApp failing must not quietly email the registration address."""
    sent = await _dispatch(_explicit(
        whatsapp_enabled=True, whatsapp_alert_number="+353871234567",
        notification_email="alerts@acme.com", email="account@acme.com"),
        wa_fails=True)
    assert sent["whatsapp"] == [] and sent["email"] == []


@pytest.mark.asyncio
async def test_one_channel_failing_does_not_suppress_another():
    sent = await _dispatch(_explicit(
        email_enabled=True, notification_email="alerts@acme.com",
        whatsapp_enabled=True, whatsapp_alert_number="+353871234567"),
        wa_fails=True)
    assert sent["email"] == ["alerts@acme.com"]


@pytest.mark.asyncio
async def test_a_legacy_tenant_still_receives_what_they_receive_today():
    """The 2 production tenants on the shared destination."""
    sent = await _dispatch(_t(
        whatsapp_enabled=True, sms_alert_number="+14165551111",
        notification_email="owner@acme.com"))
    assert sent["whatsapp"] == ["+14165551111"]
    assert sent["email"] == ["owner@acme.com"]


@pytest.mark.asyncio
async def test_an_explicit_tenant_never_uses_the_business_phone():
    sent = await _dispatch(_explicit(
        sms_enabled=True, sms_alert_number="", business_phone="+14165559999",
        twilio_subaccount_sid="AC", twilio_auth_token="tok",
        twilio_phone_number="+14165550100"))
    assert sent["sms"] == []


# ═══ 9. the E.164 boundary, in both places that enforce it ══════════════
# E.164 allows at most 15 digits. The first draft of migration 037 wrote
# [1-9][0-9]{6,15}, which is 7 to SIXTEEN -- one too many, and looser than the
# rule the repository already had in customer_identity. These pin the boundary
# and pin the two enforcement points together.

VALID_E164 = [
    "+1416555" + "0100",        # 11 digits, ordinary NANP
    "+353871234567",            # 12 digits, Irish mobile
    "+4407911123456",           # 13 digits
    "+1234567",                 # 7 digits -- the canonical minimum
    "+123456789012345",         # 15 digits -- the ITU maximum, valid
]
INVALID_E164 = [
    "14165550100",              # no leading +
    "+0416555010",              # leading zero after +
    "+123456",                  # 6 digits -- below the minimum
    "+1234567890123456",        # 16 digits -- ONE over the maximum
    "+12345678901234567890",    # far over
    "+1416555010a",             # letters
    "+1 416 555 0100",          # spaces survive into the persisted value
    "+1-416-555-0100",          # punctuation survives
    "++14165550100",
    "+",
    "",
]


@pytest.mark.parametrize("value", VALID_E164)
def test_the_canonical_validator_accepts_storable_numbers(value):
    from services import telephony
    assert telephony.is_e164(value) is True, value


@pytest.mark.parametrize("value", INVALID_E164)
def test_the_canonical_validator_refuses_everything_else(value):
    from services import telephony
    assert telephony.is_e164(value) is False, value


def test_fifteen_digits_is_valid_and_sixteen_is_not():
    """The exact boundary the first draft got wrong."""
    from services import telephony
    assert telephony.is_e164("+" + "1" * 15) is True
    assert telephony.is_e164("+" + "1" * 16) is False


def test_the_repository_has_exactly_one_e164_rule():
    """customer_identity restated it once already. A third copy is how a
    16-digit destination reaches a provider that will not dial it."""
    from services import customer_identity, telephony
    for value in VALID_E164 + INVALID_E164:
        assert bool(customer_identity._E164.fullmatch(value)) is telephony.is_e164(value), value


def test_the_migration_regex_matches_the_python_rule_exactly():
    """The DB CHECK and the application validator must accept the same set.
    Read from the migration file itself, so editing one without the other fails."""
    import pathlib
    import re as _re
    from services import telephony
    sql = (pathlib.Path(__file__).resolve().parents[2]
           / "migrations" / "037_call_summary_preferences.sql").read_text()
    found = _re.findall(r"whatsapp_alert_number ~ '([^']+)'", sql)
    assert len(found) == 1, found
    db_rule = _re.compile(found[0])
    for value in VALID_E164 + INVALID_E164:
        assert bool(db_rule.fullmatch(value)) is telephony.is_e164(value), value


@pytest.mark.parametrize("bad", ["+1234567890123456", "+123456", "+0416555010"])
def test_the_settings_api_refuses_what_the_database_would(client, bad):
    """A message, not a 500 from a constraint violation."""
    from routers import onboarding
    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.update_tenant",
               new=AsyncMock(side_effect=AssertionError("STORED AN INVALID NUMBER"))):
        r = client.patch(f"/onboarding/settings/{TENANT}",
                         json={"whatsapp_alert_number": bad})
    assert r.status_code == 422, bad


def test_formatted_input_is_normalised_before_it_is_validated(client):
    """The input layer may accept formatting; the PERSISTED value must not."""
    from routers import onboarding
    saved = {}

    async def update(tid, patch):
        saved.update(patch); return {"id": tid}

    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value={"id": TENANT})), \
         patch("db.supabase.update_tenant", new=update):
        r = client.patch(f"/onboarding/settings/{TENANT}",
                         json={"whatsapp_alert_number": "(416) 555-0100"})
    assert r.status_code == 200
    from services import telephony
    assert telephony.is_e164(saved["whatsapp_alert_number"])
    assert " " not in saved["whatsapp_alert_number"]


# ═══ 10. capability is ENFORCED, not merely hidden ══════════════════════
# Hiding SMS in the picker is not enforcement: the API is reachable directly.

def _cap(sms=False, whatsapp=True):
    async def _f(tenant):
        return {nch.EMAIL: {"eligible": True, "reason": ""},
                nch.SMS: {"eligible": sms,
                          "reason": "" if sms else nch.NOT_SMS_CAPABLE},
                nch.WHATSAPP: {"eligible": whatsapp,
                               "reason": "" if whatsapp else nch.SENDER_NOT_CONFIGURED}}
    return _f


@pytest.mark.asyncio
async def test_enabling_sms_on_a_voice_only_number_is_refused():
    with patch.object(nch, "eligible_channels", new=_cap(sms=False)):
        with pytest.raises(nch.PreferenceError):
            await nch.validate_capability(
                {"sms_enabled": True, "sms_alert_number": "+14165551111"},
                current={}, tenant=_t())


@pytest.mark.asyncio
async def test_a_crafted_api_request_cannot_enable_unsupported_sms(client):
    """The UI never offers it; this proves the API refuses it anyway."""
    from routers import onboarding
    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value={"id": TENANT})), \
         patch.object(nch, "eligible_channels", new=_cap(sms=False)), \
         patch("db.supabase.update_tenant",
               new=AsyncMock(side_effect=AssertionError("STORED AN IMPOSSIBLE CHANNEL"))):
        r = client.patch(f"/onboarding/settings/{TENANT}", json={
            "sms_enabled": True, "sms_alert_number": "+14165551111"})
    assert r.status_code == 400
    assert "sms_alert_number" not in r.text.lower() or "+1416" not in r.text


@pytest.mark.asyncio
async def test_enabling_whatsapp_without_a_sender_is_refused():
    with patch.object(nch, "eligible_channels", new=_cap(whatsapp=False)):
        with pytest.raises(nch.PreferenceError):
            await nch.validate_capability(
                {"whatsapp_enabled": True, "whatsapp_alert_number": "+353871234567"},
                current={}, tenant=_t())


@pytest.mark.asyncio
async def test_an_unknown_capability_refuses_the_enable_rather_than_guessing():
    async def unknown(tenant):
        return {nch.EMAIL: {"eligible": True, "reason": ""},
                nch.SMS: {"eligible": False, "reason": nch.CAPABILITY_UNKNOWN},
                nch.WHATSAPP: {"eligible": True, "reason": ""}}
    with patch.object(nch, "eligible_channels", new=unknown):
        with pytest.raises(nch.PreferenceError):
            await nch.validate_capability(
                {"sms_enabled": True, "sms_alert_number": "+14165551111"},
                current={}, tenant=_t())


@pytest.mark.asyncio
async def test_a_tenant_already_on_sms_is_not_blocked_from_other_edits():
    """Only NEWLY enabled channels are checked. A capability blip must not trap
    someone, or stop them editing an unrelated field."""
    with patch.object(nch, "eligible_channels", new=_cap(sms=False)):
        await nch.validate_capability(
            {"notification_email": "new@acme.com"},
            current={"sms_enabled": True, "sms_alert_number": "+14165551111"},
            tenant=_t())


@pytest.mark.asyncio
async def test_turning_a_channel_off_is_always_allowed():
    """Otherwise a capability change could trap a tenant in a configuration
    they cannot leave."""
    with patch.object(nch, "eligible_channels",
                      new=_cap(sms=False, whatsapp=False)):
        await nch.validate_capability(
            {"sms_enabled": False, "whatsapp_enabled": False},
            current={"sms_enabled": True, "whatsapp_enabled": True}, tenant=_t())


@pytest.mark.asyncio
async def test_an_available_channel_is_accepted():
    with patch.object(nch, "eligible_channels", new=_cap(sms=True)):
        await nch.validate_capability(
            {"sms_enabled": True, "sms_alert_number": "+14165551111"},
            current={}, tenant=_t())


@pytest.mark.asyncio
async def test_a_capability_change_never_erases_a_stored_destination():
    """Stage L: do not rewrite preferences because a probe failed."""
    import inspect
    src = inspect.getsource(nch.validate_capability)
    for destructive in ("update_tenant", "= None", "= \"\"", "del "):
        assert destructive not in src, destructive


@pytest.mark.asyncio
async def test_an_available_channel_still_needs_a_destination(client):
    """Capability and destination are separate refusals. With WhatsApp fully
    available, only destination validation can reject an empty destination --
    so this is the case that proves that check is still doing work."""
    from routers import onboarding
    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value={"id": TENANT})), \
         patch.object(nch, "eligible_channels", new=_cap(sms=True, whatsapp=True)), \
         patch("db.supabase.update_tenant",
               new=AsyncMock(side_effect=AssertionError("STORED AN EMPTY DESTINATION"))):
        r = client.patch(f"/onboarding/settings/{TENANT}", json={"whatsapp_enabled": True})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_a_capable_channel_with_a_destination_is_accepted(client):
    """The positive counterpart, so the two refusals above are not vacuous."""
    from routers import onboarding
    saved = {}

    async def update(tid, patch_):
        saved.update(patch_); return {"id": tid}

    with patch.object(onboarding, "verify_tenant_owner", new=AsyncMock()), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value={"id": TENANT})), \
         patch.object(nch, "eligible_channels", new=_cap(sms=True, whatsapp=True)), \
         patch("db.supabase.update_tenant", new=update):
        r = client.patch(f"/onboarding/settings/{TENANT}", json={
            "whatsapp_enabled": True, "whatsapp_alert_number": "+353871234567"})
    assert r.status_code == 200
    assert saved["whatsapp_alert_number"] == "+353871234567"
    assert saved["notification_prefs_set_at"]
