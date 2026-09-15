"""
Phase 0 harness CLI.

Every mutating subcommand:
  * default (no flag) and --dry-run make NO external change and NO network call,
  * --apply is required to mutate,
  * --apply loads the MANDATORY production denylist and FAILS CLOSED if it is
    missing/empty/unreadable/malformed or the pepper is unset,
  * --apply refuses if the tunnel/webhook host matches a production host,
  * an operation plan is printed BEFORE anything runs,
  * the manifest allow-list + denylist clear every target first,
  * partial failures stop and report progress.

  python -m phase0.cli <command> [--apply] [--base DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import constants as C
from . import config as CFG
from . import cost as COST
from . import denylist as DL
from . import lifecycle as LC
from . import manifest as M
from . import modeswitch as MS
from . import preflight as PF
from . import provision as PROV
from . import receipt as RCPT
from .cleanup import build_teardown_plan
from .logging_setup import get_logger
from .plan import OperationPlan
from .providers.twilio import TwilioProvider
from .providers.vapi import CredentialScopeError, VapiProvider, vapi_for_manifest
from .safety import Guard, SafetyError

log = get_logger("phase0.cli")


def _load_manifest(base: str) -> dict | None:
    try:
        return M.read_operational(base)
    except FileNotFoundError:
        print("No operational manifest found — run `provision --apply` first "
              "(nothing to act on).", file=sys.stderr)
        return None


def _guard(base: str) -> Guard:
    try:
        data = M.read_operational(base)
    except FileNotFoundError:
        data = {}
    return Guard.from_manifest(data)


def _preflight_apply(base: str, *, tunnel: str | None = None) -> DL.Denylist:
    """MANDATORY on every --apply. Fail closed if the denylist is unusable, and
    refuse a production tunnel/webhook host."""
    dl = DL.load_or_fail(DL.default_path(base))   # raises DenylistError -> abort
    if tunnel:
        dl.assert_host_allowed(tunnel)
    return dl


def _check_targets(planp: OperationPlan, dl: DL.Denylist, guard: Guard, *, allow_create: bool) -> None:
    planp.guard(guard, allow_create=allow_create)     # manifest allow-list
    for op in planp.operations:                        # denylist on every target
        if op.target not in ("(new)", "(org)", "(subaccount)"):
            dl.assert_target_allowed(op.target)


def _run_plan(planp: OperationPlan, *, apply: bool, base: str, allow_create: bool = False,
              tunnel: str | None = None) -> int:
    print(planp.render())
    if not apply:
        print("\nDRY RUN — no changes made, no network calls. Re-run with --apply to execute.")
        return 0
    try:
        dl = _preflight_apply(base, tunnel=tunnel)
        _check_targets(planp, dl, _guard(base), allow_create=allow_create)
    except (DL.DenylistError, SafetyError) as e:
        print(f"\nREFUSED (fail closed): {e}", file=sys.stderr)
        return 2
    results = planp.execute(apply=True)
    print("\nRESULTS:")
    for r in results:
        print("  " + json.dumps(M.redacted_view(r)))
    if any(r.get("_partial_failure") for r in results):
        print("\nPARTIAL FAILURE — see README recovery steps.", file=sys.stderr)
        return 3
    return 0


# --- commands ---------------------------------------------------------------

def cmd_validate_config(args) -> int:
    tunnel = "https://TUNNEL.example/hook"
    payloads = {
        "M1_standard_warm_summary": CFG.dev_assistant_config(C.MODE_M1, tunnel, "SECRET"),
        "M2_assistant_based_warm":  CFG.dev_assistant_config(C.MODE_M2, tunnel, "SECRET"),
    }
    text = json.dumps(payloads, indent=2)
    for bad in ("DOC?", "PLACEHOLDER", "TODO"):
        if bad in text:
            print(f"INVALID: placeholder token {bad}", file=sys.stderr)
            return 1
    m1 = payloads["M1_standard_warm_summary"]["model"]["tools"][0]["transferPlan"]
    m2 = payloads["M2_assistant_based_warm"]["model"]["tools"][0]["transferPlan"]
    assert m1["mode"] == C.MODE_WARM_SAY_SUMMARY and "summaryPlan" in m1
    assert m2["mode"] == C.MODE_WARM_EXPERIMENTAL and "transferAssistant" in m2
    print(text)
    print("\nOK: M1 (warm-transfer-say-summary) and M2 (warm-transfer-experimental + "
          "inline transferAssistant) are distinct and placeholder-free. M2 does NOT "
          "create a separate transfer-assistant resource.")
    return 0


def cmd_seed_denylist(args) -> int:
    """Seed the mandatory production denylist from an operator-local file of raw
    production identifiers (gitignored). Raw values are never printed or stored."""
    ids, hosts = [], []
    if args.ids_file and os.path.exists(args.ids_file):
        with open(args.ids_file, encoding="utf-8") as fh:
            for ln in fh:
                s = ln.strip()
                if not s or s.startswith("#"):
                    continue
                (hosts if s.startswith("host:") else ids).append(s.replace("host:", "", 1))
    if not ids and not hosts:
        print("No identifiers provided (--ids-file). Nothing seeded.", file=sys.stderr)
        return 1
    try:
        summary = DL.seed(DL.default_path(args.base), ids=ids, hosts=hosts)
    except DL.DenylistError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"Seeded denylist: {summary} (hashes only; no raw values stored).")
    return 0


def _manifest_path(base: str) -> str:
    return os.path.join(base, C.EVIDENCE_DIR_NAME, C.OPERATIONAL_MANIFEST)


def cmd_preflight(args) -> int:
    """Local only: validate apply-time preconditions from the current environment
    without any network call. Prints problems (none == ready)."""
    base = args.base
    manifest_exists = os.path.exists(_manifest_path(base))
    problems = PF.validate(dict(os.environ), base, manifest_exists=manifest_exists)
    if problems:
        print("PREFLIGHT: NOT READY")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("PREFLIGHT: ready (local apply-time preconditions satisfied).")
    return 0


def build_live_preflight_plan(base: str) -> OperationPlan:
    """Read-only provider checks for live-preflight. GET-only, no mutation."""
    data = {}
    try:
        data = M.read_operational(base)
    except FileNotFoundError:
        pass
    tw, vp = TwilioProvider(), VapiProvider()   # PARENT creds (pre-provision)
    p = OperationPlan()
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "(master)")
    p.add(tw.plan_get_account(sid))             # Twilio master read
    p.add(vp.plan_list_assistants())            # Vapi parent read
    return p


def cmd_preflight_live(args) -> int:
    """Separately-authorized, READ-ONLY network preflight. GET only — never POST/
    PATCH/DELETE. Verifies capture health + run-id match, Twilio master read, Vapi
    parent read, and spend-controls ack; writes a sanitized readiness receipt
    (booleans only, no creds/payloads). Fails unless every check passes."""
    import urllib.request
    base = args.base
    run_id = os.environ.get("PHASE0_RUN_ID", "")
    plan = build_live_preflight_plan(base)
    print("LIVE PREFLIGHT (read-only, GET only):")
    print(plan.render())
    print("  + GET capture /healthz (verify run_id_hash matches PHASE0_RUN_ID)")
    if not args.apply:
        print("\nDRY RUN — pass --apply to perform the read-only network checks.")
        return 0

    # Production-host protection BEFORE contacting anything: load the mandatory
    # denylist (fail closed) and refuse if the capture host is a production host.
    # On refusal we return immediately — the host is never contacted.
    tunnel = os.environ.get("PHASE0_SERVER_URL", "")
    try:
        dl = DL.load_or_fail(DL.default_path(base))
        dl.assert_host_allowed(tunnel)
    except DL.DenylistError as e:
        print(f"\nREFUSED (fail closed, no host contacted): {e}", file=sys.stderr)
        return 2

    checks: dict = {}
    # capture health + run-id binding
    base_url = tunnel.rsplit(C.WEBHOOK_PATH_PREFIX, 1)[0]
    try:
        with urllib.request.urlopen(base_url + C.HEALTH_PATH, timeout=10) as r:  # noqa: S310
            body = json.loads(r.read().decode())
        from .capture import run_id_hash
        checks["capture_health"] = (r.status == 200)
        checks["run_id_match"] = (body.get("run_id_hash") == run_id_hash(run_id))
        checks["capture_mode_match"] = (body.get("mode") == os.environ.get("PHASE0_MODE"))
    except Exception as e:
        print(f"capture health FAILED: {type(e).__name__}", file=sys.stderr)
        checks["capture_health"] = checks["run_id_match"] = False
    # provider credential reads (GET only)
    for op in plan.operations:
        try:
            op._run()
            checks[f"{op.provider}_read"] = True
        except Exception as e:
            print(f"{op.provider} read FAILED: {type(e).__name__}", file=sys.stderr)
            checks[f"{op.provider}_read"] = False
    checks["spend_controls_ack"] = (os.environ.get("PHASE0_SPEND_CONTROLS_ACK", "").lower() in ("yes", "true", "1"))

    path = RCPT.write(base, run_id, checks)
    ok = all(checks.values())
    print("\nReadiness receipt:", json.dumps({"run_id": run_id, "ok": ok, "checks": checks}))
    print("written:", path if ok else "(receipt records FAILED checks)")
    return 0 if ok else 1


def cmd_provision(args) -> int:
    base = args.base
    env = os.environ
    tunnel = env.get("PHASE0_SERVER_URL", "https://TUNNEL.example/hook")
    secret = env.get("VAPI_SERVER_SECRET", "")
    area = env.get("PHASE0_AREA_CODE", "416")
    country = env.get("PHASE0_COUNTRY", "CA")
    mode = env.get("PHASE0_MODE", C.MODE_M1)
    run_id = env.get("PHASE0_RUN_ID", "")
    print(PROV.dry_run_plan(tunnel, secret, area, country).render())
    if not args.apply:
        print("\nDRY RUN — no changes made, no network calls. Re-run with --apply to execute.")
        return 0
    # 0) Existing manifest => ALWAYS fail closed (no --resume in Phase 0).
    if os.path.exists(_manifest_path(base)):
        print("\nREFUSED (fail closed): an operational manifest already exists. Run "
              "stop/teardown, verify cleanup, then archive/delete it before a new run.",
              file=sys.stderr)
        return 2
    # 1) Local preconditions BEFORE any provider mutation.
    problems = PF.validate(dict(env), base, manifest_exists=False)
    if problems:
        print("\nREFUSED — preflight failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    # 2) Provider readiness receipt (from a prior read-only preflight-live).
    rproblems = RCPT.validate(base, run_id)
    if rproblems:
        print("\nREFUSED — live-preflight receipt invalid:", file=sys.stderr)
        for p in rproblems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    # 3) Mandatory denylist + production-host check.
    try:
        _preflight_apply(base, tunnel=tunnel)
    except DL.DenylistError as e:
        print(f"\nREFUSED (fail closed): {e}", file=sys.stderr)
        return 2
    result = PROV.execute(base, tunnel=tunnel, secret=secret, area_code=area,
                          selected_mode=mode, country=country, run_id=run_id)
    print("\nCREATED (sanitized):")
    print("  " + json.dumps(M.redacted_view(result.manifest)))
    if result.ok:
        print(f"\nProvision complete. Steps: {result.completed_steps}")
        return 0
    print(f"\nPROVISION FAILED at step '{result.failed_step}' ({result.error}). "
          f"Completed: {result.completed_steps}", file=sys.stderr)
    print("Partial manifest PRESERVED (not deleted). Cleanup plan for created resources:")
    print(result.cleanup.render() if result.cleanup else "  (nothing to clean up)")
    return 3


def cmd_select_mode(args) -> int:
    """Bind the temp number to the selected mode's assistant, read back, verify."""
    base = args.base
    data = _load_manifest(base)
    if data is None:
        return 0
    selected = C.MODE_M1 if args.mode == "M1" else C.MODE_M2
    assistant_id = data.get("assistant_id_m1" if selected == C.MODE_M1 else "assistant_id_m2")
    phone_id = data.get("vapi_phone_number_id")
    if not assistant_id or not phone_id:
        print("Manifest missing assistant/phone id — provision first.", file=sys.stderr)
        return 1
    try:
        vp = vapi_for_manifest(data)   # sub-org scoped; fails closed if key missing
    except CredentialScopeError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    p = OperationPlan()
    p.add(vp.plan_bind_number(phone_id, assistant_id))
    print(p.render())
    if not args.apply:
        print(f"\nDRY RUN — would bind {args.mode} (expected mode "
              f"{MS.expected_mode(selected)}); then read back and verify. No changes made.")
        return 0
    try:
        dl = _preflight_apply(base)
        _check_targets(p, dl, _guard(base), allow_create=False)
    except (DL.DenylistError, SafetyError) as e:
        print(f"\nREFUSED (fail closed): {e}", file=sys.stderr)
        return 2
    p.execute(apply=True)
    # Read back + verify.
    phone_rb = vp.plan_get_phone_number(phone_id)._run()
    asst_rb = vp.plan_get_assistant(assistant_id)._run()
    ready, reasons = MS.verify_ready(selected, assistant_id, phone_rb, asst_rb)
    if not ready:
        print("NOT READY — requested vs stored differ:", file=sys.stderr)
        for r in reasons:
            print(f"  - {r}", file=sys.stderr)
        return 1
    data["selected_mode"] = selected
    data["bound_assistant_id"] = assistant_id
    data["mode_verified"] = True
    M.write_operational(base, data)
    M.write_review(base, data)
    print(f"READY: mode {args.mode} bound + verified (mode={MS.expected_mode(selected)}).")
    return 0


