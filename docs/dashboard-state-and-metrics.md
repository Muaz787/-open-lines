# Dashboard account state and metrics

How the dashboard decides what to show. Tests are noted so changes stay checked.

## Account state

Three facts are shown separately, because one says nothing about the others:

| Label | Answers | Source | Values |
|---|---|---|---|
| Phone line | Is there a number, and may it take calls? | `account.phone_line` | On, Off, No number yet |
| Features | Which plan's features are in force? | `account.feature_plan` | Plan name, No paid plan |
| Subscription | How is the plan paid for? | `account.source` and Stripe | See below |

A subscription only reads Active after a direct Stripe lookup confirms it. The dashboard layout does that lookup once and shares it with every page, and until it answers the label is "Checking…".

`services/account_state.py` derives one record from the tenant row, with no Stripe call. It is returned as `account` on `GET /onboarding/status/{id}`. `lib/accountState.ts` turns it into every label, so no page reads `subscription_status` to decide wording.

| `source` | Meaning | Plan label | Status |
|---|---|---|---|
| `subscription` | Stripe subscription exists | "Pro plan", or "Pro trial" while trialing | Active, Trial, Canceling, Past due or Canceled |
| `manual` | Plan set by an admin, no Stripe subscription | "Pro (manual access)" | Manual |
| `complimentary` | `billing_exempt` | "Complimentary", or "Pro (complimentary)" | Complimentary |
| `trial` | Card-free derived trial | "Free trial" | Trial |
| `none` | None of the above | "No active plan" | None |

`GET /billing/subscription-details/{id}` adds `provider_state`:

| Value | Meaning | Dashboard behaviour |
|---|---|---|
| `ok` | Stripe confirmed it | Normal |
| `none` | No subscription ID on the tenant | Uses the account record |
| `missing` | Stripe rejected the stored subscription ID | "Unverified"; plan picker hidden to avoid double billing; line and features unchanged |
| `unavailable` | Stripe couldn't be reached | "Not verified right now"; plan picker hidden |

Complimentary accounts don't see the plan picker, because no deliberate conversion flow exists. This is a dashboard rule; the billing API doesn't enforce it.

While loading, labels are empty and no plan is offered. After a failed request, the label is "Plan unavailable", never "No active plan".

Tests: `tests/test_account_state.py`, `lib/dashboardState.test.mjs`, `e2e/dashboard.spec.ts`.

## Periods

`services/date_ranges.py` is the only definition.

- The timezone is `tenants.calendar_timezone`. A missing or invalid value means UTC.
- A period is a run of local calendar days ending today: Today is 1 day, 7d is 7 and 30d is 30.
- Each starts at local midnight and has no end cap, so calls placed today are included.
- Days are calendar days, so daylight-saving changes don't shift the start.

| Metric | Source | Includes |
|---|---|---|
| Calls handled | `GET /leads/{id}/stats` | Every call row in the period |
| Call history, quality counts | `GET /calls/{id}`, `/analytics` | The same rows and start time |

History lists up to 100 calls and analytics reads up to 1,000, so very busy periods can show fewer rows than the totals.

Chart bars use hourly SQL buckets mapped onto local days, which needed no migration. In zones with a half-hour offset, a call near midnight can land in the neighbouring bar. Totals are unaffected.

Tests: `tests/test_date_ranges.py` covers local midnight, both daylight-saving changes, a 25-hour day, half-hour zones and the overview matching call history.

## Leads

- **Lifecycle** is `status`: New, Contacted, Converted.
- **Qualification** is `urgency`: Hot, Warm, Cold, or "Unrated" when unset.

They are separate. The overview used to show "New" for an unset urgency, which clashed with lifecycle.

## URL state

| Page | Parameter | Values | Default |
|---|---|---|---|
| Overview | `period` | `today`, `7d`, `30d` | `7d` |
| Calls | `period` | `7`, `30`, `0` | `30` |
| Calls | `quality` | `all`, `hot`, `warm`, `cold` | `all` |
| Leads | `status` | `all`, `new`, `contacted`, `converted` | `all` |
| Calendar | `appointments` | `upcoming`, `past` | `upcoming` |

Unknown values fall back to the default before any request. Defaults are left out of the URL.

## Tokens

The `--db-*` tokens in `globals.css` use the marketing navy `#001F3F`, greys and blue family. Blue `#2563EB` is the action colour, and green is only for success. Text and status pairs were calculated at WCAG AA or better for normal text.
