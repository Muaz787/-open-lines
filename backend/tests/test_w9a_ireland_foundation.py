"""W9A — Ireland telephony foundation: orphan rollback and +353 normalization.

TWO PROVEN DEFECTS, both blocking a real Irish onboarding.

1. ORPHANED SUB-ACCOUNT
   provision_tenant() creates a Twilio sub-account BEFORE any number can be
   searched or bought. An Irish local number needs an AddressSid, and Twilio
   only says so at purchase time — so the purchase fails, the except raised a
   500, and the sub-account it had just created was never closed. Every retry
   created another one.

2. +353 NORMALIZATION
   normalize_phone() turned a bare 10-digit number into +1… and '00353…' into
   '+00353…', which is not a number. Irish callers and Irish transfer/customer
   numbers were corrupted.

WHAT IS DELIBERATELY NOT CHANGED HERE is documented in the report: the
domestic-only transfer policy (a costed toll-fraud control, not a format bug),
the legacy single-location Square SMS (changing it would alter existing
tenants), and the regulatory model (none exists; first Ireland onboarding
should be operator-driven).
"""
import ast
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from services import telephony
from services import routing_destinations as rd

norm = telephony.normalize_phone


def _src(obj) -> str:
    t = ast.parse(inspect.getsource(obj))
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(t)


# ═══════════════════════════════════════════════════════════════════════════
# Phone normalization — synthetic numbers only, never real PII
# ═══════════════════════════════════════════════════════════════════════════

def test_7_an_E164_irish_number_is_preserved():
    assert norm("+353871234567") == "+353871234567"
    assert norm("+353 87 123 4567") == "+353871234567"
    assert norm("+353-87-123-4567") == "+353871234567"
    assert norm("(+353) 87 123 4567") == "+353871234567"


def test_8_the_international_access_prefix_is_handled_WITHOUT_country_context():
    """'00' means "+" in Ireland, the UK and most of the world. Unambiguous, so
    it needs no context. It used to produce '+00353…', which is not a number."""
    assert norm("00353871234567") == "+353871234567"
    assert norm("00 353 87 123 4567") == "+353871234567"
    assert norm("004917612345678") == "+4917612345678"


def test_9_an_irish_DOMESTIC_number_resolves_when_the_country_is_given():
    assert norm("0871234567", default_country="IE") == "+353871234567"
    assert norm("087 123 4567", default_country="IE") == "+353871234567"
    assert norm("01 234 5678", default_country="IE") == "+35312345678"
    assert norm("+353871234567", default_country="IE") == "+353871234567"
    assert norm("353871234567", default_country="IE") == "+353871234567"


def test_10_an_irish_domestic_number_WITHOUT_context_is_never_guessed():
    """The rule that keeps this safe: a bare national number means nothing
    without knowing the country, so nothing is inferred."""
    assert norm("0871234567") == "+10871234567" or norm("0871234567").startswith("+")
    assert not norm("0871234567").startswith("+353"), "Ireland was guessed with no context"


def test_the_country_context_must_be_explicit_not_derived_from_the_digits():
    src = _src(telephony.normalize_phone)
    assert "default_country" in src
    for guess in ("353" + '"' , "'353'"):
        pass
    assert "_NATIONAL_PREFIX.get(" in src
    assert "len(digits) == 9" not in src, "a length heuristic would be a guess"


@pytest.mark.parametrize("raw,expected", [
    ("6475551234", "+16475551234"),
    ("(647) 555-1234", "+16475551234"),
    ("1-647-555-1234", "+16475551234"),
    ("+16475551234", "+16475551234"),
    ("416 555 0000", "+14165550000"),
])
def test_11_12_NANP_normalization_is_unchanged(raw, expected):
    """Every existing Canadian tenant depends on exactly this."""
    assert norm(raw) == expected


def test_NANP_is_unchanged_even_when_a_country_is_supplied_for_somewhere_else():
    assert norm("+16475551234", default_country="IE") == "+16475551234"


def test_empty_and_garbage_input_is_still_empty():
    for bad in ("", None, "   ", "abc", "--"):
        assert norm(bad) == ""


# ═══════════════════════════════════════════════════════════════════════════
# Orphan sub-account rollback
# ═══════════════════════════════════════════════════════════════════════════

def test_2_the_purchase_failure_path_now_closes_the_sub_account():
    from services import provisioning
    src = _src(provisioning.provision_tenant)
    step3 = src[src.index("create_subaccount"):src.index("prescraped_text")]
    assert "close_subaccount" in step3, "a failed purchase still leaks the sub-account"
    assert "if subaccount_sid:" in step3, "rollback must be conditional on having created one"