def cmd_verify(args) -> int:
    base = args.base
    data = _load_manifest(base)
    if data is None:
        return 0
    try:
        vp = vapi_for_manifest(data)   # sub-org scoped
    except CredentialScopeError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    p = OperationPlan()
    if data.get("vapi_phone_number_id"):
        p.add(vp.plan_get_phone_number(data["vapi_phone_number_id"]))
    if data.get("bound_assistant_id") or data.get("assistant_id_m1"):
        p.add(vp.plan_get_assistant(data.get("bound_assistant_id") or data["assistant_id_m1"]))
    print(p.render())
    if not args.apply:
        print("\nREAD-ONLY DRY RUN — pass --apply to query Vapi (authorized). FAIL if the "
              "number has no bound assistantId or serverMessages lack transfer-destination-request.")
        return 0
    try:
        _preflight_apply(base)
    except DL.DenylistError as e:
        print(f"\nREFUSED (fail closed): {e}", file=sys.stderr)
        return 2
    ok = True
    for r in p.execute(apply=True):
        res = r.get("result", {})
        if r.get("action") == "get_phone_number" and not res.get("assistantId"):
            print("FAIL: temp number has no bound assistantId.", file=sys.stderr); ok = False
        if r.get("action") == "get_assistant" and "transfer-destination-request" not in res.get("serverMessages", []):
            print("FAIL: assistant serverMessages missing transfer-destination-request.", file=sys.stderr); ok = False
    return 0 if ok else 1


