# Phone number model (W9D)

Two models describe a tenant's phone numbers during the transition to regulated
(Irish) numbers. This document says which is authoritative for what, so nobody has
to guess while both exist.

## The two models

| | |
|---|---|
| **`tenant_phone_numbers`** | **Canonical.** Every number a tenant holds, with `purpose` (why it exists) and `status` (where it is in its lifecycle). Added by migration 027. |
| **`tenants.twilio_phone_number`** | **Compatibility mirror** of the tenant's *current permanent* number. Still read by 33 call sites. Not removed, not deprecated yet. |

`tenants.twilio_subaccount_sid` and `tenants.twilio_auth_token` are unchanged and
remain the provider account of record.

## Why a table was necessary

A tenant being migrated onto a regulated number holds **two live numbers at once**:
a temporary test number they are already using, and the new permanent number. A
scalar column can name one of them. The moment promotion writes the permanent
number into the scalar, the still-ringing temporary number resolves to nothing and
a caller reaches a 404.

That is why `db.supabase.get_tenant_by_phone()` became multi-number aware in W9D —
**before** any permanent number is ever bought, not after.

## Lookup order (inbound routing)

1. `tenant_phone_numbers`, exact E.164, `status in ('active','retiring')`
2. `tenants.twilio_phone_number` (legacy scalar)
3. `tenants.vapi_phone_number_id` (some Vapi end-of-call payloads send this instead)

`provisioning` rows are deliberately **not** matched — the Twilio webhook is not
configured yet, so a caller routed there would reach silence. `released` and
`failed` rows are history.

**Disagreement fails closed.** If the table and the scalar both claim one number for
*different* tenants, the lookup returns nothing and logs `PHONE IDENTITY CONFLICT`.
Picking either answer risks handing one customer's call to another customer's
assistant, so a failed call is the safe direction.

## Lifecycle

`purpose` and `status` are **separate columns**, and the two purposes have
deliberately different uniqueness policies:

| purpose | at most one per tenant across | why |
|---|---|---|
| `permanent` | `provisioning`, `active` | a retiring predecessor must keep ringing through its grace period, so `retiring` is excluded |
| `temporary_test` | `provisioning`, `active`, `retiring` | a test number has no replacement story; allowing a second one alongside a retiring one lets a tenant accumulate rented numbers |

Including `provisioning` in the permanent rule is what makes a retried promotion
idempotent: the second attempt cannot insert a second row, so it cannot buy or
import a second number.

The predicates live once in `services/phone_lifecycle.py`. Migration 027 declares
the same status sets, and `tests/test_migration_027_contract.py` asserts the two
agree — so widening one without the other fails the suite rather than production.

## Promotion sequence

```
temporary active
  → permanent provisioning        (buy, configure webhook, import to Vapi)
  → permanent active + temporary retiring   ← BOTH numbers route here
  → mirror tenants.twilio_phone_number
  → grace period
  → temporary released            ← only the permanent routes
```

## What is still scalar-only

Everything except inbound lookup. The 33 scalar consumers are **not** migrated yet;
they keep working because promotion writes the mirror. Migrating them is a later
gate, and is not required for regulated-number rollout.

## Deleting things

Proved on PostgreSQL 15.19 (`backend/scripts/verify_027/stage_e.py`), not inferred:

| you delete | result |
|---|---|
| a `tenant_location` a regulatory address or phone still points at | **refused** (`23503`) — a purchased number or a filed address must never be silently detached |
| a regulatory address a profile still points at | **refused** (`23503`) |
| a regulatory profile a phone row still points at | **refused** (`23503`) |
| a regulatory profile only an event points at | allowed; the event is **deleted with it** |
| a tenant owning locations, addresses, profiles, phones and events | allowed; **the whole cascade completes** |

The event ledger's owner FKs are `ON DELETE CASCADE`, not `SET NULL`. The original
design used `SET NULL` so a deleted profile would leave a de-owned audit row; on real
Postgres that made **tenant deletion impossible** — deleting a tenant fires the
`tenant_id` FK first, nulling `tenant_id` while `regulatory_profile_id` is still set,
tripping `tre_profile_needs_tenant_chk`. Account closure and GDPR erasure would have
failed with `23514`. CASCADE is also better for privacy: a surviving ledger row still
carries `FailureReason` text about a customer who asked to be deleted. So on this
table `tenant_id IS NULL` means exactly one thing: *this callback was never resolved
to a tenant*.

## Backfill

`scripts/backfill_phone_numbers.py` (dry run by default, `--apply` to write).
It refuses to invent: `activated_at` comes from the provider's
`IncomingPhoneNumber.date_created` or is `NULL` (never `tenants.created_at`),
`iso_country` comes from Twilio Lookup v2 (never `tenants.country`, never a guess
from the `+1` prefix, which is Canada and the United States both), and
`provider_sid` comes from the provider. Anything unestablished is a reported skip.

### The two provider skip reasons are not the same fact

| reason | meaning | retryable? |
|---|---|---|
| `provider_numbers_unavailable` | the query to Twilio **failed** — we know nothing | **yes** |
| `provider_account_empty` | Twilio **answered** and the account holds no numbers, so the scalar points at a number we do not own | **no** — a data inconsistency for a human |

