/**
 * The booking systems a customer can connect, and how each one starts.
 *
 * ONE LIST, TWO SURFACES. The onboarding wizard and the dashboard calendar page
 * both offer these, and a second hardcoded path in either is a connect button
 * that silently stops working the day a route moves. The dashboard keeps its own
 * richer presentation — status, disconnect, re-sync — but the ROUTES live here.
 *
 * NOTHING HERE HANDS OFF TO THE DASHBOARD. A customer in onboarding is there to
 * reach a working phone number, and a step that sends them to another part of
 * the product to finish is a step that ends the flow: the provider's redirect
 * lands them on the dashboard and the wizard is simply over. Every provider
 * therefore starts with a URL the wizard can open itself.
 */
export type CalendarProviderId = 'google' | 'microsoft' | 'square'

export type CalendarProvider = {
  id: CalendarProviderId
  label: string
  blurb: string
  /** Ask the API for an OAuth URL, then send the customer to it. */
  start: { method: 'GET' | 'POST'; path: (tenantId: string) => string }
  /**
   * Providers that are NOT bookable the moment OAuth returns.
   *
   * Square imports the merchant's services and staff and then has to be
   * switched on; until both happen it is connected but cannot take a booking.
   * Reporting success in between would be the same lie as the old hand-off,
   * just quieter — so whoever offers Square runs these before saying it is
   * ready.
   */
  finalize?: {
    syncPath: (tenantId: string) => string
    enablePath: (tenantId: string) => string
  }
}

export const CALENDAR_PROVIDERS: CalendarProvider[] = [
  {
    id: 'google',
    label: 'Google Calendar',
    blurb: 'Books straight into the calendar you already use.',
    start: { method: 'GET', path: t => `/calendar/connect/${t}` },
  },
  {
    id: 'microsoft',
    label: 'Microsoft Outlook',
    blurb: 'For Outlook, Microsoft 365 and Exchange calendars.',
    start: { method: 'GET', path: t => `/calendar/microsoft/connect?tenant_id=${t}` },
  },
  {
    id: 'square',
    label: 'Square Appointments',
    blurb: 'Books into your existing Square schedule.',
    start: { method: 'POST', path: t => `/square-connect/onboard/${t}?origin=calendar` },
    finalize: {
      syncPath:   t => `/square-connect/appointments/sync/${t}`,
      enablePath: t => `/square-connect/appointments/enable/${t}`,
    },
  },
]