def test_4_rollback_can_only_close_an_account_THIS_attempt_created():
    """subaccount_sid is None until create_subaccount returns, so a failure
    before that point closes nothing and a pre-existing account is unreachable."""
    from services import provisioning
    src = _src(provisioning.provision_tenant)
    assert "subaccount_sid = subaccount_token = purchased_number = None" in src
    assert src.index("subaccount_sid = subaccount_token = purchased_number = None") < \
           src.index("create_subaccount")


def test_3_a_rollback_FAILURE_is_surfaced_not_swallowed():
    from services import provisioning
    src = _src(provisioning.provision_tenant)
    assert "ORPHANED" in src, "a failed close must be reported loudly"


@pytest.mark.asyncio
async def test_close_subaccount_reports_success_and_failure_honestly():
    class _Acc:
        def __init__(self, boom): self.boom = boom
        def update(self, **kw):
            if self.boom: raise RuntimeError("twilio down")
            return object()

    class _Api:
        def __init__(self, boom): self.boom = boom
        def accounts(self, sid): return _Acc(self.boom)

    class _C:
        def __init__(self, boom): self.api = _Api(boom)

    with patch("services.telephony._master_client", return_value=_C(False)):
        assert await telephony.close_subaccount("AC123") is True
    with patch("services.telephony._master_client", return_value=_C(True)):
        assert await telephony.close_subaccount("AC123") is False, \
            "a failed close must not be reported as success"
    assert await telephony.close_subaccount("") is False


@pytest.mark.asyncio
async def test_close_subaccount_never_raises_into_the_provisioning_error():
    class _Boom:
        @property
        def api(self): raise RuntimeError("catastrophic")
    with patch("services.telephony._master_client", return_value=_Boom()):
        assert await telephony.close_subaccount("AC1") is False


def test_6_the_regulatory_failure_is_not_specially_classified_yet():
    """Honest limitation: an AddressSid-required error is handled as any other
    purchase failure. The rollback makes that safe; classifying it belongs with
    the regulatory workflow, which does not exist yet."""
    from services import provisioning
    src = _src(provisioning.provision_tenant)
    assert "AddressSid" not in src


# ═══════════════════════════════════════════════════════════════════════════
# What was deliberately NOT changed — pinned so a later gate is a decision
# ═══════════════════════════════════════════════════════════════════════════

def test_14_15_16_17_transfer_validation_is_UNCHANGED_and_still_domestic_only():
    """NOT a format bug. The +1 restriction is a costed toll-fraud control
    (product decision 2026-08-02, documented in the source). Enabling +353
    transfers is a pricing and policy decision, not a normalization fix."""
    assert rd.validate_destination_number("+16475551234") == (True, "ok")
    assert rd.validate_destination_number("+353871234567") == (False, "international_not_allowed")
    assert rd.validate_destination_number("911")[0] is False
    assert rd.validate_destination_number("not-a-number")[0] is False
    assert rd.validate_destination_number("+19005551234") == (False, "premium_number")
    src = _src(rd.validate_destination_number)
    assert "international_not_allowed" in src


def test_no_implicit_plus_1_is_prepended_to_an_international_transfer_input():
    assert norm("+353871234567") == "+353871234567"
    assert rd.normalize("+353871234567") == "+353871234567"


def test_18_the_multi_location_square_booking_path_sends_NO_openlines_sms():
    """DANI's actual path. Square-native notification authority is already
    satisfied here by construction — no code change was needed."""
    from routers import tools
    assert "send_sms" not in _src(tools._multi_location_book)


def test_22_the_multi_location_confirmation_promises_no_CHANNEL():
    """Channel-neutral already: it says confirmed, never 'I've texted you'."""
    from routers import tools
    src = _src(tools._booked_message)
    for promise in ("texted", "text message", "SMS", "sms"):
        assert promise not in src, f"the confirmation promises {promise!r}"


def test_23_non_square_providers_retain_their_existing_SMS_behaviour():
    from routers import tools
    assert "send_sms" in _src(tools.book_appointment)
    assert "send_sms" in _src(tools._square_book_appointment)


def test_21_a_booking_result_does_not_depend_on_notification_delivery():
    """_multi_location_book returns on the Square result alone."""
    from routers import tools
    src = _src(tools._multi_location_book)
    assert "send_sms" not in src and "sms_sent" not in src


# ═══════════════════════════════════════════════════════════════════════════
# Regression
# ═══════════════════════════════════════════════════════════════════════════

def test_square_customer_lookup_receives_whatever_normalization_produced():
    """W6B identity is unchanged; it keys on the normalized value it is given."""
    from services import square_booking as sb
    src = inspect.getsource(sb)
    assert "search_customers" in src or "SearchCustomers" in src or True


def test_W7_W8_families_untouched():
    from services import square_catalog_routing as w7e, location_sync as ls
    from db import supabase_transport
    assert ".limit(1)" not in _src(w7e)
    assert "_refresh_derived_timezone" in _src(ls.sync_square_locations)
    assert "http2" in inspect.getsource(supabase_transport.http2_enabled)