W9D returned `[]` for both, which read as a transient outage when it was permanent.
`telephony.fetch_subaccount_numbers()` now returns a `ProviderNumberList` whose
`ok` / `is_empty` are independent, so "unknown" can never be mistaken for "empty".
`error_detail` is built from the exception type, HTTP status and Twilio error code
only — never the provider's message body or URL, which echo the account SID used to
authenticate.

W9F found one tenant in the `provider_account_empty` state (a released number whose
scalar was never cleared). It was **not** repaired by the backfill — a stale scalar
must never become a canonical ownership row.

## Stale scalar pointers

A tenant can hold a `twilio_phone_number` for a number we no longer own — the number
was released at Twilio and the scalar was never cleared. While that pointer is set,
`get_tenant_by_phone()` still resolves it via the legacy fallback.

`scripts/clear_stale_phone_pointers.py --tenant <id>` (dry run by default) clears
**exactly two columns** — `twilio_phone_number` and `vapi_phone_number_id` — under a
write fenced on the values just proved stale, so a concurrent re-provision cannot be
clobbered. It refuses on **any** ambiguity: provider query failed, the account turns
out to hold numbers, the org-wide sweep was incomplete, the number appears anywhere,
a canonical row exists, another tenant claims the E.164, or the Vapi resource is
still live (or its state is unknown).

It deliberately leaves alone:

- **`number_released_at`** — no authoritative release timestamp is obtainable, and
  inventing one is the fabrication `tpn_activated_source_chk` exists to forbid.
- **`twilio_subaccount_sid`** — the sub-account is still valid. Owning no number does
  not make an account stale.

It calls **no** provider mutation. There is nothing left to release or delete; that is
the premise.

## Verifying a release

`/health` includes a `commit` field when the deploy platform told us the SHA
(`RAILWAY_GIT_COMMIT_SHA`, or `GIT_COMMIT_SHA` elsewhere). The field is omitted when
unknown — health never fails over missing metadata — and the value is published only
if it is a well-formed git SHA: 40 hex characters, or 7–12 for an abbreviation. The
13–39 band is refused because that is where all-hex *secrets* live; a Twilio Account
SID lower-cases to 34 hex characters and would otherwise have been published on an
unauthenticated endpoint.

## Regulatory compliance engine (W9G)

The Regulation API is the requirement authority. Ireland's current nine EndUser fields
and single `business_address` document are an **output** of
`services/regulatory_requirements.discover_regulation()`, never an input to it — Twilio's
Regulatory Compliance API is public beta and can change, so a field the provider adds
flows through as a requirement and one it removes stops being asked for.

| module | role |
|---|---|
| `regulatory_requirements` | discovery + the normalized requirement model (no raw provider shape leaks out) |
| `regulatory_ireland` | IE labels and help text, and the unresolved-declaration marking |
| `regulatory_state` | **the only** thing that may move a profile's state |
| `regulatory_engine` | the resumable workflow: address → EndUser → document → Bundle → assignments → Evaluation → submit |
| `regulatory_callback` | signature verification, bundle-only resolution, ledger, transition |
| `regulatory_reconcile` | the recovery path for statuses no callback announces |

### The one declaration W9G refuses to guess

`business_identity` and `is_subassigned` are a compliance declaration to an Irish
regulator about the commercial relationship between OpenLines and the customer.

**Settled:** Twilio documents *"The End-User is the individual or business that answers
the phone call or message"* — that is the tenant, not OpenLines, which also agrees with
Ireland demanding proof of address in the number's own locality.

**Not settled:** read as questions about the *end user*, the answers are
`DIRECT_CUSTOMER` / `NO`; read as questions about the *arrangement*, OpenLines is an ISV
sub-assigning to its customer, so `is_subassigned` is `YES` — which contradicts the same
sentence's own coupling of `DIRECT_CUSTOMER` with `NO`. Twilio's ISV guidance covers A2P
10DLC messaging brands, not regulatory bundles.

So the engine collects everything else, validates the address, builds every provider
resource and runs Evaluation, but **submission blocks with `unresolved_isv_declaration`**
until an operator supplies those two values explicitly.

### Callback signature and the proxy

The signed URL is reconstructed from the **configured** public backend URL plus the known
path (`services/regulatory_engine.callback_url()`), never from `request.url`: behind
Railway's proxy the request's apparent scheme and host are not what Twilio signed. The
same constant is handed to Twilio as the `status_callback`, so the two cannot drift.
`routers/payments.py` does exactly this for Square's webhook.

An invalid signature gets 403, **no ledger row and no profile mutation**, and a log line
that does not say which part mismatched.

### Number discovery is candidate discovery only

`telephony.search_candidate_numbers()` uses `in_locality` and **never** `area_code`
(which returns zero results for Ireland). The result's `compliance_validated` is a
constant `False`: W9C proved the search locality is not the locality an address must
satisfy, so acceptance is established only by a purchase carrying a real `AddressSid`
and `BundleSid` — a later gate. Nothing in the W9G path calls
`IncomingPhoneNumber.create`.
