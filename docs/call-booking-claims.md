# Call booking claims (migration 045)

Google and Outlook bookings made during a call claim their slot in
`call_booking_claims` before touching the calendar. The claim, not a read of the
caller's appointments, decides whether a request may create an event.

| Case | What happens |
|---|---|
| Two requests for the same slot at once | One creates the event; the others are told it is already being made |
| Two slots in one call at once | One goes ahead; the other is told another booking is in progress |
| Retry after success | Returns the existing booking; nothing is created |
| Calendar error that proves nothing was made (4xx) | Claim marked failed; the next attempt uses a new event id |
| Timeout or 5xx | Google: the event is looked up by its id. Otherwise the claim stays pending and the caller is told it isn't confirmed |
| Process dies after the event, before the appointment row | After 90 seconds the next request takes the claim over at the same attempt, re-sends the same event id, gets the existing event, and writes the row once |
| Process dies after the appointment row, before marking the claim booked | The next read of the call's bookings marks the claim booked; a takeover finds the row by its event id and writes nothing |
| A second slot passes the first check, then the first booking finishes | After claiming, the request checks the call's bookings again and books nothing without the caller's explicit yes |
| Claim store or appointment lookup fails | Nothing is booked |

Before any appointment is written, the event id is looked up in `appointments`: an
event never gets a second row, however the request got there.

Event ids are derived from tenant, call, slot and attempt. Google is given the id
directly and answers 409 for a repeat; Outlook gets it as `transactionId`, which
Graph uses to drop a repeated create.

`replace_booking` books through the same path, then cancels the earlier booking
under its ownership claim (migration 021). A retry re-reads both bookings: it says
"already done" only when the earlier one reads as cancelled, finishes a cancel that
failed, and reports a cancel whose record could not be written as unconfirmed.

## Release

The booking tool refuses Google and Outlook bookings while the table is missing,
so apply the migration first.

1. In the SQL Editor of project `gsylobklnpytitaqcley`, as `postgres`, apply
   `migrations/045_call_booking_claims.sql`. It aborts if a browser role can read
   the table or `service_role` cannot write it.
2. Check: `select count(*) from public.call_booking_claims;` returns 0.
3. Merge and deploy the backend. Wait for `/health` to report the merge commit.
4. On the next real booking, check that one claim row is `booked` with the
   appointment's id, and that the calendar has one event.

## Rollback

Revert the backend first, then `drop table public.call_booking_claims;`. Reverting
alone is enough to stop using the table.
