"""
Twilio provider — v2010 endpoints, form-encoded bodies, JSON responses.

Number acquisition follows the correct Twilio workflow (verified 2026-08-02 against
twilio.com/docs/phone-numbers/api/availablephonenumberlocal-resource):
  1. GET  AvailablePhoneNumbers/{CC}/Local.json?AreaCode=..&VoiceEnabled=true   (search)
  2. select a returned number (prefer address_requirements == "none")
  3. POST IncomingPhoneNumbers.json  (form: PhoneNumber=<exact>)                (purchase)

CA caveat: some Canadian numbers carry an `address_requirements` other than "none"
and need a Twilio Address / regulatory bundle before purchase. The harness prefers
"none" and surfaces the requirement rather than silently failing.

Teardown capability (documented; verify live):
  release number    DELETE IncomingPhoneNumbers/{sid}.json
  suspend account   POST Accounts/{sid}.json Status=suspended   (reversible)
  close account     POST Accounts/{sid}.json Status=closed      (IRREVERSIBLE — manual)
  list calls        GET  Calls.json
  end call          POST Calls/{sid}.json Status=completed
"""
from __future__ import annotations

import base64

from .base import BaseProvider, env
from ..plan import PlannedOperation

TWILIO_API = "https://api.twilio.com"


class TwilioProvider(BaseProvider):
    ENCODING = "form"
    NAME = "twilio"

    def __init__(self):
        super().__init__(TWILIO_API)

    def _auth_header(self) -> dict:
        sid = env("TWILIO_ACCOUNT_SID")
        tok = env("TWILIO_AUTH_TOKEN")
        if not sid or not tok:
            raise RuntimeError("TWILIO master credentials not set in environment")
        raw = f"{sid}:{tok}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}

    # -- creation --
    def plan_create_subaccount(self, friendly_name: str) -> PlannedOperation:
        return PlannedOperation(
            "twilio", "create_subaccount", "POST", "(new)", True,
            detail=f"friendly_name={friendly_name}",
            _run=lambda: self._http("POST", "/2010-04-01/Accounts.json",
                                    body={"FriendlyName": friendly_name}),
        )

    def plan_search_local(self, subaccount_sid: str, country: str, area_code: str) -> PlannedOperation:
        return PlannedOperation(
            "twilio", "search_local_numbers", "GET", subaccount_sid, False,
            detail=f"search {country} area {area_code}, voice-enabled",
            _run=lambda: self._http(
                "GET",
                f"/2010-04-01/Accounts/{subaccount_sid}/AvailablePhoneNumbers/{country}/Local.json",
                query={"AreaCode": area_code, "VoiceEnabled": "true"}),
        )

    def plan_purchase_exact(self, subaccount_sid: str, e164: str) -> PlannedOperation:
        return PlannedOperation(
            "twilio", "purchase_number", "POST", "(new)", True,
            detail="purchase the exact number returned by search",
            _run=lambda: self._http(
                "POST", f"/2010-04-01/Accounts/{subaccount_sid}/IncomingPhoneNumbers.json",
                body={"PhoneNumber": e164}),
        )

    # -- read-only --
    def plan_get_account(self, account_sid: str) -> PlannedOperation:
        """Read-only account fetch used by live-preflight to verify master creds."""
        return PlannedOperation(
            "twilio", "get_account", "GET", account_sid, False,
            _run=lambda: self._http("GET", f"/2010-04-01/Accounts/{account_sid}.json"),
        )

    def plan_list_calls(self, subaccount_sid: str) -> PlannedOperation:
        return PlannedOperation(
            "twilio", "list_calls", "GET", subaccount_sid, False,
            detail="read legs: CallSid, ParentCallSid, direction, status, duration, price",
            _run=lambda: self._http(
                "GET", f"/2010-04-01/Accounts/{subaccount_sid}/Calls.json",
                query={"PageSize": 50}),
        )

    # -- emergency stop / teardown --
    def plan_end_call(self, subaccount_sid: str, call_sid: str) -> PlannedOperation:
        return PlannedOperation(
            "twilio", "end_call", "POST", call_sid, True, detail="Status=completed",
            _run=lambda: self._http(
                "POST", f"/2010-04-01/Accounts/{subaccount_sid}/Calls/{call_sid}.json",
                body={"Status": "completed"}),
        )

    def plan_release_number(self, subaccount_sid: str, number_sid: str) -> PlannedOperation:
        return PlannedOperation(
            "twilio", "release_number", "DELETE", number_sid, True,
            _run=lambda: self._http(
                "DELETE",
                f"/2010-04-01/Accounts/{subaccount_sid}/IncomingPhoneNumbers/{number_sid}.json"),
        )

    def plan_suspend_subaccount(self, subaccount_sid: str) -> PlannedOperation:
        return PlannedOperation(
            "twilio", "suspend_subaccount", "POST", subaccount_sid, True,
            detail="Status=suspended (reversible)",
            _run=lambda: self._http(
                "POST", f"/2010-04-01/Accounts/{subaccount_sid}.json",
                body={"Status": "suspended"}),
        )

    def plan_close_subaccount(self, subaccount_sid: str) -> PlannedOperation:
        return PlannedOperation(
            "twilio", "close_subaccount", "POST", subaccount_sid, True,
            detail="Status=closed (IRREVERSIBLE — see README)",
            _run=lambda: self._http(
                "POST", f"/2010-04-01/Accounts/{subaccount_sid}.json",
                body={"Status": "closed"}),
        )