def cmd_inspect(args) -> int:
    base = args.base
    data = _load_manifest(base)
    if data is None:
        return 0
    tw = TwilioProvider()
    try:
        vp = vapi_for_manifest(data)   # sub-org scoped (calls live in the sub-org)
    except CredentialScopeError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    p = OperationPlan()
    if args.vapi_call_id:
        p.add(vp.plan_get_call(args.vapi_call_id))
    if data.get("subaccount_sid"):
        p.add(tw.plan_list_calls(data["subaccount_sid"]))
    print(p.render())
    if not args.apply:
        print("\nREAD-ONLY DRY RUN — pass --apply to query providers (authorized).")
        return 0
    try:
        _preflight_apply(base)
    except DL.DenylistError as e:
        print(f"\nREFUSED (fail closed): {e}", file=sys.stderr)
        return 2
    from .sanitize import sanitize_mapping
    for r in p.execute(apply=True):
        print(json.dumps(sanitize_mapping(r.get("result", {})))[:2000])
    return 0


def cmd_cost(args) -> int:
    with open(args.legs, "r", encoding="utf-8") as fh:
        legs = json.load(fh)
    print(json.dumps(COST.summarize(legs), indent=2))
    return 0


def cmd_limits(args) -> int:
    print("PHASE 0 LIMITS — enforcement labels:")
    print(f"  max_call_seconds = {C.MAX_CALL_SECONDS}   [PROVIDER-ENFORCED per call via assistant.maxDurationSeconds]")
    print(f"  max_calls        = {C.MAX_CALLS}          [HARNESS-OBSERVED (best-effort) + OPERATOR-ENFORCED] "
          "— the capture service only sees calls that reach the assistant "
          "(transfer/end-of-call events); calls failing before Vapi are NOT counted, "
          "so this count is NOT guaranteed complete.")
    print(f"  budget_threshold = ${C.BUDGET_THRESHOLD_USD:.0f}      [OPERATOR-ENFORCED] "
          "— NOT a software cap. Set provider-side: Twilio usage trigger, restricted "
          "subaccount balance, Vapi spending limit.")
    print("  destination class = domestic allow-list only [HARNESS-ENFORCED] "
          "(rejects emergency/premium/international/short codes).")
    return 0


