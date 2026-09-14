"""
Provisioning state machine (SID/resource-id chaining).

Contract (per step): run ONLY under apply; validate the provider response; persist
the new id into the restricted operational manifest and fsync BEFORE continuing;
feed it to the next step. On any failure: stop immediately, keep the partial
manifest (never auto-delete/overwrite), emit a sanitized partial-resource report,
and produce a cleanup plan covering exactly the resources created so far.

Number acquisition uses the correct Twilio workflow: SEARCH available local numbers
(voice-enabled, preferring address_requirements == "none") then PURCHASE the exact
selected number — never a blind AreaCode purchase.

M2 note: assistant-based warm transfer's `transferAssistant` is INLINE JSON in the
M2 assistant's transferCall tool — no separate transfer-assistant resource, so no
`transfer_assistant_id` in the manifest.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import config as CFG
from . import constants as C
from . import manifest as M
from .cleanup import build_teardown_plan
from .plan import OperationPlan
from .providers.twilio import TwilioProvider
from .providers.vapi import VapiProvider

STEP_ORDER = [
    "subaccount",      # subaccount_sid, subaccount_auth_token
    "suborg",          # suborg_id, suborg_api_key
    "assistant_m1",    # assistant_id_m1
    "assistant_m2",    # assistant_id_m2 (transferAssistant inline; no extra id)
    "number_search",   # number, number_address_requirements  (read-only)
    "number_purchase", # number_sid                            (mutation)
    "import_bind",     # vapi_phone_number_id, bound_assistant_id
]


class ProvisionError(Exception):
    pass


@dataclass
class ProvisionResult:
    ok: bool
    manifest: dict
    completed_steps: list[str] = field(default_factory=list)
    failed_step: str | None = None
    error: str | None = None
    cleanup: OperationPlan | None = None


def _need(res: dict, key: str, step: str) -> str:
    val = (res or {}).get(key)
    if not val:
        raise ProvisionError(f"step {step}: provider response missing '{key}'")
    return str(val)


def select_number(search_response: dict) -> tuple[str, str]:
    """Pick a voice-enabled number, preferring address_requirements == 'none'.
    Returns (e164, address_requirements). Raises if none suitable."""
    nums = (search_response or {}).get("available_phone_numbers") or []
    voice = [n for n in nums if ((n.get("capabilities") or {}).get("voice", True))]
    if not voice:
        raise ProvisionError("number_search: no voice-enabled numbers returned")
    preferred = [n for n in voice if (n.get("address_requirements") or "none") == "none"]
    chosen = (preferred or voice)[0]
    return _need(chosen, "phone_number", "number_search"), str(chosen.get("address_requirements") or "none")


def dry_run_plan(tunnel: str, secret: str, area_code: str, country: str = "CA") -> OperationPlan:
    tw, vp = TwilioProvider(), VapiProvider()
    p = OperationPlan()
    p.add(tw.plan_create_subaccount(f"OpenLines - {C.RESOURCE_PREFIX}"))
    p.add(vp.plan_create_suborg(f"{C.RESOURCE_PREFIX} — OpenLines"))
    p.add(vp.plan_create_assistant(CFG.dev_assistant_config(C.MODE_M1, tunnel, secret)))
    p.add(vp.plan_create_assistant(CFG.dev_assistant_config(C.MODE_M2, tunnel, secret)))
    p.add(tw.plan_search_local("(subaccount)", country, area_code))
    p.add(tw.plan_purchase_exact("(subaccount)", "(number from search)"))
    p.add(vp.plan_import_number({"note": "bind selected assistant to temp number"}))
    return p


def execute(base: str, *, tunnel: str, secret: str, area_code: str,
            selected_mode: str = C.MODE_M1, country: str = "CA",
            run_id: str = "") -> ProvisionResult:
    # Fail closed if a manifest already exists — NEVER overwrite it. Recovery is
    # via stop/teardown, then deliberate archival/deletion of the old manifest.
    if os.path.exists(os.path.join(base, C.EVIDENCE_DIR_NAME, C.OPERATIONAL_MANIFEST)):
        raise ProvisionError("operational manifest already exists — refusing to overwrite; "
                             "run stop/teardown and archive/delete it before a new run")
    ctx: dict = {"resource_prefix": C.RESOURCE_PREFIX, "selected_mode": selected_mode}
    if run_id:
        ctx["run_id"] = run_id
    M.write_operational(base, ctx)
    completed: list[str] = []
    tw = TwilioProvider()
    vp_parent = VapiProvider()

    def persist():
        M.write_operational(base, ctx)
        M.write_review(base, ctx)

    try:
        # 1) Twilio subaccount
        res = tw.plan_create_subaccount(f"OpenLines - {C.RESOURCE_PREFIX}")._run()
        ctx["subaccount_sid"] = _need(res, "sid", "subaccount")
        ctx["subaccount_auth_token"] = _need(res, "auth_token", "subaccount")
        completed.append("subaccount"); persist()

        # 2) Vapi sub-org
        res = vp_parent.plan_create_suborg(f"{C.RESOURCE_PREFIX} — OpenLines")._run()
        ctx["suborg_id"] = _need(res, "id", "suborg")
        ctx["suborg_api_key"] = str(res.get("apiKey") or res.get("privateKey") or res.get("key") or "")
        if not ctx["suborg_api_key"]:
            raise ProvisionError("step suborg: no api key in response")
        completed.append("suborg"); persist()

        vp = VapiProvider(explicit_key=ctx["suborg_api_key"])

        # 3) M1 assistant
        res = vp.plan_create_assistant(CFG.dev_assistant_config(C.MODE_M1, tunnel, secret))._run()
        ctx["assistant_id_m1"] = _need(res, "id", "assistant_m1")
        completed.append("assistant_m1"); persist()

        # 4) M2 assistant (transferAssistant inline — no separate resource)
        res = vp.plan_create_assistant(CFG.dev_assistant_config(C.MODE_M2, tunnel, secret))._run()
        ctx["assistant_id_m2"] = _need(res, "id", "assistant_m2")
        completed.append("assistant_m2"); persist()

        # 5) Search available local numbers (READ-ONLY) and choose one
        res = tw.plan_search_local(ctx["subaccount_sid"], country, area_code)._run()
        number, addr_req = select_number(res)
        ctx["number"] = number
        ctx["number_address_requirements"] = addr_req
        completed.append("number_search"); persist()

        # 6) Purchase the exact chosen number (MUTATION)
        res = tw.plan_purchase_exact(ctx["subaccount_sid"], ctx["number"])._run()
        ctx["number_sid"] = _need(res, "sid", "number_purchase")
        completed.append("number_purchase"); persist()

        # 7) Import + bind the selected assistant
        bound = ctx["assistant_id_m1"] if selected_mode == C.MODE_M1 else ctx["assistant_id_m2"]
        body = CFG.import_number_body(ctx["number"], ctx["subaccount_sid"], bound, tunnel, secret)
        body["twilioAuthToken"] = ctx["subaccount_auth_token"]
        res = vp.plan_import_number(body)._run()
        ctx["vapi_phone_number_id"] = _need(res, "id", "import_bind")
        ctx["bound_assistant_id"] = bound
        completed.append("import_bind"); persist()

        return ProvisionResult(ok=True, manifest=ctx, completed_steps=completed)

    except Exception as e:
        persist()  # keep partial manifest; NEVER auto-delete
        failed = STEP_ORDER[len(completed)] if len(completed) < len(STEP_ORDER) else "unknown"
        try:
            cleanup = build_teardown_plan(ctx)
        except Exception:
            cleanup = None   # e.g. vapi resources w/o sub-org key — surfaced, not hidden
        return ProvisionResult(
            ok=False, manifest=ctx, completed_steps=completed,
            failed_step=failed, error=type(e).__name__, cleanup=cleanup,
        )
