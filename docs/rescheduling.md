# Rescheduling

Callers can move an appointment from the current call or an earlier one. Each
provider uses its own supported operation.

| Provider | How it moves | Ownership and recovery | Deposits |
|---|---|---|---|
| Google Calendar | `PATCH` the event in place (`services.calendar_reschedule`) | Mutation claim (021) + `calendar_move_operations` (046); recovery reads the event | Kept: same appointment row, status unchanged |
| Microsoft Outlook | `PATCH` the event in place | Same as Google | Kept |
| Square, multi-location | W6A2 engine: replacement booking, then cancel the original | Claim (021) + `appointment_reschedule_operations` (020); existing recovery | Refused: the deposit is linked to the original row |
| Square, single-location | The same W6A2 engine, at the tenant's own Square location | Same as multi-location | Refused |

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
   new time. The confirmation text is sent after that re-read.

## What is kept and what is refused

- The service, length and team member stay the same. A different service is a new
  booking. A different location is refused (Square).
- Google and Outlook: the new time must be inside opening hours and outside the
  break, the team member must be free, and the calendar must be free. The
  appointment's own event and seat are left out, so it can shift a little.
- A date that contradicts the caller's words, or is in the past, is refused.
- An appointment that changed since it was listed is not moved.
- Nothing is charged and nothing is refunded. Payment status is never changed.

## Failure and retries

| Case | Google / Outlook | Square |
|---|---|---|
| Provider refuses (4xx) | Operation `failed`, claim released, original unchanged; a new attempt may run | `create_failed`, original unchanged |
| Timeout or 5xx | The event is read. At the new time: completed. Otherwise `unknown`: claim held, no second `PATCH`; recovery reads again after 120 seconds | `create_unknown`, replayed by the existing recovery |
| Provider moved, our row not | `provider_moved`; recovery writes the row, re-reads it and completes | n/a |
| Retry after success | The reference is consumed; the row is re-read and reported, no new `PATCH` | Second identical call books nothing |
| Two requests at once | One claim per appointment and one live operation per appointment: one move, the other is told it's being changed | Same, through 021 and 022 |

## Release

Apply `migrations/046_calendar_move_operations.sql` before deploying. Until the
table exists, Google and Outlook moves fail closed: the operation can't be
recorded, so nothing is sent to the provider.