def cmd_stop(args) -> int:
    base = args.base
    data = _load_manifest(base)
    if data is None:
        return 0
    tw = TwilioProvider()
    try:
        vp = vapi_for_manifest(data)   # sub-org scoped detach/disable
    except CredentialScopeError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    p = OperationPlan()
    if data.get("vapi_phone_number_id"):
        p.add(vp.plan_detach_number(data["vapi_phone_number_id"]))     # stop new inbound
    for k in ("assistant_id_m1", "assistant_id_m2"):
        if data.get(k):
            p.add(vp.plan_disable_transfer(data[k]))                   # remove transfer tool
    p.add(vp.plan_list_calls())                                        # identify active (sub-org)
    if data.get("subaccount_sid"):
        p.add(tw.plan_list_calls(data["subaccount_sid"]))
    print("EMERGENCY STOP — FIRST disable carrier forwarding on the business line "
          "manually (the tunnel is NOT the kill switch). THEN:")
    rc = _run_plan(p, apply=args.apply, base=base)
    if args.apply and rc == 0:
        data["stopped"] = True
        M.write_operational(base, data); M.write_review(base, data)
    return rc


def cmd_teardown(args) -> int:
    base = args.base
    data = _load_manifest(base)
    if data is None:
        return 0
    try:
        p = build_teardown_plan(data)   # raises if vapi resources exist w/o sub-org key
    except CredentialScopeError as e:
        print(f"REFUSED (fail safe, no parent-key fallback): {e}", file=sys.stderr)
        return 2
    if args.apply:
        data["teardown_attempted"] = True
        M.write_operational(base, data); M.write_review(base, data)
    rc = _run_plan(p, apply=args.apply, base=base)
    if args.apply and rc == 0:
        print("\nTeardown executed. Run `verify --apply` to confirm resources are gone; "
              "mark teardown_verified + delete the operational manifest ONLY after that.")
    return rc


