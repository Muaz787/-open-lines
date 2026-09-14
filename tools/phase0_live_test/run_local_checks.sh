#!/usr/bin/env bash
# Local, NON-NETWORK verification only. Never calls Twilio or Vapi.
set -euo pipefail
cd "$(dirname "$0")"

echo "== compile (py_compile static check) =="
python3 -m py_compile phase0/*.py phase0/providers/*.py tests/*.py

echo "== unit tests (stdlib unittest, no network) =="
PYTHONPATH="$(pwd)" python3 -m unittest discover -s tests -v

echo "== validate-config (local, no calls) =="
PYTHONPATH="$(pwd)" python3 -m phase0.cli validate-config >/dev/null && echo "validate-config OK"

echo "== dry-run proves no mutation (provision without --apply) =="
PYTHONPATH="$(pwd)" python3 -m phase0.cli provision | tail -n 3

echo "== --apply fails closed without a valid denylist (expect exit 2) =="
NODL="$(mktemp -d)"; mkdir -p "$NODL/phase0-evidence"
set +e
PHASE0_DENYLIST_PEPPER=x PYTHONPATH="$(pwd)" python3 -m phase0.cli --base "$NODL" provision --apply >/dev/null 2>&1
rc=$?; set -e
[ "$rc" -eq 2 ] && echo "fail-closed OK (exit 2)" || { echo "EXPECTED exit 2, got $rc"; exit 1; }

echo "== limits labels ==" && PYTHONPATH="$(pwd)" python3 -m phase0.cli limits | head -1

echo "ALL LOCAL CHECKS PASSED"
