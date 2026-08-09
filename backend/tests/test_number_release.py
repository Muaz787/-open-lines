"""Releasing a tenant's phone number.

This is the most destructive operation in the codebase: Twilio can reassign a
released number, so a business that loses one loses it permanently and its
callers eventually reach a stranger. The tests that matter here are the ones
pinning ORDER and the refusal to proceed after a partial failure — not the happy
path.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import provisioning, retention
import db.supabase as _supabase_mod  # noqa: F401  (registers the dotted path for patch())


def _tenant(**over):
    return {
        "id": "t1", "business_name": "Acme",
        "twilio_phone_number": "+14165550100",
        "twilio_subaccount_sid": "AC_sub", "twilio_auth_token": "tok",
        "vapi_phone_number_id": "vapi_pn_1",
        "subscription_status": "none",
        **over,
    }


@pytest.mark.asyncio
async def test_release_detaches_vapi_before_giving_the_number_back():
    """Order is load-bearing. Releasing Twilio first would leave Vapi routing to a
    number Twilio has already handed to someone else — real calls to the wrong
    business. Failing the other way round only costs us a month of rent."""
    calls = []

    async def _vapi_delete(pid, api_key=None):
        calls.append("vapi")
        return True

    async def _twilio_release(sid, token, number):
        calls.append("twilio")
        return True

    with patch("services.vapi.delete_phone_number", new=_vapi_delete), \
         patch("services.telephony.release_number", new=_twilio_release), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await provisioning.release_tenant_number(_tenant())

    assert res["released"] is True
    assert calls == ["vapi", "twilio"]
    # Cleared so a retry is a no-op rather than a second release attempt.
    wrote = upd.call_args.args[1]
    assert wrote["twilio_phone_number"] is None
    assert wrote["vapi_phone_number_id"] is None
    # Audit trail — stamped here so a manual admin release records the same as
    # the automated sweep.
    assert wrote["number_released_at"]


@pytest.mark.asyncio
async def test_a_failed_vapi_delete_stops_before_anything_is_given_away():
    with patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=False)), \
         patch("services.telephony.release_number", new=AsyncMock()) as twilio, \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await provisioning.release_tenant_number(_tenant())

    assert res["released"] is False and res["reason"] == "vapi_delete_failed"
    twilio.assert_not_called()   # nothing released — fully retryable
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_twilio_release_leaves_the_row_intact_for_a_retry():
    with patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=True)), \
         patch("services.telephony.release_number", new=AsyncMock(side_effect=RuntimeError("twilio down"))), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await provisioning.release_tenant_number(_tenant())

    assert res["released"] is False and res["reason"] == "twilio_release_failed"
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_a_number_missing_from_the_subaccount_does_not_clear_the_row():
    """THE regression this suite missed. release_number used to swallow every
    error and return None, so a release that did nothing looked identical to one
    that worked — and we cleared the row anyway, losing the only record of a
    number Twilio kept billing for."""
    with patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=True)), \
         patch("services.telephony.release_number", new=AsyncMock(return_value=False)), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await provisioning.release_tenant_number(_tenant())

    assert res["released"] is False and res["reason"] == "twilio_number_not_found"
    assert res["steps"]["twilio_released"] is False
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_missing_twilio_credentials_refuses_rather_than_guessing():
    """Without the subaccount creds the number cannot be released, and pretending
    otherwise would drop it from our records while Twilio kept billing."""
    with patch("services.vapi.delete_phone_number", new=AsyncMock(return_value=True)), \
         patch("services.telephony.release_number", new=AsyncMock()) as twilio:
        res = await provisioning.release_tenant_number(_tenant(twilio_auth_token=""))

    assert res["released"] is False and res["reason"] == "missing_twilio_credentials"
    twilio.assert_not_called()


@pytest.mark.asyncio
async def test_a_tenant_with_no_number_is_already_done():
    with patch("services.vapi.delete_phone_number", new=AsyncMock()) as v, \
         patch("services.telephony.release_number", new=AsyncMock()) as t:
        res = await provisioning.release_tenant_number(_tenant(twilio_phone_number=""))
    assert res["released"] is True and res["reason"] == "no_number_on_tenant"
    v.assert_not_called()
    t.assert_not_called()


@pytest.mark.asyncio
async def test_release_works_when_vapi_never_had_the_number():
    with patch("services.vapi.delete_phone_number", new=AsyncMock()) as v, \
         patch("services.telephony.release_number", new=AsyncMock()), \
         patch("db.supabase.update_tenant", new=AsyncMock()):
        res = await provisioning.release_tenant_number(_tenant(vapi_phone_number_id=""))
    assert res["released"] is True
    v.assert_not_called()


# ── Retention purge ordering ─────────────────────────────────────────────────

def _purge_client():
    client = MagicMock()
    q = MagicMock()
    q.delete.return_value = q
    q.eq.return_value = q
    q.execute.return_value = MagicMock(data=[])
    client.table.return_value = q
    return client


@pytest.mark.asyncio
async def test_purge_releases_the_number_before_dropping_the_row():
    """The subaccount SID, token and number all live on the tenant row and are the
    only way to release it. Dropping the row first left the number permanently
    unreleasable except by hand in the Twilio console, billing us forever."""
    order = []

    client = _purge_client()
    original_table = client.table

    def _table(name):
        if name == "tenants":
            order.append("drop_row")
        return original_table(name)
    client.table = _table

    async def _release(tenant):
        order.append("release")
        return {"released": True, "steps": {}, "reason": ""}

    with patch("db.supabase.get_client", return_value=client), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=_tenant())), \
         patch("services.provisioning.release_tenant_number", new=_release):
        res = await retention.delete_tenant_data("t1", drop_tenant=True)

    assert order.index("release") < order.index("drop_row")
    assert res["deleted"]["phone_number_released"] == 1


@pytest.mark.asyncio
async def test_purge_records_a_failed_release_instead_of_hiding_it():
    """The row still gets deleted — data-retention obligations don't pause for a
    Twilio outage — but the failure has to be visible or the number is lost."""
    with patch("db.supabase.get_client", return_value=_purge_client()), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=_tenant())), \
         patch("services.provisioning.release_tenant_number",
               new=AsyncMock(return_value={"released": False, "steps": {}, "reason": "twilio_release_failed"})):
        res = await retention.delete_tenant_data("t1", drop_tenant=True)

    assert res["errors"]["phone_number"] == "twilio_release_failed"
    assert res["deleted"]["tenant"] == 1


@pytest.mark.asyncio
async def test_data_only_delete_keeps_the_number():
    """drop_tenant=False wipes caller PII but keeps the account working, so the
    line must survive it."""
    with patch("db.supabase.get_client", return_value=_purge_client()), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=_tenant())), \
         patch("services.provisioning.release_tenant_number", new=AsyncMock()) as rel:
        await retention.delete_tenant_data("t1", drop_tenant=False)
    rel.assert_not_called()


# ── telephony.release_number itself ──────────────────────────────────────────
#
# These exist because the rest of this file mocks release_number, and the mock
# used to be MORE capable than the real thing: it could raise, which the real
# function never did — it swallowed everything and returned None. That mismatch
# is what let a silent no-op reach production. Pin the real contract here.

def _twilio_client(found: bool):
    client = MagicMock()
    number = MagicMock()
    client.incoming_phone_numbers.list.return_value = [number] if found else []
    return client, number


@pytest.mark.asyncio
async def test_release_number_deletes_and_reports_true():
    from services import telephony
    client, number = _twilio_client(found=True)
    with patch("services.telephony._sub_client", return_value=client):
        assert await telephony.release_number("AC_sub", "tok", "+14165550100") is True
    number.delete.assert_called_once()


@pytest.mark.asyncio
async def test_release_number_reports_false_when_the_number_is_elsewhere():
    """Each tenant has its own sub-account. A number that isn't on this one was
    never released, and saying otherwise leaves it billing us with no record."""
    from services import telephony
    client, number = _twilio_client(found=False)
    with patch("services.telephony._sub_client", return_value=client):
        assert await telephony.release_number("AC_sub", "tok", "+14165550100") is False
    number.delete.assert_not_called()


@pytest.mark.asyncio
async def test_release_number_propagates_twilio_errors():
    """It used to catch these and return None, so callers cleared the tenant row
    as though the release had succeeded."""
    from services import telephony
    with patch("services.telephony._sub_client", side_effect=RuntimeError("twilio down")):
        with pytest.raises(RuntimeError):
            await telephony.release_number("AC_sub", "tok", "+14165550100")
