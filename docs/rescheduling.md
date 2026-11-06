# Rescheduling

Callers can move an appointment from the current call or an earlier one. Each
provider uses its own supported operation.

**Not complete yet.** The requirement is rescheduling across Google, Outlook and
Square, with and without deposits. Square appointments with a deposit move in
place (issue #179, migration 047), but that path is verified against mocks only
until the Square sandbox test (`tests/test_square_sandbox_update.py`) has run
against a real sandbox seller and a real production move has been observed.

| Provider | How it moves | Ownership and recovery | Deposits |
|---|---|---|---|
| Google Calendar | `PATCH` the event in place (`services.calendar_reschedule`) | Mutation claim (021) + `calendar_move_operations` (046); recovery reads the event | Kept: same appointment row, status unchanged |
| Microsoft Outlook | `PATCH` the event in place | Same as Google | Kept |
| Square, multi-location | Without a deposit: W6A2 engine, replacement booking then cancel the original. With a deposit: `UpdateBooking` in place (`services.square_inplace_reschedule`) | Engine: 020/021/022. In place: claim (021) + `calendar_move_operations` (046/047) | In place: same booking id, same row, deposit stays linked |
| Square, single-location | The same, at the tenant's own Square location | Same | Same |

## Square appointments with a deposit (#179)

Square's `UpdateBooking` moves a booking and keeps its id: only `start_at` is sent,
with the version it was read at and an idempotency key. The appointment row stays
too, so a deposit linked to it, whether paid or still owed, stays linked. Nothing
is charged, refunded, voided or re-linked, and payment status is never written.

It moves automatically only when all of this holds; otherwise the team moves it:

- Same location, service, team member and length. Square is asked for the new
  time for the booking's own team member; a free slot with someone else is not
  enough.
- The booking at Square still matches our record (accepted, one segment, same
  start, location and team member) when it is read under ownership.
- A **paid** deposit already inside the business's non-refundable window
  (`cancellation_refund_hours`, default 24) is not moved. An owed deposit has paid
  nothing, so it can move. Refund eligibility on cancellation is unchanged.
- Square accepts the write. A seller without Appointments Plus or Premium can't
  write bookings through the API; Square answers 403 and the caller is told
  nothing changed.

Success needs the booking read back at the new time with the same version step,
team member and service, then our row written by `calendar_move_finish`.

**Remaining limits**
- The real API has not been exercised yet: the sandbox test is blocked because
  the sandbox seller can't write bookings (Square support case pending).
- Square's availability counts the booking itself, so a move that overlaps its own
  current time (for example 15 minutes later) can be refused as unavailable.
- When a deposit lands during a move, its text leaves the day and time out; the
  caller hears the new time on the call.

## Deposits and a move at the same time

**Confirmation texts.** A deposit confirmation takes ownership of the appointment
(a `payment_confirmation` claim, migration 047) before it reads the time, and
releases it after its texts are sent. A move needs the same ownership, so the two
never overlap: a move that meets a confirmation is told the appointment is being
changed, and a confirmation that meets a move (or can't take ownership) says the
deposit is received and the appointment confirmed, without a day or time. The
claim has a five-minute lease so a stopped webhook can't hold an appointment;
before each message the confirmation checks it has at least 60 seconds of lease
left (each send has its own shorter timeout), and leaves the time out if not.
Recovery and the next move or cancellation clear expired confirmation claims.
A Square booking webhook that meets a confirmation asks Square to redeliver.
`tests/test_deposit_move_payment_state.py` pauses a confirmation and a move before
each read, write and send and runs all 3,003 orders: no text names a time that
differs from our record or Square's at the moment it is sent. Without the claim,
1,569 of them do.

## Validation scope (#179 production test)

Everything new is off unless all of these are set on the **web** service
(`services/square_inplace_scope.py`):

| Variable | Value |
|---|---|
| `SQUARE_INPLACE_TEST_TENANT_ID` | the one workspace |
| `SQUARE_INPLACE_TEST_LOCATION_ID` | its Square location |
| `SQUARE_INPLACE_TEST_CALLER_PHONE` | the one caller, E.164, matched against call metadata (never the model) |
| `SQUARE_INPLACE_TEST_EXPIRES_AT` | ISO-8601 UTC, at most 24 hours ahead (otherwise off) |

- Nothing works until a run is **armed**: an operator inserts the sha256 of a
  one-time code of at least 12 digits into `inplace_test_runs`. The plaintext never
  leaves the caller; it is not in any setting or log.
- Only that caller, on that workspace, inside the window, is offered a `test_code`
  field on `book_appointment`, and those calls are not recorded. Everyone else's
  tools, prompt and recording are unchanged.
- A call from that caller that ends without using an armed code disables it: the
  code may now be in that call's transcript. Arm a new one.
- A Square booking by that caller with the right code gets one CAD $1.00 deposit
  link (`services/inplace_test_deposit.py`). The amount is fixed in code. Workspace
  deposit settings stay off and are never read or changed.
- Using the code marks its row used by that call (single use), binds the one
  appointment, and lets only one request claim the payment link, so retries and
  concurrent requests can't create a second link.
- The in-place move and the deposit-confirmation lock act only on the appointment
  bound to a live, enabled run. Everyone else: today's team handoff for a Square
  deposit move and today's confirmation text.

**Stop the test immediately:** `update public.inplace_test_runs set disabled_at = now()
where disabled_at is null;` takes effect on the next request, used or not, with no
redeploy: an unused code can't be used, and a used one can't create a link, move
or lock anything. Unsetting a variable or
letting the expiry pass also turns everything off.

**An unfinished move after the test is stopped:** the move keeps the appointment's
ownership claim, so other calls hear it is being changed. Recovery
(`calendar_reschedule.run_recovery`, in the web service's background processor) does
not consult the scope. It reads Square's booking and never re-sends:
- at the new time: writes our row and releases the claim;
- still at the old time after two minutes: marks the move failed and releases;
- unreadable or anything else: leaves it held for a person.

Expired confirmation claims are swept by the same pass.

## Refund windows

Unchanged in this release: a cancelled deposit is refunded when the appointment,
at its current time, is at least `cancellation_refund_hours` away. A proposed rule
that stops a reschedule reopening a closed window, and sends refunds after moves
made directly in Square to the team, is on branch `refund-window-policy` for
separate review. Until then, a deposit paid during a move from a time already
inside the window is judged from the new time.

## The conversation

1. `reschedule_appointment` with no arguments lists the caller's appointments
   and changes nothing.
2. The caller picks one and is asked to confirm it.
3. `check_availability` for the new day. Square records the offered slots
   (`slot_ref`); Google and Outlook check the requested time again when moving.
4. The assistant confirms the new day and time out loud, then calls
   `reschedule_appointment` with:
   - Square: `appointment_ref` and `slot_ref`;
   - Google and Outlook: `appointment_ref`, `date`, `time` and `date_phrase`.
5. Success is reported only after both the provider and our row are re-read at the
   new time. For Google and Outlook the event must read back active, starting and
   ending exactly where it was moved; anything else — a different time, a
   cancelled event, an unreadable calendar — keeps the operation live and the
   appointment owned, and the caller is told the team will confirm. The
   confirmation text is sent only after both re-reads.

## What is kept and what is refused

- The service, length and team member stay the same. A different service is a new
  booking. A different location is refused (Square).
- Google and Outlook: the new time must be inside opening hours and outside the
  break, the team member must be free, and the calendar must be free. The
  appointment's own event and seat are left out, so it can shift a little.
- A date that contradicts the caller's words, or is in the past, is refused. So
  is a time earlier today, judged in the tenant's timezone.
- On clock-change days, a time that doesn't exist (clocks go forward) or happens
  twice (clocks go back) is refused, and the caller is asked for another time.
- An appointment that changed since it was listed is not moved.
- Nothing is charged and nothing is refunded. Payment status is never changed.

## Failure and retries

| Case | Google / Outlook | Square |
|---|---|---|
| Provider refuses (4xx) | Operation `failed`, claim released, original unchanged; a new attempt may run | `create_failed`, original unchanged |
| Timeout or 5xx | The event is read. At the new time: completed. Otherwise `unknown`: claim held, no second `PATCH`; recovery reads again after 120 seconds | `create_unknown`, replayed by the existing recovery |
| Provider moved, our row not | `provider_moved`; recovery re-verifies the event, writes the row, re-reads it and completes | n/a |
| Provider says moved, event reads back different, cancelled or unreadable | Stays `provider_moved` with the reason; claim held; no row change, no text; an unreadable event completes once it reads back correctly | n/a |
| Retry after success | The reference is consumed; the row is re-read and reported, no new `PATCH` | Second identical call books nothing |
| A recovery worker pauses, then resumes after the move finished, a newer move, or a cancellation | Nothing: the appointment write, completion and release happen in one transaction (`calendar_move_finish`) that requires this operation to still own the appointment; no stale text, no release of a newer claim. Recovery also leases each operation, so one worker settles it at a time | n/a |
| Two requests at once | One claim per appointment and one live operation per appointment: one move, the other is told it's being changed | Same, through 021 and 022 |

## Release (047, Square deposits)

1. Run `migrations/preflight/047_preflight.sql` on production; every `ok` must be
   true, including no live moves.
2. Apply `migrations/047_square_inplace_moves.sql`, then run
   `ops/rescheduling/verify-047.sql`; every `ok` must be true.
3. Merge and deploy. Until 047 is applied, a Square deposit move can't be recorded,
   so it is refused and handed to the team as before.
4. Check `/health` and System Health. On the first natural Square deposit move:
   the booking id is unchanged, its version went up by one, the booking and our
   row show the new time, payment rows are untouched and ownership is released.

Rollback: first disable the run (see *Validation scope*); the in-place path, the
test deposit and the confirmation lock stop for everyone. Keep 047's columns, its constraint and
every row. Settle any live Square
move by reading the booking, then revert the code: deposit appointments go back
to the team handoff and confirmations name the time as before. Old code doesn't
know `payment_confirmation` claims and won't expire them, so after the old code
is live, delete any that remain (they last seconds:
`delete from appointment_mutation_claims where operation_type = 'payment_confirmation'
and claimed_at < now() - interval '5 minutes'`).

## Release (046)

1. Run `migrations/preflight/046_preflight.sql` on production; every `ok` must be true.
2. Apply `migrations/046_calendar_move_operations.sql`, then run
   `ops/rescheduling/verify-046.sql`; every `ok` must be true.
3. Merge and deploy. Until the table exists, Google and Outlook moves fail closed:
   the operation can't be recorded, so nothing is sent to the provider.
4. Check `/health` reports the merge commit and System Health passes.
5. On the first natural reschedule: one operation row reaches `completed`, the
   appointment row and its event are at the new time, and the claim is released.

## Rollback

Keep the table, the function and every row.

1. First check `calendar_move_operations` for rows in `in_progress`, `unknown` or
   `provider_moved`, and `appointment_mutation_claims` for `reschedule` claims.
   Settle each one by reading its calendar event and recording the outcome. Old
   code doesn't know these operations and would otherwise leave the appointment
   owned.
2. Then revert the code (revert the merge, or redeploy the previous Railway
   deployment). Rescheduling falls back to the old behaviour: Google and Outlook
   callers are told moves aren't supported, and single-location Square loses the
   reschedule tool.
