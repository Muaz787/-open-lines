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
- A **paid** deposit whose refund window has closed (see *Refund windows* below)
  is not moved. An owed deposit has paid nothing, so it can move.
- A deposit paid in the last two minutes waits (the caller is asked to give us a
  minute), so its confirmation text can't name a time that is about to change.
- Square accepts the write. A seller without Appointments Plus or Premium can't
  write bookings through the API; Square answers 403 and the caller is told
  nothing changed.

Success needs the booking read back at the new time with the same version step,
team member and service, then our row written by `calendar_move_finish`.

**Remaining limits**
- The real API has not been exercised yet: the sandbox test needs a sandbox seller
  with Appointments and the four `SQUARE_SANDBOX_*` variables.
- Square's availability counts the booking itself, so a move that overlaps its own
  current time (for example 15 minutes later) can be refused as unavailable.
- Square bookings moved by the business in Square itself are not in our move
  history, so they don't count toward a closed refund window.

## Deposits and a move at the same time

**Confirmation texts.** A payment webhook marks the deposit paid, then looks for
anything changing the appointment: a mutation claim (021), a live move operation
(046), or a time that differs before and after it looks. If it finds one, the
caller's text and the owner's note say the deposit is received and the
appointment confirmed, without a day or time. The caller hears the new time on
the call. A move, for its part, reads the payment after taking ownership and waits
if it was paid in the last two minutes. Each side writes before it reads, so one
always sees the other. This applies to Google, Outlook and Square moves.

**Refund windows (for review).** A paid deposit is refundable on cancellation only
if its refund window has never closed since it was paid
(`services.refunds.refund_window_open`):

1. the appointment, where it is now, is at least `cancellation_refund_hours`
   away; and
2. every move that finished after the deposit was paid started, or took the
   payment, while the window for the time it moved *from* was still open.

A move made while the window is open carries refundability to the new time, as
before. What changes: a deposit paid during a move from a time already inside the
window, or an appointment moved inside its window after paying (possible for
Google and Outlook, which don't refuse that), stays non-refundable at the new
time. The hours are the business's current setting, as before. If the move
history can't be read, the deposit is neither refunded nor forfeited: the caller
is told the team will follow up and the business is notified.

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

Rollback: keep 047's columns and every row. Settle any live Square move by reading
the booking, then revert the code: deposit appointments go back to the team handoff.

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
