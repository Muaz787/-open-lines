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
2. For each tenant, read Stripe's meter total for its customer over the billing period,
   using the `call_minutes` meter's event summaries. Summaries lag behind events, so read
   twice, at least 2 minutes apart, and use them only when both reads agree.
3. Compare Stripe's total with the ledger: `reported` rows plus the row in review.
4. **If Stripe's total includes the row:** set it to `reported`, and make
   `overage_minutes_reported` equal Stripe's total for the current period.
5. **If it doesn't:** the customer wasn't billed for it. Decide deliberately whether to
   bill it, and record the decision. If you don't, set the row to `none`.

Each step that changes a row or a tenant needs approval at the time.

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

## Release and rollback

The operational SQL is in `ops/usage-ledger-release/`. Each script states what it does.

### Why a hold is needed

`claim_pending_webhook_events` reads pending events without locking or marking them. If
an old and a new backend run at once, both can process the same call. A quiet period
doesn't prevent that.

`hold-on.sql` stores new end-of-call events as `held:usage-042`, which no backend
reads. Call intake keeps working. It only changes events that arrive as `pending`, and it
refuses to start if any event already has a status other than `pending`, `done` or
`failed`. `hold-off.sql` releases only `held:usage-042` events, in order, and prints each
ID. `handover-status.sql` shows the hold, the held IDs, and events still being processed.

### How Railway ends the old deployment

Railway sends the old deployment SIGTERM once the new one is active, then SIGKILL after the
draining period, which defaults to 0 seconds. With no health check, a deployment is
active as soon as its container starts. The overlap default isn't documented, so it isn't
assumed. Before either step below, read Railway's deployment list until the previous
deployment shows **Removed**. `/health` reporting the new commit isn't enough on its own.

### Release

1. Apply migration 042, and verify it.
2. Run `hold-on.sql`, then wait for `handover-status.sql` to show `in_flight = 0`.
3. Merge the code, and wait for `/health` to report the merge commit and for the previous
   web and cron deployments to show Removed.
4. Run `hold-off.sql`, and check the released IDs match the held IDs.

If the deploy fails while held, the old code is still running: run `hold-off.sql`.

### Rollback

The old code sends Stripe the gap between usage over the allowance and
`overage_minutes_reported`, under a new identifier. That gap includes a report Stripe
accepted just before a crash, and any row in review. **`pending = 0` isn't enough.** In a
test, the old code billed 15 minutes instead of 8 with `pending = 0`.

1. Run `hold-on.sql`, and wait for `in_flight = 0`. No new call can report overage.
2. Run `rollback-pause.sql`, and keep the rows it prints. Retries stop.
3. Deploy the revert, and wait until the previous deployment shows **Removed**. Only now
   can no request to Stripe still be under way. This replaces a timed wait.
4. The old code runs from here, but can't report anything: its only meter call is in call
   recording, and the hold keeps calls from being processed.
5. Reconcile every row from step 2 against Stripe, as above.
6. Run `rollback-gate.sql`. Every value must be 0, including `resend_exposure_minutes`.
7. Run `hold-off.sql`.

If the gate can't reach 0, keep the hold on and redeploy the new code instead. Releasing
the hold onto the old code would bill the exposure again. Rows left in the ledger stay
valid if the new code returns.
