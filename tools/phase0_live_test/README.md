# Phase 0 Live-Test Harness (isolated) — Operator Runbook

**Status: prepared for review. NOTHING here has been run against Twilio or Vapi.**
No number purchased, no call placed, no forwarding enabled, no production config
changed. Every mutating command is a no-op until an authorized operator adds
`--apply`.

This harness validates **call transfers and carrier-forwarded overflow** on an
isolated dev tenant. It does **not** touch the public OpenLines number and does
**not** use OpenLines' production assistant-resolution logic.

---

## 0. Guardrails (built in)

- **No mutation without `--apply`.** Default and `--dry-run` print an operation
  plan and make zero network calls. Proven by `tests/test_dry_run_no_mutation.py`.
- **Production guard.** A mutating op may only target a resource id present in the
  operational manifest this run created (allow-list), plus an optional hashed
  deny-list. Production ids are never in the manifest, so they can't be targeted.
- **Number policy.** Destinations must be domestic (+1 NANP), allow-listed, and
  are rejected if emergency / premium (900,976) / short-code / international.
- **Local limits.** Max 20 calls; max 5 min/call (set as `maxDurationSeconds`,
  provider-enforced per call).
- **Sanitized evidence only.** The capture service persists an allow-list of
  fields; transcripts, recordings, caller names, full numbers, headers, and auth
  values are never written. Numbers are masked to last-4.

## 1. Inbound design (explicit)

The temp number is created in Vapi with the **dev assistant bound directly**
(`assistantId` on the phone-number import). Vapi answers with a static assistant —
**no `assistant-request` round-trip** — so the test exercises transfers, not
routing. The assistant's own `server` + `serverMessages` still deliver
`transfer-destination-request` (dynamic destination) and `end-of-call-report`
(outcome) to the capture service. **`verify` FAILS if the number has no bound
`assistantId` or the assistant's `serverMessages` lack `transfer-destination-request`.**

## 2. Transfer modes under test (distinct — not conflated)

Validated against the current Vapi API reference:
- **M1 — standard warm transfer with summary:** `transferPlan.mode =
  "warm-transfer-say-summary"` + `summaryPlan`. Vapi speaks a generated summary to
  the operator. No transfer assistant.
- **M2 — assistant-based warm transfer:** `transferPlan.mode =
  "warm-transfer-experimental"` + a `transferAssistant`, which exposes Vapi's
  built-in `transferSuccessful` / `transferCancel` (the caller-recovery path).
  *(The experimental mode IS the assistant-based mechanism; there is no separate
  "M3".)*

`sipVerb` defaults to **`dial`** so the outbound leg is a Twilio `<Dial>` child
call observable on our subaccount (needed for the identifier/billing
investigation). `refer` hands off to the carrier and hides the leg — do not use it
for the identifier test.

**Tool type = `transferCall`** (camelCase) — verified 2026-08-02 against the Vapi
OpenAPI spec (`api.vapi.ai/api-json`, schema `TransferCallTool` /
`CreateTransferCallToolDTO`). The native `transferCall` tool takes
`destinations` + `transferPlan` (no `function` block). `transferPlan` fields:
`mode`, `sipVerb` (`refer|bye|dial`, default `refer`), `timeout`, `dialTimeout`,
`summaryPlan` (`{enabled,timeoutSeconds,messages}`), `transferAssistant`.

Sources (verified 2026-08-02): api.vapi.ai/api-json ·
docs.vapi.ai/api-reference/tools/create · docs.vapi.ai/calls/assistant-based-warm-transfer
· docs.vapi.ai/calls/call-ended-reason · docs.vapi.ai/calls/call-dynamic-transfers
· twilio.com/docs/phone-numbers/api/availablephonenumberlocal-resource ·
twilio.com/docs/voice/api/call-resource. **Reconfirm at run time — provider docs change.**

## 3. Prerequisites

Console access (Twilio master, Vapi parent org); a tunnel tool (cloudflared/ngrok);
one line to forward from, one to originate; two operator-owned domestic
destinations. Copy `.env.example` → `.env` and fill locally. **Never commit `.env`.**
Secrets are read only at `--apply` time and never printed or logged.

## 4. Run order

### APPROVED NOW — read-only stage (safe to run today)

