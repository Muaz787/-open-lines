"""
Shared teardown/cleanup plan builder. Used by `cli teardown` AND the provisioning
state machine's failure path so a partially-created run always has a concrete
cleanup plan covering exactly the resources created.

Vapi child resources are torn down with the SUB-ORG key (`vapi_for_manifest`),
which fails closed if the key is missing — never a silent parent-key fallback.
Building a plan performs NO provider call.
"""
from __future__ import annotations

from .plan import OperationPlan
from .providers.twilio import TwilioProvider
from .providers.vapi import vapi_for_manifest


def _has_vapi_resources(manifest: dict) -> bool:
    return any(manifest.get(k) for k in ("assistant_id_m1", "assistant_id_m2", "vapi_phone_number_id"))


def build_teardown_plan(manifest: dict) -> OperationPlan:
    tw = TwilioProvider()
    p = OperationPlan()

    # Vapi teardown (sub-org scoped). vapi_for_manifest raises CredentialScopeError
    # if the sub-org key is missing, so teardown fails safely instead of using the
    # parent key on sub-org resources.
    if _has_vapi_resources(manifest):
        vp = vapi_for_manifest(manifest)
        if manifest.get("vapi_phone_number_id"):
            p.add(vp.plan_delete_phone_number(manifest["vapi_phone_number_id"]))
        for k in ("assistant_id_m1", "assistant_id_m2"):
            if manifest.get(k):
                p.add(vp.plan_delete_assistant(manifest[k]))

    # Twilio teardown (master creds acting on the subaccount).
    if manifest.get("subaccount_sid") and manifest.get("number_sid"):
        p.add(tw.plan_release_number(manifest["subaccount_sid"], manifest["number_sid"]))
    if manifest.get("subaccount_sid"):
        p.add(tw.plan_suspend_subaccount(manifest["subaccount_sid"]))  # NOT close (manual/irreversible)
    return p
