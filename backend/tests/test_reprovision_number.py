"""Giving a returning tenant a working phone line again.

The counterpart to reclaiming a number. We keep the tenant row when we release,
so their knowledge base and settings survive — without this they'd come back to a
working account with no phone line and no way to get one, since provision_tenant()
only ever runs at signup.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import provisioning
import db.supabase as _supabase_mod  # noqa: F401  (registers the dotted path for patch())
import db.phone_numbers as _phones_mod  # noqa: F401


def _canonical_patches():
    """W9I-B: reprovision records the number in tenant_phone_numbers as well as
    the legacy scalar, through services.phone_registry. Modelled here so these
    tests keep asserting what they are about -- purchase, import and rollback --
    rather than the new persistence step."""
    import contextlib
    stack = contextlib.ExitStack()
    for cm in (
        # W9I-B.1: the preflight asks the canonical model whether this tenant
        # already holds a permanent number BEFORE spending money. These tests
        # are about what happens once that has passed, so it answers "no".
        patch("services.phone_registry.current_permanent_conflict",
              new=AsyncMock(return_value=None)),
        patch("services.phone_registry.register_permanent",
              new=AsyncMock(return_value={"status": "ok",
                                          "row": {"id": "phone-row-reprov"},
                                          "created": True})),
        patch("services.phone_registry.mark_active",
              new=AsyncMock(return_value={"status": "ok", "row": {}})),
    ):
        stack.enter_context(cm)
    return stack


def _tenant(**over):
    """A returning tenant: subaccount and assistant intact, number reclaimed."""
    return {
        "id": "t1", "business_name": "Acme", "country": "CA",
        "twilio_phone_number": None,
        "twilio_subaccount_sid": "AC_sub", "twilio_auth_token": "tok",
        "vapi_assistant_id": "asst_1",
        "number_released_at": "2026-07-01T00:00:00+00:00",
        "number_release_warn1_sent": True,
        "number_release_warn2_sent": True,
        **over,
    }


@pytest.mark.asyncio
async def test_buys_imports_and_clears_the_reclaim_history():
    with _canonical_patches(), patch("services.telephony.find_available_number", new=AsyncMock(return_value="+14165550999")), \
         patch("services.telephony.purchase_number_with_sid",
               new=AsyncMock(return_value=("+14165550999", "PN_reprov"))), \
         patch("services.vapi.import_twilio_number", new=AsyncMock(return_value="vapi_pn_new")), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await provisioning.reprovision_tenant_number(_tenant())

    assert res["provisioned"] is True and res["number"] == "+14165550999"

    wrote = upd.call_args.args[1]
    # W9I-B: the legacy scalar is now mirrored by phone_registry.mark_active --
    # the single path that owns both it and the canonical row -- so it is no
    # longer part of this update. `res["number"]` above is the assertion that the
    # number was actually adopted.
    assert "twilio_phone_number" not in wrote
    assert wrote["vapi_phone_number_id"] == "vapi_pn_new"
    # Without this the new number could never be reclaimed again: release_due_at()
    # returns None for anything carrying a number_released_at, and the stale warn
    # flags would suppress the notices they'd be owed next time.
    assert wrote["number_released_at"] is None
    assert wrote["number_release_warn1_sent"] is False
    assert wrote["number_release_warn2_sent"] is False


@pytest.mark.asyncio
async def test_refuses_a_tenant_that_already_has_a_number():
    """This spends money on a real number. Buying a second one silently would be
    a recurring charge nobody notices."""
    with _canonical_patches(), patch("services.telephony.purchase_number_with_sid", new=AsyncMock()) as buy:
        res = await provisioning.reprovision_tenant_number(
            _tenant(twilio_phone_number="+14165550100")
        )
    assert res["provisioned"] is False and res["reason"] == "tenant_already_has_a_number"
    buy.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_vapi_import_hands_the_number_straight_back():
    """We'd otherwise own — and be billed monthly for — a line that can never ring."""
    with _canonical_patches(), patch("services.telephony.find_available_number", new=AsyncMock(return_value="+14165550999")), \
         patch("services.telephony.purchase_number_with_sid",
               new=AsyncMock(return_value=("+14165550999", "PN_reprov"))), \
         patch("services.vapi.import_twilio_number", new=AsyncMock(side_effect=RuntimeError("vapi down"))), \
         patch("services.telephony.release_number", new=AsyncMock()) as release, \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await provisioning.reprovision_tenant_number(_tenant())

    assert res["provisioned"] is False and res["reason"] == "vapi_import_failed"
    release.assert_awaited_once()
    assert release.call_args.args[2] == "+14165550999"
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_purchase_changes_nothing():
    with _canonical_patches(), patch("services.telephony.find_available_number", new=AsyncMock(return_value="+14165550999")), \
         patch("services.telephony.purchase_number_with_sid",
               new=AsyncMock(side_effect=RuntimeError("twilio down"))), \
         patch("services.vapi.import_twilio_number", new=AsyncMock()) as imp, \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await provisioning.reprovision_tenant_number(_tenant())

    assert res["provisioned"] is False and res["reason"] == "twilio_purchase_failed"
    imp.assert_not_called()
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_a_lost_db_write_reports_the_live_number_for_reconciliation():
    """Twilio is already billing for it, so the number has to come back in the
    result or it becomes an untraceable charge."""
    with _canonical_patches(), patch("services.telephony.find_available_number", new=AsyncMock(return_value="+14165550999")), \
         patch("services.telephony.purchase_number_with_sid",
               new=AsyncMock(return_value=("+14165550999", "PN_reprov"))), \
         patch("services.vapi.import_twilio_number", new=AsyncMock(return_value="vapi_pn_new")), \
         patch("db.supabase.update_tenant", new=AsyncMock(side_effect=RuntimeError("db down"))):
        res = await provisioning.reprovision_tenant_number(_tenant())

    assert res["provisioned"] is False and res["reason"] == "db_write_failed"
    assert res["number"] == "+14165550999"


@pytest.mark.asyncio
@pytest.mark.parametrize("missing,reason", [
    ({"twilio_auth_token": ""},  "missing_twilio_credentials"),
    ({"vapi_assistant_id": ""},  "no_assistant_on_tenant"),
])
async def test_an_incomplete_tenant_is_refused_rather_than_half_built(missing, reason):
    with _canonical_patches(), patch("services.telephony.purchase_number_with_sid", new=AsyncMock()) as buy:
        res = await provisioning.reprovision_tenant_number(_tenant(**missing))
    assert res["provisioned"] is False and res["reason"] == reason
    buy.assert_not_called()


@pytest.mark.asyncio
async def test_the_new_number_stays_local_to_their_published_one():
    with _canonical_patches(), patch("services.telephony.find_available_number", new=AsyncMock(return_value="+19055550999")) as find, \
         patch("services.telephony.purchase_number", new=AsyncMock(return_value="+19055550999")), \
         patch("services.vapi.import_twilio_number", new=AsyncMock(return_value="vapi_pn_new")), \
         patch("db.supabase.update_tenant", new=AsyncMock()):
        await provisioning.reprovision_tenant_number(_tenant(business_phone="+19055551234"))

    assert find.call_args.kwargs["preferred_area_code"] == "905"
