"""
Vapi provider (stdlib urllib, apply-gated). Every method returns a
PlannedOperation whose executor runs ONLY under apply.

Teardown capability status (documented; UNVERIFIED — confirm live when authorized):
  - create sub-org      : POST /org                                (documented: yes)
  - create assistant    : POST /assistant                         (documented: yes)
  - import number+bind  : POST /phone-number (assistantId)        (documented: yes)
  - read assistant      : GET  /assistant/{id}                    (documented: yes)
  - read phone-number   : GET  /phone-number/{id}                 (documented: yes)
  - read call           : GET  /call/{id}                         (documented: yes)
  - list active calls   : GET  /call                              (documented: yes)
  - disable transfer    : PATCH /assistant/{id} (tools=[])        (documented: yes)
  - end call            : POST /call/{id}/... control              (UNVERIFIED — may require control URL)
  - delete assistant    : DELETE /assistant/{id}                  (documented; VERIFY before relying)
  - delete phone-number : DELETE /phone-number/{id}               (documented; VERIFY before relying)
  - delete sub-org      : DELETE /org/{id}                        (UNVERIFIED — may need dashboard)
"""
from __future__ import annotations

from .base import BaseProvider, env
from ..plan import PlannedOperation

VAPI_API = "https://api.vapi.ai"


class CredentialScopeError(Exception):
    """Raised when a child-resource operation lacks the sub-org key. Fail closed —
    NEVER fall back to the parent key for sub-org-scoped resources."""


def vapi_for_manifest(manifest: dict) -> "VapiProvider":
    """Return a VapiProvider scoped to the run's sub-organization key. Every
    resource created inside the test sub-org MUST be accessed with this. Fails
    closed if the sub-org key is missing (never silently uses the parent key)."""
    key = (manifest or {}).get("suborg_api_key")
    if not key:
        raise CredentialScopeError("suborg_api_key missing from operational manifest — refusing "
                                   "to operate on sub-org resources with the parent key")
    return VapiProvider(explicit_key=key)


class VapiProvider(BaseProvider):
    ENCODING = "json"
    NAME = "vapi"

    def __init__(self, api_key_env: str = "VAPI_API_KEY", explicit_key: str | None = None):
        super().__init__(VAPI_API)
        self._key_env = api_key_env
        self._explicit_key = explicit_key  # e.g. a sub-org key discovered at apply time

    def _auth_header(self) -> dict:
        key = self._explicit_key or env(self._key_env)
        if not key:
            raise RuntimeError(f"{self._key_env} not set in environment")
        return {"Authorization": f"Bearer {key}"}

    # -- creation --
    def plan_create_suborg(self, name: str) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "create_suborg", "POST", "(new)", True, detail=f"name={name}",
            _run=lambda: self._http("POST", "/org", {"name": name}),
        )

    def plan_create_assistant(self, config: dict) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "create_assistant", "POST", "(new)", True,
            detail=f"name={config.get('name', '?')}",
            _run=lambda: self._http("POST", "/assistant", config),
        )

    def plan_import_number(self, body: dict) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "import_number_bind_assistant", "POST", "(new)", True,
            detail="binds assistantId to the temp number",
            _run=lambda: self._http("POST", "/phone-number", body),
        )

    # -- read-only --
    def plan_get_assistant(self, assistant_id: str) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "get_assistant", "GET", assistant_id, False,
            _run=lambda: self._http("GET", f"/assistant/{assistant_id}"),
        )

    def plan_get_phone_number(self, phone_id: str) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "get_phone_number", "GET", phone_id, False,
            _run=lambda: self._http("GET", f"/phone-number/{phone_id}"),
        )

    def plan_get_call(self, call_id: str) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "get_call", "GET", call_id, False,
            _run=lambda: self._http("GET", f"/call/{call_id}"),
        )

    def plan_list_calls(self) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "list_calls", "GET", "(org)", False,
            _run=lambda: self._http("GET", "/call", query={"limit": 20}),
        )

    def plan_list_assistants(self) -> PlannedOperation:
        """Parent-scope read used by live-preflight to verify parent credentials."""
        return PlannedOperation(
            "vapi", "list_assistants", "GET", "(org)", False,
            _run=lambda: self._http("GET", "/assistant", query={"limit": 1}),
        )

    # -- emergency stop / teardown --
    def plan_disable_transfer(self, assistant_id: str) -> PlannedOperation:
        # Removes tools so the assistant can no longer request a transfer.
        return PlannedOperation(
            "vapi", "disable_transfer", "PATCH", assistant_id, True,
            detail="model.tools=[] (no transfer-call)",
            _run=lambda: self._http("PATCH", f"/assistant/{assistant_id}",
                                    {"model": {"provider": "openai", "model": "gpt-4.1-mini", "tools": []}}),
        )

    def plan_bind_number(self, phone_id: str, assistant_id: str) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "bind_number_assistant", "PATCH", phone_id, True,
            detail="set assistantId to the selected mode's assistant",
            _run=lambda: self._http("PATCH", f"/phone-number/{phone_id}", {"assistantId": assistant_id}),
        )

    def plan_detach_number(self, phone_id: str) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "detach_number_assistant", "PATCH", phone_id, True,
            detail="unset assistantId (stop new inbound routing)",
            _run=lambda: self._http("PATCH", f"/phone-number/{phone_id}", {"assistantId": None}),
        )

    def plan_delete_assistant(self, assistant_id: str) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "delete_assistant", "DELETE", assistant_id, True,
            detail="documented; VERIFY before relying",
            _run=lambda: self._http("DELETE", f"/assistant/{assistant_id}"),
        )

    def plan_delete_phone_number(self, phone_id: str) -> PlannedOperation:
        return PlannedOperation(
            "vapi", "delete_phone_number", "DELETE", phone_id, True,
            _run=lambda: self._http("DELETE", f"/phone-number/{phone_id}"),
        )