```bash
# 1) Prepare env locally (copy .env.example -> .env). PHASE0_RUN_ID must be a UUID
#    or [A-Za-z0-9_-]{8,64}; PHASE0_SERVER_URL = https://<tunnel>/hook/<PHASE0_RUN_ID>
./run_local_checks.sh                        # local, non-network — must pass first
python -m phase0.cli validate-config         # exact M1/M2 payloads (local)

# 2) Seed the hashed production denylist (from REAL prod ids — see 5b)
export PHASE0_DENYLIST_PEPPER='<random, kept out of repo>'
python -m phase0.cli seed-denylist --ids-file production_resources.txt

# 3) Start the capture service (path = /hook/<run_id>)
python -m phase0.capture                     # localhost:8099
cloudflared tunnel --url http://localhost:8099

# 4) Local preflight (no network)
python -m phase0.cli preflight

# 5) Read-only live preflight (GET only). Loads the denylist + refuses a production
#    host BEFORE contacting anything; writes a sanitized readiness receipt.
python -m phase0.cli preflight-live --apply

# 6) STOP and review: phase0-evidence/readiness_receipt.json + lifecycle state.
python -m phase0.cli state                    # expect: provider_preflight_ready
```

### NOT YET APPROVED — mutating stage (do NOT run without explicit approval)

The manual approval boundary is BETWEEN step 6 and everything below.

```bash
python -m phase0.cli provision --apply        # creates provider resources
python -m phase0.cli select-mode --mode M1 --apply
python -m phase0.cli verify --apply
#   ...enable carrier forwarding...           # telephony change
#   ...place test calls...                    # ONLY after `state` == call_test_ready
python -m phase0.cli inspect --apply --vapi-call-id <CALL_ID>
python -m phase0.cli stop --apply             # mutations — only to recover from an
python -m phase0.cli teardown --apply         # expressly authorized later run
python -m phase0.cli cost --legs legs.json    # local
```

## 5. Limits — labelled by who enforces them (`phase0.cli limits`)

- **`max_call_seconds = 300` — PROVIDER-ENFORCED.** Set as `assistant.maxDurationSeconds`; Vapi terminates the call.
- **`max_calls = 20` — HARNESS-OBSERVED (best-effort) + OPERATOR-ENFORCED.** The capture service only sees calls that reach the assistant (transfer / end-of-call events); a call that fails before Vapi is **not** counted, so this number is **not guaranteed complete** — the operator must also watch.
- **`budget = $25` — OPERATOR-ENFORCED. NOT a software cap.** Set provider-side before running: a **Twilio usage trigger**, a **restricted/low subaccount balance**, and a **Vapi spending limit**.
- **Destination class — HARNESS-ENFORCED.** Domestic allow-list only; emergency/premium/international/short codes rejected.

## 5b. Mandatory production denylist (fail-closed)

`--apply` refuses to run unless a valid production denylist exists. Seed it once
from an operator-local file of **real** production identifiers (gitignored); only
keyed HMAC hashes are stored — never raw values:

```bash
export PHASE0_DENYLIST_PEPPER='<a long random string kept out of the repo>'
cp production_resources.txt.example production_resources.txt   # then fill with REAL values
python -m phase0.cli seed-denylist --ids-file production_resources.txt
```
Seed **all** of: the production OpenLines number, Twilio account + subaccount SIDs,
Vapi org + assistant + phone-number ids, known customer resource ids, and (as
`host:` lines) the production webhook host(s). `--apply` fails closed if the
denylist is missing/empty/unreadable/malformed or the pepper is unset, and refuses
if the tunnel host matches a production host.

## 5c. Selecting the transfer mode (M1 / M2)

```bash
python -m phase0.cli select-mode --mode M1     # dry-run plan
python -m phase0.cli select-mode --mode M1 --apply
```
This binds the temp number to the chosen mode's assistant, **reads it back**, and
verifies the bound `assistantId`, the transfer `mode`, and `serverMessages`. It
refuses to mark the mode "ready" if requested and stored differ, and records the
selected mode in both manifests. Emergency stop detaches the assistant. **M2's
`transferAssistant` is inline JSON — Vapi creates no separate transfer-assistant
resource, so none appears in the manifest, provisioning, or teardown.**

## 6. Emergency stop

