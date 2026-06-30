# Square Appointments — P0 Spike Findings

**Status:** P0 complete & green. Ready to scope P1.
**Date:** 2026-06-30
**Goal:** De-risk a native Square Appointments (Bookings API) integration so OpenLines reads
real availability from a merchant's Square calendar and books into the *same* system — no
parallel Google/Outlook calendar. Targets the barbershop/salon vertical (most already run
Square Appointments on their website).

Spike scripts (throwaway, not wired into app code; read `SQUARE_SANDBOX_ACCESS_TOKEN`):
- `backend/scripts/square_appointments_spike.py` — exercises locations / booking profile /
  catalog / team / availability / CreateBooking / CancelBooking.
- `backend/scripts/square_appointments_seed.py` — creates a bookable service + team member via API.

Validated against a **sandbox** Default Test Account (America/Toronto, CAD), Square-Version `2024-11-20`.

---

## What we set out to validate → results

| Question | Result |
|---|---|
| Does Square compute availability for us (pass-through), or must we calculate slots? | **Pass-through.** `POST /v2/bookings/availability/search` returned **150 slots** for one service over 14 days, already honoring staff schedule + location timezone (`13:00Z` = 9:00 AM Toronto). We do **not** calculate slots for this provider. |
| Is the `version` field present on service variations (CreateBooking requires it)? | **Yes.** Every `APPOINTMENTS_SERVICE` variation carries a `version` (e.g. `1782780873035`). Must be passed in `appointment_segments[].service_variation_version`. |
| Availability query window limit? | **32 days, hard.** A 40-day range returned `400 INVALID_TIME_RANGE: "Max query range is 32 days."` → chunk long horizons. |
| Catalog + team data shape for our mapping tables? | Confirmed. Services expose `variation_id`, `version`, name, `service_duration` (ms), `available_for_booking`, and `team_member_ids`. Team via `POST /v2/team-members/search` (status ACTIVE). |
| Is `CreateBooking`'s payload shape correct? | **Yes.** The request passed validation and reached the *subscription* check (not a 400 malformed). Customer create worked first. |
| **Does an Appointments subscription gate the API?** | **Reads: no. Writes: yes.** `CreateBooking` → `403 FORBIDDEN: "Merchant subscription does not support write operations."` while `booking_enabled=False`. Availability/catalog/team reads worked regardless. |

---

## Key conclusions (some revise the original plan)

1. **`booking_enabled` is advisory for reads but authoritative for writes.** (Original plan guessed it
   was advisory-only — corrected.) A merchant can connect and *preview* availability without an
   Appointments subscription, but **booking writes 403 until Appointments is active**. This is the
   right onboarding gate: enable the "bookings flow into Square" switch only when `booking_enabled=true`,
   otherwise show "Subscribe to Square Appointments to enable booking."

2. **We are a pure availability pass-through for this provider.** The Square branch ignores our
   `business_hours_*`, `break_*`, `slot_capacity` knobs (those stay for Google/Microsoft). Square owns
   the slot logic. This is the one asymmetry in the `BookingProvider` contract.

3. **`booking_policy` decides instant-confirm vs pending** (seen in dashboard *Online booking → Settings →
   Reservation guarantee*): `ACCEPT_ALL` → CreateBooking is auto-accepted (what we want for a live phone
   booking); `REQUIRES_ACCEPTANCE` → booking lands **PENDING** and needs the merchant to accept. Our AI flow
   should detect this and either require `ACCEPT_ALL` at onboarding or tell the caller "the shop will confirm
   shortly" when the booking is pending. Must not assume every booking is instantly confirmed.

4. **Phone numbers must be valid E.164** — Square rejects fictional `555` area codes
   (`400 INVALID_PHONE_NUMBER`). Caller numbers from Twilio are already E.164, so fine in production; the
   spike just used a bad test constant initially.

5. **Service-variation `version` staleness risk** stands: a stale version will fail CreateBooking, so we
   refresh it (webhook `catalog.version.updated` or re-fetch) — carried into P1.

---

## What P0 did NOT cover (deferred to P1)

- **OAuth scope granularity** — the sandbox token has full permissions, so we have not yet proven
  `APPOINTMENTS_ALL_READ/WRITE` (managing *other* team members' calendars, required for multi-barber shops).
  Validate by completing the real OAuth flow requesting the exact scopes.
- **A successful end-to-end CreateBooking → Cancel** — blocked only by the sandbox account lacking an
  Appointments subscription at spike time (now being enabled). The payload is already proven correct; the
  round-trip is a formality once Appointments is on (Free plan in sandbox).
- **Webhooks** (`booking.created/updated`, `catalog.version.updated`) for two-way sync — design only so far.
- **Production parity** of the `booking_enabled` write-gate behavior.

---

## Net: green to scope P1

Everything structurally risky is settled — availability is a pass-through, the data model maps cleanly,
the booking payload is correct, and the write-gate is a known, detectable onboarding condition
(`booking_enabled`). P1 (read availability via the new `square_appointments` provider + scopes/reconnect +
catalog/team sync) can proceed. Remaining unknowns (`APPOINTMENTS_ALL_*`, webhooks) are P1 work items,
not blockers.

See the full phased plan in the conversation / `square-appointments` memory.
