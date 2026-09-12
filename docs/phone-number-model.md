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