**Order matters — the tunnel is NOT the kill switch.**
1. **Manually disable carrier forwarding** on the business line (dial the
   carrier's disable code). Until this is done, calls keep arriving.
2. `python -m phase0.cli stop --apply` — detaches the assistant from the number
   (stops new inbound routing), removes the transfer tool from both assistants,
   and lists active Vapi + Twilio legs so the operator can end them.
3. Stop the capture process / kill the tunnel (prevents new dynamic destinations).
4. If needed, end active Twilio legs (`stop` lists their SIDs).

## 7. Teardown + verification

```bash
python -m phase0.cli teardown --apply       # release number, delete assistants, suspend subaccount
python -m phase0.cli verify --apply         # re-list; any resource still present => cleanup INCOMPLETE
# only after verification confirms removal: delete the operational manifest.
```
Teardown capability is **documented but unverified** against a live account until
`teardown --apply` runs — see the matrix from `verify-teardown`. `close_subaccount`
is **irreversible**; the harness uses `suspend` by default. `delete_suborg` and Vapi
`end_call` are **UNVERIFIED** and may require the dashboard / a control URL.

## 8. Evidence & privacy

- Operational manifest: `phase0-evidence/manifest.operational.json` — gitignored,
  `0600`, never printed in full, deleted only after teardown verification.
- Review manifest: `phase0-evidence/manifest.review.json` — masked, shareable.
- Events: `phase0-evidence/events-<date>.jsonl` — sanitized allow-list only.
- Raw payload capture is **not** available by default. If ever needed, it must be a
  separate, short-lived, encrypted mode with immediate deletion (not implemented
  here by design).
- Retention: keep sanitized evidence for the Phase 0 review only; delete raw
  captures within 7 days.

## 9. Identifier investigation (what to capture)

The harness captures enough to answer, per attempt: Vapi `call.id`; provider call
id Vapi exposes (`call.phoneCallProviderId`); Twilio inbound `CallSid`; Twilio
outbound/child `CallSid` (if `sipVerb=dial`); `ParentCallSid`; per-leg direction /
status (`DialCallStatus`) / duration / price; event ordering; whether multiple
attempts have distinct ids. **Do not finalize a production deduplication key from
this task** — record the evidence for a later decision.

## 10. Files

See the handoff message accompanying this package for the file-by-file purpose,
local verification results, exact `--apply` operations, unverified assumptions,
and the execution-approval page.

## 11. Provider-compatibility corrections (verified 2026-08-02)

1. **Request encoding is provider-specific.** Vapi = JSON (`application/json`);
   Twilio v2010 = form (`application/x-www-form-urlencoded`). GET/DELETE send no
   body; query params are URL-encoded separately. Errors are sanitized (status +
   redacted snippet); credentials/numbers/bodies are never logged. See
   `providers/base.py` + `test_transport.py`.
2. **Tool type `transferCall`** (see §2). Fixtures/config/tests/read-back updated.
3. **Dynamic destination = BARE.** The capture webhook returns only
   `{destination:{type:"number",number,numberE164CheckEnabled}}`; the COMPLETE
   mode-specific `transferPlan` (M1 `summaryPlan`, M2 `transferAssistant`,
   timeouts) lives once on the assistant tool, so dynamic selection cannot change
   the mode. `PHASE0_MODE` must match the bound assistant (capture refuses
   otherwise). Tests: `test_capture_fixture.py`, `test_config_models.py`.
4. **Apply-time preflight** (`phase0.cli preflight`) validates HTTPS capture URL,
   webhook secret, Twilio + Vapi creds, area code / explicit number, destination
   allow-list, initial mode, unique `PHASE0_RUN_ID`, spend-controls ack, mandatory
   denylist, manifest-outside-repo, and no-existing-manifest-unless-`--resume`,
   BEFORE the first mutation. A separately-authorized `preflight-live` does the
   network health/credential checks (never run in local tests).
5. **Webhook auth decision: shared secret via the `X-Vapi-Secret` header**
   (Vapi's `server.secret`), the production-proven mechanism. Constant-time
   `hmac.compare_digest`, non-empty required, never stored/logged. No undocumented
   header and no server-credential-ID mechanism is required today.
6. **Capture hardening:** exact path `/hook/<run_id>`, health `/healthz`, method
   allow-list, `application/json` required, 256 KiB body cap, run-id path binding,
   lock-guarded atomic sanitized writes, graceful shutdown. Tests:
   `test_capture_fixture.py`.
7. **Review manifest masks ALL provider identifiers** (SIDs/UUIDs/ids + numbers);
   complete values live only in the restricted operational manifest. Test:
   `test_review_mask.py`.
8. **Number acquisition = search → select → purchase-exact** (prefer
   `address_requirements == "none"`; CA numbers may need a Twilio Address/regulatory
   bundle). No blind `AreaCode` purchase. See `provision.py` + `providers/twilio.py`.
9. **Cost** separates published-rate estimate (Twilio **ceil-to-minute**, Vapi
   per-second) from **actual metered** provider prices, and connected vs
   ringing/unanswered minutes. See `cost.py` + `test_cost.py`.
10. **Teardown:** suspend ≠ close (close is IRREVERSIBLE, manual); sub-org deletion
   + Vapi call-ending are UNVERIFIED (dashboard/control-URL). See `verify-teardown`.
