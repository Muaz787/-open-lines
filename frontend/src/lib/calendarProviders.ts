/**
 * The booking systems a customer can connect, and how each one starts.
 *
 * ONE LIST, TWO SURFACES. The onboarding wizard and the dashboard calendar page
 * both offer these, and a second hardcoded path in either is a connect button
 * that silently stops working the day a route moves. The dashboard keeps its own
 * richer presentation — status, disconnect, Square's sync and enable steps — but
 * the ROUTES live here.
 *
 * `start.kind` is the honest part. Google and Microsoft mint an OAuth URL we can
 * open and be done with. Square cannot: connecting it leaves services and staff
 * unsynced and booking not yet enabled, and its own card on the dashboard owns
 * those steps. A wizard button that implied otherwise would report success for a
 * calendar that cannot take a booking.
 */
export type CalendarProviderId = 'google' | 'microsoft' | 'square'

export type CalendarProvider = {
  id: CalendarProviderId
  label: string
  blurb: string
  start:
    /** Ask the API for an OAuth URL, then send the customer to it. */
    | { kind: 'url'; method: 'GET' | 'POST'; path: (tenantId: string) => string }
    /** Hand off to the page that owns this provider's remaining steps. */
    | { kind: 'page'; path: (tenantId: string) => string; note: string }
}

export const CALENDAR_PROVIDERS: CalendarProvider[] = [
  {
    id: 'google',
    label: 'Google Calendar',
    blurb: 'Books straight into the calendar you already use.',
    start: { kind: 'url', method: 'GET',
             path: t => `/calendar/connect/${t}` },
  },
  {
    id: 'microsoft',
    label: 'Microsoft Outlook',
    blurb: 'For Outlook, Microsoft 365 and Exchange calendars.',
    start: { kind: 'url', method: 'GET',
             path: t => `/calendar/microsoft/connect?tenant_id=${t}` },
  },
  {
    id: 'square',
    label: 'Square Appointments',
    blurb: 'Books into your existing Square schedule.',
    // Square needs a Pro or Business plan on a started subscription, and after
    // authorising you still have to sync services and staff and switch booking
    // on. Its dashboard card does all of that; this only opens it.
    start: { kind: 'page', path: t => `/dashboard/${t}/calendar#square`,
             note: 'A few extra steps — we’ll open it for you.' },
  },
]
