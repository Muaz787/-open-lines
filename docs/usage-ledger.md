# Usage ledger

Migration 042 adds `usage_events`, one row per call, and `usage_quarantine`. They replace
the old read-then-write counter. `tenants.minutes_used_this_period` is still the number
the dashboard shows.

## Rules

| Case | What happens |
|---|---|
| Normal call | Counted once in the period containing its end time |
| Retried call | Same call ID, so nothing changes |
| Delayed call from an earlier period | Recorded with `counted = false`; doesn't use the allowance; never creates overage |
| Stripe unreachable during a call | Counted now; if it ended in the new period, the rollover keeps it |
| No call ID | Goes to `usage_quarantine`; not counted; not billed |
| No usable end time | Recorded at processing time, with `ended_at_estimated = true`; billed normally |
| Overage | Recorded as `pending`, sent to Stripe, then marked `reported` |

An end time needs a timezone to be usable. A missing, garbled or timezone-less value
counts as no end time. Only the period assignment is estimated: the minutes come from the
call's duration.

## Overage retries

Each call has a stable Stripe identifier. Stripe enforces identifiers for at least 24
hours, so:

- The processor loop retries `pending` rows every 10 minutes, once they're 5 minutes old.
- A row older than 23 hours moves to `review` and is never sent again automatically.
- Stripe answers a repeated identifier with HTTP 400, no error code, and the message
  `An event already exists with identifier <id>.` Only that exact message, with our
  identifier, marks a row reported. Any other refusal leaves it `pending`.

## Admin warnings

System Health shows a **Usage ledger** check. It's an error when overage has stopped
retrying or a call is quarantined, and a warning while overage is pending.

## Reconciling overage in `review`

**Never resend one of these rows.** Stripe may already have the event, and past the
identifier window a resend could bill twice.

1. List the rows: `select * from usage_events where overage_state = 'review'`.
2. Find the customer in Stripe, and open Billing → Meters → `call_minutes`.
3. Look for an event with identifier `ol-usage-` plus the first 40 hex characters of
   `sha256("<tenant_id>:<call_id>")`, at the row's `ended_at`.
4. **If Stripe has it:** set the row to `reported`, and add its minutes to
   `overage_minutes_reported` if it's in the current period.
5. **If Stripe doesn't have it:** the customer wasn't billed. Decide deliberately whether
   to bill it, and record the decision. Set the row to `none` if you don't.

## Reviewing quarantined calls

1. List them: `select * from usage_quarantine where resolved_at is null`.
2. Match each one to `calls` and the Vapi dashboard by tenant, minutes and time.
3. Set `resolved_at` and a `resolution`. Duplicates of one call are expected, because a
   retry can't be recognised without an ID.
4. Don't add the minutes to usage by hand unless you've decided to. Nothing bills them.

## Delayed calls

Rows with `counted = false` aren't charged automatically. They stay in the ledger for the
record, and any decision to bill one is a manual one.

## Starting the ledger

The ledger starts empty, and nothing is backfilled.

- Existing counters stay as they are. The first call adds to the stored value.
- `overage_minutes_reported` stays as it is, so overage already sent isn't sent again.
- The old code had no pending state, so there is no pending overage to carry over.
- The first rollover after release starts the new period from the ledger. Calls from
  before release aren't in it, so the new period starts at the minutes recorded since
  release. That can only lower a count, never raise one.
- `usage_reconcile_report.py` compares counters with call history, read-only. Differences
  are reviewed by a person. There are no automatic historical corrections.

## Retention proposal, not implemented

The privacy policy keeps records while an account is active and for up to 12 months
afterwards, unless the law requires longer, subject to legal, security, billing and backup
requirements.

- Keep `usage_events` and `usage_quarantine` for the life of the account.
- After an account closes, delete them with the account at the existing 12-month purge.
  This already happens through the foreign key's cascade, and it's the only deletion
  that touches them.
- Keep nothing longer unless accounting advice requires it for billing records. If it
  does, de-identify rather than keep tenant-linked rows, and confirm the policy wording.
- Rows hold a call ID, minutes and times, with no caller name, number or transcript.
- A periodic purge for active accounts isn't proposed. No new automatic deletion is added.

## Rollback

Reverting the code leaves the tables and column in place, unused.

**Before reverting, check for pending overage.** The old code works out overage from
`overage_minutes_reported`, which a pending row hasn't updated, so it could resend those
minutes with a new identifier and bill them twice. Let the retry finish, or reconcile the
rows by hand, until `pending` is zero.

Rows left behind stay valid. Re-deploying resumes retrying them, and old ones go to review.
