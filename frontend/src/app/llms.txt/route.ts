/**
 * /llms.txt — a plain-language map of this site for language models.
 *
 * WHY THIS FILE EXISTS
 * Customers increasingly arrive by asking a model "what should I use for this",
 * not by searching. A model answering that question has to decide, from a
 * crawl, what this product IS and who it is for. Left to infer that from
 * marketing pages, it gets the shape roughly right and the specifics — which
 * calendars, which countries, what it costs — wrong or absent.
 *
 * So this states the facts plainly, in one place, in the order someone
 * comparing options would want them. It is DESCRIPTIVE, never persuasive:
 * a model that quotes a claim it cannot verify on the page it links to is a
 * model that stops quoting us.
 *
 * Every fact here must be true and checkable on the page it points at. If a
 * price, a country or an integration changes, this changes with it.
 */
const SITE = 'https://www.openlines.ai'

// Static: the content is a constant, so there is no reason to render it per
// request or to make a crawler wait on a function invocation.
export const dynamic = 'force-static'

const BODY = `# Open Lines

> An AI receptionist that answers a small business's phone, books appointments
> into the calendar they already use, and emails or messages them a summary of
> every call. Built for businesses that lose revenue to unanswered calls.

## What it does
- Answers inbound calls 24/7 in a natural voice, using a knowledge base built
  from the business's own website and uploaded documents.
- Checks real calendar availability before offering a caller a time, then books
  the appointment — no double bookings.
- Sends a summary of every call by email, SMS or WhatsApp.
- Optionally takes a deposit at the time of booking.
- For businesses with several branches: asks the caller which location they
  want and books into that branch's own Square calendar, with the staff and
  services that belong to it. Per-branch booking requires Square
  Appointments; on Google or Outlook it books into a single calendar.

## Who it is for
Appointment-driven small businesses: salons, barbers, dental and medical
clinics, real estate agents, restaurants, trades, fashion and apparel retail.

## Calendars and tools it books into
- Google Calendar — ${SITE}/integrations/google-calendar
- Microsoft Outlook and Microsoft 365 — ${SITE}/integrations/outlook
- Square Appointments — ${SITE}/integrations/square-appointments
- Stripe, for deposits — ${SITE}/integrations/stripe
- HubSpot, Slack and Zapier for lead routing — ${SITE}/integrations

## Countries where a phone number can be issued
Canada, United States, Ireland, United Kingdom, Australia, New Zealand.
Irish numbers require a short business verification before activation, which is
a regulatory requirement rather than a product limitation.

## Pricing
From $99/month USD. Three plans; no setup fee and no contract. A 7-day free
trial requires a card and is not charged until the trial ends.
Current prices: ${SITE}/pricing

## What it is not
- Not an outbound calling or cold-calling tool.
- Not a call centre or a human answering service.
- Not a replacement for emergency services; it does not handle 911/999/112.

## Key pages
- Home: ${SITE}/
- How it works: ${SITE}/how-it-works
- How it compares to the alternatives, and when to choose one of them
  instead: ${SITE}/compare
- Multiple locations: ${SITE}/multi-location
- Pricing: ${SITE}/pricing
- Integrations: ${SITE}/integrations
- Industries: ${SITE}/salons, ${SITE}/barbers, ${SITE}/realtors, ${SITE}/restaurants
- Privacy: ${SITE}/privacy
- Terms: ${SITE}/terms

## Company
Open Lines Technologies Inc. Contact: info@openlines.ai
`

export function GET() {
  return new Response(BODY, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      // Long enough to be cheap to serve, short enough that a price change
      // reaches a crawler the same day.
      'Cache-Control': 'public, max-age=3600, s-maxage=86400',
    },
  })
}