def cmd_state(args) -> int:
    """Report the computed lifecycle readiness state. Local, no network."""
    base = args.base
    try:
        data = M.read_operational(base)
    except FileNotFoundError:
        data = {}
    local_ready = not PF.validate(dict(os.environ), base, manifest_exists=bool(data))
    receipt_ok = not RCPT.validate(base, os.environ.get("PHASE0_RUN_ID", ""))
    mode = data.get("selected_mode", os.environ.get("PHASE0_MODE", ""))
    from .capture import mode_consistent
    state = LC.compute_state(manifest=data, receipt_ok=receipt_ok,
                             local_ready=local_ready, mode_consistent=mode_consistent(data, mode))
    print(f"LIFECYCLE STATE: {state}")
    print(LC.guidance(state))
    return 0


def cmd_verify_teardown(args) -> int:
    rows = [
        ("release Twilio number", "DELETE .../IncomingPhoneNumbers/{sid}.json", "API: documented",
         "Console: Phone Numbers > Manage > Active numbers > release", "re-list numbers; must be absent"),
        ("suspend subaccount", "POST .../Accounts/{sid}.json Status=suspended", "API: documented (REVERSIBLE)",
         "Console: Account > Subaccounts > Suspend", "GET account; status=suspended"),
        ("close subaccount", "POST .../Accounts/{sid}.json Status=closed", "API: documented (IRREVERSIBLE — not automated)",
         "Console: Account > Subaccounts > Close (manual, permanent)", "GET account; status=closed"),
        ("delete/disable Vapi assistant", "DELETE /assistant/{id}", "API: documented — VERIFY before relying",
         "Dashboard: Assistants > delete", "GET assistant; 404/absent"),
        ("delete/detach Vapi number", "DELETE /phone-number/{id}  OR  PATCH assistantId=null", "API: documented",
         "Dashboard: Phone Numbers > delete/edit", "GET phone-number; 404 or assistantId null"),
        ("delete/disable Vapi sub-org", "DELETE /org/{id}", "UNVERIFIED — may NOT be API-available",
         "Dashboard: Org switcher > delete org (manual)", "list orgs; sub-org absent"),
        ("list + end active calls", "GET /call ; POST call control", "list documented; end UNVERIFIED (control URL)",
         "Dashboard: Calls > end; Twilio Console: Calls > complete", "GET calls; none in-progress"),
    ]
    print("TEARDOWN CAPABILITY MATRIX (no provider calls made):")
    for name, api, avail, manual, verify in rows:
        print(f"  • {name}")
        print(f"      api    : {api}")
        print(f"      status : {avail}")
        print(f"      manual : {manual}")
        print(f"      verify : {verify}")
    print("\nNOTE: suspend != close. Suspend is reversible and does NOT delete the "
          "subaccount; closing is permanent and is left as a MANUAL console step.")
    print("Incomplete-cleanup detection: after teardown --apply run `verify --apply`; "
          "any resource still present => cleanup incomplete => do NOT delete the "
          "operational manifest.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="phase0", description="Phase 0 live-test harness (isolated).")
    ap.add_argument("--base", default=".", help="working dir holding phase0-evidence/")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, mutating=True):
        sp = sub.add_parser(name)
        sp.set_defaults(func=fn)
        if mutating:
            g = sp.add_mutually_exclusive_group()
            g.add_argument("--apply", action="store_true", help="perform mutations")
            g.add_argument("--dry-run", action="store_true", help="explicit no-op (default)")
        return sp

    add("provision", cmd_provision)
    sm = add("select-mode", cmd_select_mode); sm.add_argument("--mode", choices=["M1", "M2"], required=True)
    add("verify", cmd_verify)
    add("inspect", cmd_inspect).add_argument("--vapi-call-id", default="")
    c = add("cost", cmd_cost, mutating=False); c.add_argument("--legs", required=True)
    add("stop", cmd_stop)
    add("teardown", cmd_teardown)
    sd = add("seed-denylist", cmd_seed_denylist, mutating=False); sd.add_argument("--ids-file", default="")
    add("preflight", cmd_preflight, mutating=False)
    add("preflight-live", cmd_preflight_live)
    add("state", cmd_state, mutating=False)
    add("validate-config", cmd_validate_config, mutating=False)
    add("verify-teardown", cmd_verify_teardown, mutating=False)
    add("limits", cmd_limits, mutating=False)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "dry_run", False):
        args.apply = False
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
