/* ─────────────────────────────────────────────────────────────
   Integration landing content — one object per SUPPORTED integration.
   Only integrations that are actually live in the product belong here.
   Drives /integrations/[tool] and the /integrations hub.
   ───────────────────────────────────────────────────────────── */

export interface IntegrationContent {
  slug: string
  name: string
  emoji: string
  eyebrow: string
  metaTitle: string
  metaDescription: string
  h1: string
  subhead: string
  whatHeading: string
  what: string
  steps: { title: string; body: string }[]
  benefits: { icon: string; title: string; body: string }[]
  /** Unique, integration-specific detail (de-templating): field mapping, deposit flow, etc. */
  unique: { heading: string; points: { title: string; body: string }[] }
  faqs: { q: string; a: string }[]
  /** Contextual internal links: which industries use this, and related integrations. */
  related: {
    industries: { href: string; label: string; sub?: string }[]
    integrations: { href: string; label: string; sub?: string }[]
  }
  ctaHeading: string
  ctaSub: string
}

export const INTEGRATIONS: IntegrationContent[] = [
  {
    slug: 'google-calendar',
    name: 'Google Calendar',
    emoji: '📅',
    eyebrow: 'Calendar integration',
    metaTitle: 'AI Receptionist for Google Calendar — Open Lines',
    metaDescription: 'Open Lines answers your phone and books appointments straight into Google Calendar with real-time availability. Free 7-day trial.',
    h1: 'An AI receptionist that books straight into Google Calendar.',
    subhead: 'Open Lines answers every call, checks your real Google Calendar availability, and books the appointment — no double-bookings, no back-and-forth, nothing to rip out.',
    whatHeading: 'What the Google Calendar integration does',
    what: 'Connect your Google account once and Open Lines reads your live availability before it offers a caller a time — so it only ever books slots that are actually free. When a caller confirms, the event is written straight to your calendar with the caller’s details, and everyone sees it instantly.',
    steps: [
      { title: 'Connect your Google account', body: 'Authorize Open Lines from your dashboard in a couple of clicks. No plugins, no calendar migration.' },
      { title: 'The AI checks real availability', body: 'On every call it reads your free/busy times, so it never offers a slot that’s already taken.' },
      { title: 'The booking lands in your calendar', body: 'Once the caller confirms, the appointment is written to Google Calendar with their name and details.' },
    ],
    benefits: [
      { icon: '⚡', title: 'Real-time availability', body: 'Books only genuinely open slots by reading your live calendar — no double-bookings.' },
      { icon: '🔄', title: 'Two-way and instant', body: 'New bookings appear in Google Calendar the moment a caller confirms, visible to your whole team.' },
      { icon: '🧩', title: 'Nothing to replace', body: 'Keep working in Google Calendar exactly as you do today. Open Lines just fills it for you.' },
    ],
    faqs: [
      { q: 'Does it check my real availability before booking?', a: 'Yes. Before offering a caller a time, Open Lines reads your live Google Calendar free/busy, so it only books slots that are actually open.' },
      { q: 'How do I connect Google Calendar?', a: 'From your Open Lines dashboard, click to connect your Google account and authorize access. It takes a couple of clicks and there’s nothing to install.' },
      { q: 'Will bookings include the caller’s details?', a: 'Yes. Each event is created with the caller’s name and the details captured on the call, so your calendar is ready to go.' },
      { q: 'Can I use more than one calendar?', a: 'Open Lines books into the Google Calendar you connect. You can also connect Outlook or Square Appointments if you run more than one system.' },
    ],
    unique: {
      heading: 'How the Google Calendar booking works',
      points: [
        { title: 'Reads free/busy before it offers a time', body: 'On every call it checks your live calendar so it never offers a slot that overlaps an existing event — no double-bookings.' },
        { title: 'Writes a complete event', body: 'The confirmed booking is created with the caller’s name, the reason for the call, and the details it captured, so the entry is ready to work from.' },
        { title: 'Works with the calendar you choose', body: 'Point it at the Google Calendar you want it to book into; the rest of your calendars stay untouched.' },
      ],
    },
    related: {
      industries: [
        { href: '/salons', label: 'AI receptionist for salons', sub: 'Books the right stylist into Google Calendar.' },
        { href: '/legal', label: 'AI receptionist for law firms', sub: 'Books consultations into your calendar.' },
        { href: '/home-services', label: 'AI receptionist for home services', sub: 'Books the service call into your calendar.' },
      ],
      integrations: [
        { href: '/integrations/outlook', label: 'Prefer Outlook?', sub: 'Same booking, into Microsoft 365.' },
        { href: '/integrations/square-appointments', label: 'On Square Appointments?', sub: 'Book into your Square calendar.' },
      ],
    },
    ctaHeading: 'Let your calendar fill itself.',
    ctaSub: 'Connect Google Calendar and let your AI receptionist answer, check availability, and book — in under 10 minutes.',
  },
  {
    slug: 'outlook',
    name: 'Microsoft Outlook',
    emoji: '📆',
    eyebrow: 'Calendar integration',
    metaTitle: 'AI Receptionist for Outlook & Microsoft 365 — Open Lines',
    metaDescription: 'Open Lines answers your phone and books appointments straight into Outlook / Microsoft 365 with real-time availability. Free 7-day trial.',
    h1: 'An AI receptionist that books straight into Outlook.',
    subhead: 'Open Lines answers every call, checks your live Outlook and Microsoft 365 availability, and books the appointment — no double-bookings, no back-and-forth, nothing to migrate.',
    whatHeading: 'What the Outlook integration does',
    what: 'Connect your Microsoft account once and Open Lines reads your real Outlook availability before offering a caller a time, so it only books slots that are free. When a caller confirms, the meeting is written to your Outlook / Microsoft 365 calendar with their details, and your team sees it right away.',
    steps: [
      { title: 'Connect your Microsoft account', body: 'Authorize Open Lines from your dashboard in a couple of clicks. Works with Microsoft 365 and Outlook.' },
      { title: 'The AI checks real availability', body: 'On every call it reads your Outlook free/busy times, so it never offers a slot that’s already booked.' },
      { title: 'The booking lands in Outlook', body: 'Once the caller confirms, the appointment is written to your Outlook calendar with their name and details.' },
    ],
    benefits: [
      { icon: '⚡', title: 'Real-time availability', body: 'Reads your live Outlook calendar and books only genuinely open slots — no clashes.' },
      { icon: '🔄', title: 'Instant and shared', body: 'Bookings appear in Outlook the moment a caller confirms, visible across your Microsoft 365 team.' },
      { icon: '🧩', title: 'Nothing to migrate', body: 'Keep using Outlook exactly as you do today. Open Lines simply books into it for you.' },
    ],
    faqs: [
      { q: 'Does it work with Microsoft 365?', a: 'Yes. The integration works with Outlook and Microsoft 365 calendars — connect your Microsoft account and Open Lines books straight in.' },
      { q: 'Does it check availability first?', a: 'Always. Open Lines reads your live Outlook free/busy before offering a caller a time, so it only books open slots.' },
      { q: 'How do I connect Outlook?', a: 'From your Open Lines dashboard, click to connect your Microsoft account and authorize access. It’s a couple of clicks with nothing to install.' },
      { q: 'Can I connect more than one calendar?', a: 'Open Lines books into the calendar you connect. You can also connect Google Calendar or Square Appointments if you run multiple systems.' },
    ],
    unique: {
      heading: 'How the Outlook booking works',
      points: [
        { title: 'Microsoft 365 and Outlook', body: 'Connect your Microsoft account and it books into your Outlook / Microsoft 365 calendar — the same one your team already lives in.' },
        { title: 'Reads free/busy first', body: 'It checks your live Outlook availability before offering a time, so it never books over an existing meeting.' },
        { title: 'Visible across your team', body: 'The event appears in Outlook the moment the caller confirms, so everyone sharing the calendar sees it right away.' },
      ],
    },
    related: {
      industries: [
        { href: '/legal', label: 'AI receptionist for law firms', sub: 'Books consultations into Outlook.' },
        { href: '/insurance', label: 'AI receptionist for insurance', sub: 'Books advisor callbacks into Outlook.' },
        { href: '/automotive', label: 'AI receptionist for auto shops', sub: 'Books service appointments into Outlook.' },
      ],
      integrations: [
        { href: '/integrations/google-calendar', label: 'On Google Calendar?', sub: 'Same booking, into Google.' },
        { href: '/integrations/hubspot', label: 'Add HubSpot CRM', sub: 'Log every caller automatically.' },
      ],
    },
    ctaHeading: 'Let Outlook fill itself.',
    ctaSub: 'Connect Outlook and let your AI receptionist answer, check availability, and book — in under 10 minutes.',
  },
  {
    slug: 'square-appointments',
    name: 'Square Appointments',
    emoji: '🟦',
    eyebrow: 'Booking integration',
    metaTitle: 'AI Receptionist for Square Appointments — Open Lines',
    metaDescription: 'Open Lines answers your phone and books straight into Square Appointments using your real availability. Free 7-day trial.',
    h1: 'An AI receptionist that books into Square Appointments.',
    subhead: 'Open Lines answers every call, reads your live Square Appointments availability, and books the right service into your Square calendar — so the bookings you can’t pick up still land in the system you already run.',
    whatHeading: 'What the Square Appointments integration does',
    what: 'Connect your Square account once and Open Lines reads your real Square Appointments availability before offering a caller a time. When the caller confirms, the appointment is booked into your Square calendar — the same place your walk-ins and online bookings live — so everything stays in one system.',
    steps: [
      { title: 'Connect your Square account', body: 'Authorize Open Lines from your dashboard in a couple of clicks. Your services and availability come across automatically.' },
      { title: 'The AI checks real availability', body: 'On every call it reads your live Square availability, so it only offers times you can actually take.' },
      { title: 'The booking lands in Square', body: 'Once the caller confirms, the appointment is booked into your Square Appointments calendar with the right service.' },
    ],
    benefits: [
      { icon: '⚡', title: 'Live Square availability', body: 'Reads your real Square Appointments calendar and books only open slots — no clashes with existing bookings.' },
      { icon: '🗂️', title: 'One source of truth', body: 'Phone bookings land in the same Square calendar as your walk-ins and online bookings.' },
      { icon: '🧩', title: 'No new software', body: 'Keep running Square exactly as you do. Open Lines just answers the phone and books into it.' },
    ],
    faqs: [
      { q: 'Does it book into my real Square calendar?', a: 'Yes. Open Lines reads your live Square Appointments availability and books confirmed appointments straight into your Square calendar — the same place your other bookings live.' },
      { q: 'Do my services come across?', a: 'When you connect your Square account, your services and availability are used so the AI can book the right service at a time you can actually take.' },
      { q: 'How do I connect Square?', a: 'From your Open Lines dashboard, connect your Square account and authorize access. It takes a couple of clicks.' },
      { q: 'Can it also take deposits?', a: 'Yes — on eligible plans Open Lines can text a secure payment link to collect a deposit and cut no-shows, alongside the Square booking.' },
    ],
    unique: {
      heading: 'How the Square Appointments booking works',
      points: [
        { title: 'Your services come across', body: 'When you connect Square, your service list and availability are used so the AI books the right service at a time you can actually take.' },
        { title: 'Books into your Square calendar', body: 'Phone bookings land in the same Square Appointments calendar as your walk-ins and online bookings — one source of truth.' },
        { title: 'Deposits alongside the booking', body: 'On eligible plans it can text a secure payment link to take a deposit at the same time it books, cutting no-shows.' },
      ],
    },
    related: {
      industries: [
        { href: '/salons', label: 'AI receptionist for salons', sub: 'Books the right stylist into Square.' },
        { href: '/barbers', label: 'AI receptionist for barbershops', sub: 'Books the right barber into Square.' },
      ],
      integrations: [
        { href: '/integrations/stripe', label: 'Take deposits with Stripe', sub: 'Cut no-shows at booking.' },
        { href: '/integrations/google-calendar', label: 'Prefer Google Calendar?', sub: 'Book into Google instead.' },
      ],
    },
    ctaHeading: 'Answer every call, book into Square.',
    ctaSub: 'Connect Square Appointments and let your AI receptionist book the calls you can’t pick up — in under 10 minutes.',
  },
  {
    slug: 'hubspot',
    name: 'HubSpot CRM',
    emoji: '🧡',
    eyebrow: 'CRM integration',
    metaTitle: 'AI Receptionist + HubSpot CRM Sync — Open Lines',
    metaDescription: 'Open Lines logs every call to HubSpot — creating or updating the contact and adding an AI-generated call summary as a note. Free 7-day trial.',
    h1: 'Every call, logged to HubSpot automatically.',
    subhead: 'After Open Lines answers a call, it creates or updates the contact in HubSpot and adds an AI-generated summary as a note — caller details, urgency, and the suggested next step — so your CRM is always current without anyone typing it up.',
    whatHeading: 'What the HubSpot integration does',
    what: 'Connect HubSpot once and every answered call flows into your CRM. Open Lines matches or creates the contact, then attaches a structured note with the call summary, the caller’s details, how urgent it was, and what to do next — so your pipeline reflects reality without manual data entry.',
    steps: [
      { title: 'Connect HubSpot', body: 'Authorize Open Lines from your dashboard in a couple of clicks. No CSV imports, no manual mapping.' },
      { title: 'A call comes in and gets answered', body: 'Open Lines handles the call, captures the caller’s details, and writes an AI summary.' },
      { title: 'HubSpot updates itself', body: 'The contact is created or updated and the call summary is added as a note — automatically.' },
    ],
    benefits: [
      { icon: '🧠', title: 'No manual data entry', body: 'Every call becomes a contact and a structured note in HubSpot without anyone typing it up.' },
      { icon: '🎯', title: 'Context on every lead', body: 'Summary, urgency, and suggested next step are attached so follow-up is fast and informed.' },
      { icon: '📈', title: 'A pipeline that reflects reality', body: 'Phone leads land in HubSpot the moment the call ends, so nothing slips through the cracks.' },
    ],
    faqs: [
      { q: 'What gets sent to HubSpot after a call?', a: 'Open Lines creates or updates the contact and adds an AI-generated call summary as a note — including the caller’s details, how urgent the matter was, and the suggested next step.' },
      { q: 'Does it create a new contact or update an existing one?', a: 'It matches existing contacts where it can and creates a new one when the caller is unknown, so you don’t end up with duplicates for repeat callers.' },
      { q: 'How do I connect HubSpot?', a: 'From your Open Lines dashboard, connect HubSpot and authorize access. It takes a couple of clicks.' },
      { q: 'Is HubSpot sync on every plan?', a: 'CRM sync is available on the paid plans. You can start a free trial and connect it from your dashboard.' },
    ],
    unique: {
      heading: 'How the HubSpot sync works',
      points: [
        { title: 'Contact matching & de-duplication', body: 'It matches the caller to an existing contact by phone or email where it can, and only creates a new one when they’re genuinely unknown — so repeat callers don’t spawn duplicates.' },
        { title: 'What lands on the note', body: 'Each call becomes a note with the AI summary, the caller’s details, the urgency, and the suggested next step — the same structure every time, so your pipeline reads consistently.' },
        { title: 'Create vs. update, decided for you', body: 'Known caller → the contact is updated and the note appended. New caller → a fresh contact is created with the first note attached.' },
      ],
    },
    related: {
      industries: [
        { href: '/realtors', label: 'AI receptionist for real estate', sub: 'Pushes qualified leads to HubSpot.' },
        { href: '/insurance', label: 'AI receptionist for insurance', sub: 'Logs quote and claim intake to HubSpot.' },
        { href: '/contractors', label: 'AI receptionist for contractors', sub: 'Logs project leads to HubSpot.' },
      ],
      integrations: [
        { href: '/integrations/slack', label: 'Add Slack alerts', sub: 'Get every call in your channel too.' },
        { href: '/integrations/google-calendar', label: 'Book into Google Calendar', sub: 'Log the call and book the meeting.' },
      ],
    },
    ctaHeading: 'Keep HubSpot current, automatically.',
    ctaSub: 'Connect HubSpot and let every call log itself — contact, summary, and next step — in under 10 minutes.',
  },
  {
    slug: 'slack',
    name: 'Slack',
    emoji: '💬',
    eyebrow: 'Notifications integration',
    metaTitle: 'AI Receptionist Slack Notifications — Open Lines',
    metaDescription: 'Get a Slack message after every call — caller details, urgency, AI summary, and next step, delivered to any channel. Free 7-day trial.',
    h1: 'Every call, in your Slack channel — instantly.',
    subhead: 'After Open Lines answers a call, it posts a clean message to the Slack channel you choose: who called, how urgent it was, an AI summary, and the suggested next step. One message per call — no noise, no transcripts to wade through.',
    whatHeading: 'What the Slack integration does',
    what: 'Connect Slack once and pick a channel. Every time Open Lines answers a call, your team gets a single, tidy message with the caller’s name and number, the urgency, an AI-written summary, and what to do next — so the whole team stays in the loop the moment a call ends.',
    steps: [
      { title: 'Connect Slack', body: 'Authorize Open Lines from your dashboard and choose the channel you want call updates in.' },
      { title: 'A call comes in and gets answered', body: 'Open Lines handles the call and writes a short, structured summary.' },
      { title: 'Your channel gets the message', body: 'A single Slack message lands with caller details, urgency, summary, and next step.' },
    ],
    benefits: [
      { icon: '⚡', title: 'Real-time visibility', body: 'The whole team sees every call the moment it ends, right where they already work.' },
      { icon: '🎯', title: 'Signal, not noise', body: 'One clean message per call — caller, urgency, summary, next step — with no transcripts to scroll.' },
      { icon: '📣', title: 'Any channel you choose', body: 'Route call updates to a front-desk, sales, or on-call channel — wherever your team lives.' },
    ],
    faqs: [
      { q: 'What does the Slack message include?', a: 'Each message has the caller’s name and phone, how urgent the call was, an AI-generated summary, and the suggested next step — one message per call.' },
      { q: 'Can I choose which channel it posts to?', a: 'Yes. When you connect Slack you pick the channel, so call updates land wherever your team already works.' },
      { q: 'Will it flood my channel?', a: 'No. It’s deliberately one tidy message per call, with no transcripts — just the details your team needs at a glance.' },
      { q: 'How do I connect Slack?', a: 'From your Open Lines dashboard, connect Slack, authorize access, and choose your channel. It takes a couple of clicks.' },
    ],
    unique: {
      heading: 'How the Slack notifications work',
      points: [
        { title: 'You pick the channel', body: 'Choose the channel when you connect — front desk, sales, or on-call — and every call update posts exactly there.' },
        { title: 'The anatomy of one message', body: 'Caller name and number, an urgency tag, the AI summary, and the suggested next step — one tidy message, no transcripts to scroll.' },
        { title: 'Signal, not noise', body: 'It’s deliberately one message per call, so the channel stays useful instead of turning into a firehose.' },
      ],
    },
    related: {
      industries: [
        { href: '/realtors', label: 'AI receptionist for real estate', sub: 'Hot-lead alerts straight to Slack.' },
        { href: '/courier', label: 'AI receptionist for couriers', sub: 'New orders posted to dispatch.' },
      ],
      integrations: [
        { href: '/integrations/hubspot', label: 'Add HubSpot CRM', sub: 'Log the call as well as ping Slack.' },
        { href: '/integrations/google-calendar', label: 'Book into Google Calendar', sub: 'Notify and book in one flow.' },
      ],
    },
    ctaHeading: 'Bring every call into Slack.',
    ctaSub: 'Connect Slack and keep your whole team in the loop on every call — in under 10 minutes.',
  },
  {
    slug: 'stripe',
    name: 'Stripe',
    emoji: '💳',
    eyebrow: 'Payments integration',
    metaTitle: 'AI Receptionist that Takes Deposits with Stripe — Open Lines',
    metaDescription: 'Cut no-shows: Open Lines texts a secure Stripe payment link to collect a deposit when it books an appointment. Free 7-day trial.',
    h1: 'Take deposits on the call — powered by Stripe.',
    subhead: 'When Open Lines books an appointment, it can text the caller a secure Stripe payment link to collect a deposit — so the bookings that used to no-show are paid for before anyone walks in.',
    whatHeading: 'What the Stripe integration does',
    what: 'Connect Stripe once and Open Lines can collect a deposit at the point of booking. After it takes the appointment, it texts the caller a secure Stripe link; the caller pays in a tap, and the payment settles into your own Stripe account. It’s the simplest way to protect your calendar from no-shows.',
    steps: [
      { title: 'Connect Stripe', body: 'Link your Stripe account from your dashboard in a couple of clicks and set your deposit amount.' },
      { title: 'The AI books and requests a deposit', body: 'When it books the appointment, it texts the caller a secure Stripe payment link.' },
      { title: 'The deposit is paid before they arrive', body: 'The caller pays in a tap and the funds settle into your own Stripe account.' },
    ],
    benefits: [
      { icon: '🛡️', title: 'Fewer no-shows', body: 'A paid deposit means the booking is real — the calendar slots you lose to no-shows get protected.' },
      { icon: '🔗', title: 'Secure, tap-to-pay link', body: 'The caller gets a secure Stripe link by text and pays in seconds — no card details taken over the phone.' },
      { icon: '🏦', title: 'Straight to your account', body: 'Deposits settle into your own Stripe account, so the money is yours from the moment it’s paid.' },
    ],
    faqs: [
      { q: 'How does it collect the deposit?', a: 'When Open Lines books an appointment, it texts the caller a secure Stripe payment link. The caller pays in a tap — no card details are read out over the phone.' },
      { q: 'Where does the money go?', a: 'Deposits settle directly into your own connected Stripe account.' },
      { q: 'Can I set the deposit amount?', a: 'Yes. You set your deposit amount in the dashboard, and Open Lines requests it when it books.' },
      { q: 'Is taking deposits on every plan?', a: 'Deposit collection is available on eligible paid plans. You can start a free trial and connect Stripe from your dashboard.' },
    ],
    unique: {
      heading: 'How the Stripe deposit flow works',
      points: [
        { title: 'Deposit requested at booking', body: 'When it books the appointment, it texts the caller a secure Stripe link for the deposit amount you set — no card details are ever read out over the phone.' },
        { title: 'Refunds & cancellations', body: 'Because deposits sit in your own Stripe account, cancellations and refunds are handled with your normal Stripe controls and policy.' },
        { title: 'If a payment doesn’t complete', body: 'The booking still comes through with the deposit marked unpaid, so you can decide whether to hold, follow up, or release the slot.' },
      ],
    },
    related: {
      industries: [
        { href: '/salons', label: 'AI receptionist for salons', sub: 'Deposits to protect the chair.' },
        { href: '/contractors', label: 'AI receptionist for contractors', sub: 'Deposits to hold the job.' },
        { href: '/restaurants', label: 'AI receptionist for restaurants', sub: 'Deposits on large parties.' },
      ],
      integrations: [
        { href: '/integrations/square-appointments', label: 'On Square?', sub: 'Deposits alongside Square bookings.' },
        { href: '/integrations/google-calendar', label: 'Book into Google Calendar', sub: 'Take the deposit and the booking.' },
      ],
    },
    ctaHeading: 'Protect your calendar from no-shows.',
    ctaSub: 'Connect Stripe and let your AI receptionist collect deposits at the point of booking — in under 10 minutes.',
  },
]

export const INTEGRATION_SLUGS = INTEGRATIONS.map(i => i.slug)

export function getIntegration(slug: string): IntegrationContent | undefined {
  return INTEGRATIONS.find(i => i.slug === slug)
}
