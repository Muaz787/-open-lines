# Rescheduling

Callers can move an appointment from the current call or an earlier one. Each
provider uses its own supported operation.

**Not complete yet.** The requirement is rescheduling across Google, Outlook and
Square, with and without deposits. Square appointments with a deposit are still
handed to the team; supporting them is tracked in issue #179. Until that ships,
rescheduling is not complete across providers.

| Provider | How it moves | Ownership and recovery | Deposits |
|---|---|---|---|
| Google Calendar | `PATCH` the event in place (`services.calendar_reschedule`) | Mutation claim (021) + `calendar_move_operations` (046); recovery reads the event | Kept: same appointment row, status unchanged |
| Microsoft Outlook | `PATCH` the event in place | Same as Google | Kept |
| Square, multi-location | W6A2 engine: replacement booking, then cancel the original | Claim (021) + `appointment_reschedule_operations` (020); existing recovery | Not yet supported: handed to the team (#179) |
| Square, single-location | The same W6A2 engine, at the tenant's own Square location | Same as multi-location | Not yet supported: handed to the team (#179) |

## Square appointments with a deposit: temporary team handoff (#179)

This is unfinished work, not a product restriction. It stays in place until a
verified replacement ships (issue #179: Square's booking-update operation, with
payment status and audit history preserved).

Square moves an appointment by booking a replacement and cancelling the original.
A deposit — paid, or still owed through a payment link — is linked to the original
appointment row, so an automatic move would leave the payment attached to a
cancelled appointment. These appointments are therefore refused before anything
is locked or sent:

- The assistant says the appointment has a deposit and can't be moved on this
  call, that nothing has changed, and that the team will move it and keep the
  deposit with it. It takes a message (`create_callback` where routing is on).
- Nothing is charged, refunded, voided or re-linked. The appointment, its status
  and its payment stay exactly as they were.
- If the deposit lookup itself fails, the appointment is treated as having one.
- The team moves it in Square and, if needed, updates the appointment and
  payment records by hand.

Google and Outlook appointments with a deposit can be moved: they move in place,
the row and its payment link are unchanged, and payment status is never touched.

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

## Release

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
