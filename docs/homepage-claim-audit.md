# Homepage and pricing claim audit

Scope: the P0 items from the website review of 31 October 2026, on `/` and `/pricing`.
"Support" says what the claim was checked against. This is a marketing accuracy
review, not legal advice.

## Changed

| Former wording | Support found | Risk | Replacement |
|---|---|---|---|
| "Save up to $45,000 a year" | None. The page's own figures gave $32,412 | Misleading saving | Plan price, included minutes and overage |
| "$2,800 / mo", "$33,600+", "$2,800–$4,000 a month" | No source | Unsupported figures | $3,640 a month and $43,680 a year, sourced below |
| "Turnover risk: None", "Scales with calls: Yes" | No measurement | Absolute | Removed; added a "Best at" row showing each option's limits |
| "<1s Answer latency" | No defined measurement | Performance promise | Removed |
| "0 Missed calls" | Calls can fail or lines can be inactive | Guarantee | Removed |
| "Live right now" and "Live · 3 new today" style badges | Hardcoded | Fake activity | Removed; "Example dashboard · sample data" |
| "Shahid Real Estate", "Hartwell & Associates LLP", "Smile Dental Group", "Studio Nova" | Fictional or unverified names that could match real businesses | Implied customers | "Sample Realty", "Sample Law Firm", "Sample Dental Clinic", "Sample Hair Salon" |
| "Learns from every interaction", "improves with every call", "Smarter every call" | No automatic learning. Owners update the knowledge base; websites are re-crawled weekly | False capability | "Keep answers current by updating your services, hours and policies" |
| "Answers every call", "answers instantly", "no wait", "never goes to voicemail" | Availability is not guaranteed | Guarantee | "Answers calls 24/7" |
| "Delivered within seconds of every call ending" | No timing guarantee in code | Performance promise | "Sent after each call" |
| "Texts customers an instant confirmation" | SMS is unavailable on some numbers, such as Irish voice-only lines | Overclaim | Removed from the process step |
| "No staff required" | Not supportable for all work | Absolute | Removed |
| "Setup in under 10 minutes · No contracts · Cancel any time" | Omitted the required card | Incomplete offer | "Setup in under 10 minutes · Free for 7 days · Card required · Cancel any time" |
| "Everything surfaces. Nothing slips." | No support | Absolute | "See what happened on each call." |
| "Confirms … in real time — no follow-up needed" | Booking works during calls; "no follow-up" is too broad | Overclaim | "Checks availability and books appointments during the call" |
| Pricing FAQ: free trial "waitlist" | Card trial live since 9 August 2026 | Contradicts the offer | Actual trial terms |
| "Cheaper than a missed call" | No support | Unsupported comparison | "Simple monthly pricing." |
| No currency on the pricing page | `lib/plans.ts` documents CAD | Ambiguous price | "Prices in CAD, plus tax" |

## Kept

| Wording | Support |
|---|---|
| 24/7 call answering | Listed plan feature, subject to an active line |
| Starter $99, 150 minutes, $0.69 overage | `lib/plans.ts`, `services/usage.py` |
| 7 days, card required, 60 minutes, early charge at the cap | `services/trial.py`, `TrialCardStep.tsx` |
| Google Calendar and Outlook on every plan | `lib/plans.ts` |
| Prices in CAD | Confirmed by the owner, 31 October 2026 |
| Setup in under 10 minutes | Confirmed as realistic by the owner, 31 October 2026, and not measured here. The verification caveat stays because regulated countries take longer |

## /salons and /barbers

Checked against the backend on 31 October 2026.

| Former wording | Support found | Risk | Replacement |
|---|---|---|---|
| "80%", "Four out of five callers" never call back | No source | Invented statistic | "May not leave a message" |
| "Quotes walk-in waits", "how busy you are" | No feature. The AI cannot see the shop floor | False capability | Explains the walk-in policy and offers the next open time; states it doesn't quote live waits |
| "Knows who's in today", "the day's roster" | Team names and per-person availability exist; no daily roster | False capability | Checks a named barber's availability |
| "Confirmation and reminder", "Cuts no-shows" | No appointment reminder in the backend | False capability | "Confirms by text" |
| "Callers rarely realise it's AI" | No evidence, and awkward beside the disclosure | Unsupported | States the opening disclosure |
| "It never guesses", "nothing falls through" | No guarantee | Absolute | Takes details; summary for follow-up |
| "No double-booking" | Live checks exist; no absolute guarantee | Absolute | "Checks live availability" |
| "Answered in 1 ring" | Hardcoded | Performance promise | "Example call · sample data" |
| "Picks up where they left off" | Caller recognition exists | Overclaim | Greets returning callers using earlier calls |
| "Never lose", "no booking gets missed", "answers every call" | No guarantee | Absolute | Plain capability wording |
| "Studio Luxe", "Fade Co." | Could match real businesses | Implied customers | "Sample Salon", "Sample Barbershop" |
| Trial CTA without card or price | Card required; plans start at $99 CAD | Incomplete offer | Adds both |

The trial CTA and sample labels are in `VerticalLanding`, so they also apply to the other industry pages. Their page copy has not been audited.

Confirmed real: Square Appointments on any active plan, booking with a named team member, caller recognition, party size, and deposits on Pro and Business.

## Salary comparison

The homepage uses the Job Bank Canada national median for Receptionist (NOC 14101): $21.00 an hour, from the Labour Force Survey, reference period 2023-2024, updated 19 November 2025.

$21.00 × 40 hours × 52 weeks = $43,680 a year, or $3,640 a month, before employer costs. The Starter figures are $99 a month and $990 a year, plus tax.

The page shows the assumptions and says the two are not like-for-like. It makes no savings claim. Source: https://www.jobbank.gc.ca/marketreport/wages-occupation/24391/ca

Cross-check: PayScale showed C$18.18 an hour for Receptionist in Canada from 231 profiles, updated 7 October 2026, which is about $37,800 a year on the same hours. Job Bank is used because it draws on Statistics Canada data. Provincial medians range from $20.00 in Quebec to $24.00 in British Columbia.

## Unresolved facts

- Tax wording for customers outside Canada.
- Whether a number can be kept or forwarded. Not claimed here.

## Not yet changed

Out of this P0 pass. These still need the same treatment:

- "Every call" appears in about 25 other files; "never miss" in 7. Many are learn or SEO pages.
- The other industry pages using `VerticalLanding`. `/ireland` also inherits "Live in under 10 minutes", which doesn't fit a country that needs verification first.
- Homepage P1 items: rotating hero, "Build your own agent", duplicate demo sections, Ask-an-AI block, and the hardcoded "System Status: Online".
- The homepage overflows sideways by 8px on mobile, from the integrations marquee. This predates the change.

## Owner decisions

- Privacy-policy wording stays as it is for now, by owner decision on 31 October 2026. It is outside this audit.
- Public support contact: support@openlines.ai.

## Evidence still needed from the owner

Sample visuals are labelled and stay in place until these exist:

- Service geography to show publicly.
- Redacted real dashboard screenshot.
- Approved call recording with transcript.
- Customer quotes, logos or results, with permission.
- A real status page, if a status badge is to stay.
