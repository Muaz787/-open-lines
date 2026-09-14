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
  /** A real screenshot or mark for this integration, when we have one worth
   *  showing. Optional: a placeholder would be worse than nothing on a page
   *  whose job is to be believed. */
  hero?: { src: string; alt: string; width: number; height: number }
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
    subhead: 'One calendar, one copy, no new system to check. Open Lines reads the same Google Calendar you already live in and writes the appointment into it while the caller is still on the phone.',
    whatHeading: 'What the Google Calendar integration does',
    what: 'Google Calendar suits businesses that run on one diary rather than a booking system — a few people, a shared view, and whatever anyone has blocked out. Open Lines treats that diary as the single source of truth: it reads what is genuinely free at the moment a caller asks, and writes the appointment in as an ordinary event. There is no second calendar to reconcile, because there is only ever one copy.',
    steps: [
      { title: 'Sign in with Google', body: 'An ordinary Google authorisation from your dashboard. No plugin to install and nobody’s permission to ask for.' },
      { title: 'Everything in the diary counts', body: 'A school run, a supplier meeting, a block you added yourself — each one makes that time unofferable.' },
      { title: 'It appears where you already look', body: 'On the phone in your pocket, in the view your team already has open, with the caller’s details attached.' },
    ],
    benefits: [
      { icon: '⚡', title: 'No gap between promise and record', body: 'The slot is written down in the same moment it is offered, which is what actually prevents a double booking.' },
      { icon: '🔄', title: 'One diary, not two', body: 'Nothing to keep in sync and no booking calendar to remember to check, because the appointment lives in the only calendar you have.' },
      { icon: '🧩', title: 'Your own blocks are respected', body: 'Personal commitments in the same calendar protect your time automatically — which is the argument for keeping them there.' },
    ],
    faqs: [
      { q: 'Which calendar does it book into?', a: 'Your primary Google Calendar — the one your phone already shows. There is no separate booking calendar to keep an eye on.' },
      { q: 'Will it book over something already in my diary?', a: 'No. Anything in your calendar makes that time unavailable, including personal blocks you added yourself.' },
      { q: 'Can I stop it offering evenings and early mornings?', a: 'Yes. It offers times inside the working hours you set, rather than any gap that happens to be empty.' },
      { q: 'Does it need access to my whole Google account?', a: 'It asks for calendar access, and you can see exactly what was granted in your Google account’s security settings at any time.' },
      { q: 'How do I revoke access?', a: 'From your Open Lines dashboard, or directly in your Google account alongside every other connected app. It takes effect immediately.' },
      { q: 'Does the customer get a calendar invitation?', a: 'The appointment is created in your calendar with their details, and they receive a confirmation from Open Lines by text or email.' },
    ],
    unique: {
      heading: 'How the Google Calendar booking works',
      points: [
        { title: 'It books into your primary calendar', body: 'The same calendar your phone already shows. There is no separate booking calendar to check, and nothing to keep in sync, because there is only ever one copy.' },
        { title: 'Existing events block the slot', body: 'Anything already in your calendar makes that time unavailable — a school run, a supplier meeting, a block you added yourself. The assistant cannot offer a time you have already spoken for.' },
        { title: 'Your working hours are respected', body: 'It offers times inside the hours you set rather than any gap in the day, so nobody gets booked in at seven in the morning because the calendar happened to be empty.' },
        { title: 'Revoking access is immediate', body: 'The connection is an ordinary Google authorisation, visible in your Google account alongside every other app, and removable from there at any time without contacting anyone.' },
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
    subhead: 'Built for diaries other people write into. Open Lines reads free/busy across your Microsoft 365 tenant — including meetings colleagues put in your calendar — and books inside the rules your administrator already set.',
    whatHeading: 'What the Outlook integration does',
    what: 'Outlook is rarely one person’s diary. Colleagues send invitations, appointments sit in shared mailboxes, rooms have calendars of their own, and an IT administrator decides what any application may do. Open Lines works inside that: it authorises through your own Microsoft account, reads free/busy rather than copying anything out, and creates an ordinary calendar item your organisation can forward, edit and govern like every other meeting.',
    steps: [
      { title: 'Authorise through your own account', body: 'Whatever your tenant requires applies — if your organisation asks administrators to approve new applications, yours approves it once.' },
      { title: 'Invitations block time too', body: 'A meeting a colleague put in your diary makes that hour unavailable exactly as one you created does.' },
      { title: 'It lands where your team books', body: 'An individual diary, a shared mailbox or a room calendar — wherever your colleagues already look.' },
    ],
    benefits: [
      { icon: '⚡', title: 'Free/busy, not a copy', body: 'Availability is read at the moment of the call. Nothing about your diary is exported or held elsewhere to make booking work.' },
      { icon: '🔄', title: 'An ordinary calendar item', body: 'It syncs to phones, shows in Teams, and can be forwarded or amended by anyone who would normally amend a meeting.' },
      { icon: '🧩', title: 'Your administrator stays in charge', body: 'Conditional access, retention and sharing limits continue to apply. Connecting a phone line does not create an exception to them.' },
    ],
    faqs: [
      { q: 'Does it work with Microsoft 365 and Exchange?', a: 'Yes. You authorise it from your own Microsoft account and it reads the calendar that account can see — whether that is a personal mailbox, a shared one, or a room.' },
      { q: 'Will it see meetings other people put in my diary?', a: 'Yes. It reads free/busy, so an invitation you accepted blocks that time just as an appointment you created does.' },
      { q: 'Can it book into a shared or room calendar?', a: 'Yes, if the account you connect has access to it. Teams that already book into a shared mailbox keep doing exactly that.' },
      { q: 'Does our IT administrator need to approve it?', a: 'That depends on your tenant. Some organisations require admin consent for new applications; if yours does, your administrator approves it once.' },
      { q: 'Is anything copied out of Microsoft 365?', a: 'No. Availability is read at the moment of the call and the booking is written back. The calendar remains the only copy.' },
      { q: 'How do I disconnect it?', a: 'From your Open Lines dashboard, or by revoking the application in your Microsoft account. Either stops it immediately.' },
    ],
    unique: {
      heading: 'How the Outlook booking works',
      points: [
        { title: 'It reads free/busy, not just your diary', body: 'Microsoft 365 exposes free/busy across your organisation, so the assistant can see that a slot is genuinely clear before offering it — including time blocked by meetings you were invited to rather than ones you created.' },
        { title: 'Shared and room calendars', body: 'Teams that book into a shared mailbox or a room calendar rather than an individual one keep doing exactly that; the appointment lands where your colleagues already look.' },
        { title: 'Your tenant, your rules', body: 'The connection is authorised through your own Microsoft account, so whatever your administrator has set — conditional access, retention, sharing limits — continues to apply. Nothing is copied out of Microsoft 365 to make booking work.' },
        { title: 'Invitations behave normally', body: 'A booked appointment is an ordinary calendar item. It syncs to phones, shows in Teams, and can be forwarded or edited by your team like anything else in the diary.' },
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
    hero: {
      src: '/integrations/open-lines-square-appointments.png',
      // Describes what the image SHOWS. Alt text is read by screen readers and
      // by crawlers building an idea of what this page is about, and "logo" or
      // "image" tells both of them nothing.
      alt: 'Open Lines connected to Square — the Open Lines mark linked to the Square logo',
      width: 1200, height: 513,
    },
    eyebrow: 'Booking integration',
    metaTitle: 'AI Receptionist for Square Appointments — Open Lines',
    metaDescription: 'Open Lines answers your phone and books into Square Appointments using your live availability — the right service, the right team member, and the right location if you have several. Cancels and reschedules by phone too. Free 7-day trial.',
    h1: 'An AI receptionist that books into Square Appointments.',
    subhead: 'Open Lines answers every call, reads your live Square Appointments availability, and books the right service into your Square calendar — so the bookings you can’t pick up still land in the system you already run.',
    whatHeading: 'What the Square Appointments integration does',
    what: 'Connect your Square account once and Open Lines reads your real Square Appointments availability before offering a caller a time. When the caller confirms, the appointment is booked into your Square calendar — the same place your walk-ins and online bookings live. It books the right service, with a specific team member when the caller asks for one, and at the right branch if you run more than one. It can also cancel and move existing appointments by phone.',
    steps: [
      { title: 'Connect your Square account', body: 'Authorize Open Lines from your dashboard in a couple of clicks. Your services, team members and locations come across automatically.' },
      { title: 'The AI checks real availability', body: 'On every call it reads your live Square availability — for the service asked for, the team member requested, and the branch the caller wants.' },
      { title: 'The booking lands in Square', body: 'Once the caller confirms, the appointment is written to your Square Appointments calendar against a real Square customer record.' },
    ],
    benefits: [
      { icon: '⚡', title: 'Live Square availability', body: 'Reads your real Square Appointments calendar and books only open slots — no clashes with existing bookings.' },
      { icon: '📍', title: 'Knows which branch', body: 'Run more than one location? The caller says which, and availability and the booking are scoped to that branch.' },
      { icon: '🗂️', title: 'One source of truth', body: 'Phone bookings land in the same Square calendar as your walk-ins and online bookings.' },
      { icon: '🔁', title: 'Cancels and moves too', body: 'Callers can cancel or reschedule an existing appointment on the phone, without reaching anyone.' },
      { icon: '👤', title: 'Asks for a person by name', body: 'If a caller wants a particular stylist, barber or practitioner, it books that person’s real availability.' },
      { icon: '🧩', title: 'No new software', body: 'Keep running Square exactly as you do. Open Lines just answers the phone and books into it.' },
    ],
    faqs: [
      { q: 'Does it book into my real Square calendar?', a: 'Yes. Open Lines reads your live Square Appointments availability and books confirmed appointments straight into your Square calendar — the same place your walk-ins and online bookings live.' },
      { q: 'Does it work if I have more than one location?', a: 'Yes. With two or more Square locations connected and switched on, the caller says which branch they want and both the availability check and the booking are scoped to it. If it is not clear which branch they mean, the AI asks by name — it never picks one for them.' },
      { q: 'Can a caller ask for a specific stylist, barber or practitioner?', a: 'Yes. Your Square team members come across when you connect, so if a caller asks for someone by name the AI checks that person’s real availability and books the appointment with them.' },
      { q: 'Can callers cancel or reschedule on the phone?', a: 'Both. The AI can cancel an appointment, and can move one to a new time for the same service at the same branch. Moving an appointment to a different location is not automated — it will tell the caller the team will arrange that rather than cancelling and rebooking to imitate a move.' },
      { q: 'Will it create duplicate customers in Square?', a: 'No. A caller is matched to their existing Square customer record by phone number and the booking attaches to that customer. Someone calling for the first time gets a new customer record created.' },
      { q: 'Do my services come across?', a: 'Yes. When you connect your Square account, your service list and availability are used so the AI books the right service at a time you can actually take.' },
      { q: 'Does it double-book?', a: 'It reads your live Square availability before offering any time, so it only offers slots that are genuinely open. Bookings made elsewhere — online, in person, by another staff member — are already reflected, because it is reading the same calendar.' },
      { q: 'How do I connect Square?', a: 'From your Open Lines dashboard, connect your Square account and authorize access. It takes a couple of clicks, then your services, team and locations sync across.' },
      { q: 'Can it also take deposits?', a: 'Yes — on Pro and Business plans Open Lines can text a secure payment link to collect a deposit and cut no-shows, alongside the Square booking.' },
      { q: 'Do I need Square Appointments specifically, or just Square?', a: 'Square Appointments, since that is where the bookable calendar, services and team members live. If you use Square only for payments, Open Lines can still take deposits — but it will need Google Calendar or Outlook to book into.' },
    ],
    unique: {
      heading: 'How the Square Appointments booking works',
      points: [
        { title: 'Your services and team come across', body: 'When you connect Square, your service list, team members and availability are used — so the AI books the right service, with the right person, at a time you can actually take.' },
        { title: 'More than one location', body: 'If you run several branches, the caller says which one they want and both the availability check and the booking are scoped to it. When it is not clear which they mean, the AI asks by name rather than guessing.' },
        { title: 'Returning callers are recognised', body: 'A caller is matched to their existing Square customer record by phone number, so their booking attaches to the same customer rather than creating a duplicate. A new caller gets a customer record created.' },
        { title: 'Cancelling and rescheduling', body: 'Callers can cancel, or move an appointment to a new time for the same service at the same branch. Moving between locations is deliberately not automated — the AI says the team will arrange it rather than cancelling and rebooking to imitate a move.' },
        { title: 'Deposits alongside the booking', body: 'On eligible plans it can text a secure payment link to take a deposit at the same time it books, cutting no-shows.' },
      ],
    },
    related: {
      industries: [
        { href: '/salons', label: 'AI receptionist for salons', sub: 'Books the right stylist into Square.' },
        { href: '/barbers', label: 'AI receptionist for barbershops', sub: 'Books the right barber into Square.' },
        { href: '/multi-location', label: 'Running several branches?', sub: 'One line, booked into the right location.' },
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
      { q: 'Does it create a new contact or update an existing one?', a: 'It looks the caller’s number up against the phone property on your contacts. A match updates that contact and appends the note; no match creates a new contact with the first note attached.' },
      { q: 'Why did it create a duplicate for someone already in HubSpot?', a: 'Almost always number formatting. The lookup is an exact match, so 07700 900123 and +447700900123 are different strings. Records imported in mixed formats are worth standardising before you connect.' },
      { q: 'Does it match on email as well?', a: 'No. A phone call gives you a number reliably and an email address only if the caller volunteers one, so the number is what the matching uses.' },
      { q: 'Will it overwrite details already on the contact?', a: 'It adds the call as a note and fills in what was missing. The history you already hold on that contact stays where it is.' },
      { q: 'How do I connect HubSpot?', a: 'From your Open Lines dashboard, connect HubSpot and authorize access. It takes a couple of clicks.' },
      { q: 'Is HubSpot sync on every plan?', a: 'CRM sync is available on the paid plans. You can start a free trial and connect it from your dashboard.' },
    ],
    unique: {
      heading: 'How the HubSpot sync works',
      points: [
        { title: 'Matched on the number they rang from', body: 'The caller’s number is looked up against the phone property on your contacts. A match updates that person; no match creates them. It is the only identifier a phone call reliably gives you, so it is the one used.' },
        { title: 'Why number formatting matters', body: 'The lookup is an exact match, so a contact stored as 07700 900123 is not the same string as +447700900123 and will not be found. If your existing records were imported in mixed formats you may see a second contact created for somebody already in HubSpot — worth a tidy-up before you connect, rather than after.' },
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
      { q: 'Who in the channel can see caller details?', a: 'Everybody in it — a channel post is visible to its members, so a private channel is the sensible home for anything naming customers rather than a general one the whole company sits in.' },
      { q: 'What happens if Slack is down or the channel is archived?', a: 'The alert not arriving never affects the call. Slack is a notification route rather than the record — the summary is kept regardless, so nothing is lost if a message fails to post.' },
      { q: 'How do I connect Slack?', a: 'From your Open Lines dashboard, connect Slack, authorize access, and choose your channel. It takes a couple of clicks.' },
    ],
    unique: {
      heading: 'What lands in Slack, and what it changes',
      points: [
        { title: 'The summary, not the transcript', body: 'A short account of who called, what they wanted and what happened — short enough to read in the channel without opening anything. The full transcript stays in the dashboard for the rare call that needs it.' },
        { title: 'The urgent ones stand out', body: 'A call flagged as urgent reads differently in the channel, so someone can pick it up without reading every message in order.' },
        { title: 'It ends the forwarding habit', body: 'Teams without this forward voicemails and screenshots to each other. One channel that every call reaches removes the step where a message sits in one person’s inbox while they are out.' },
        { title: 'Nobody has to be watching', body: 'A call at 9pm is in the channel in the morning, in order, with everything needed to act on it — rather than a voicemail icon and a guess about what it was.' },
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
      { q: 'What if the caller never pays the deposit?', a: 'That is yours to decide in advance: hold the slot for a set period, or release it if the payment does not arrive. Whichever you choose, the appointment and the payment are visible together so you are not reconciling two systems.' },
      { q: 'Does this affect the card fees I already pay?', a: 'It is an ordinary charge through your own Stripe account, so your existing rates and payout schedule apply exactly as they do for payments you take any other way.' },
      { q: 'Is taking deposits on every plan?', a: 'Deposit collection is available on eligible paid plans. You can start a free trial and connect Stripe from your dashboard.' },
    ],
    unique: {
      heading: 'How the deposit actually works',
      points: [
        { title: 'A link by text, never card details by voice', body: 'The caller receives a secure Stripe payment link and pays on their own phone. Card numbers are never spoken aloud, never transcribed, and never stored by us.' },
        { title: 'Taken while they are still committed', body: 'The link goes out during the booking call, when the customer has just chosen a time — not the next day, when the moment has passed and someone has to chase.' },
        { title: 'It lands in your own Stripe account', body: 'Payouts, refunds and disputes stay where your accountant already looks. Open Lines does not hold the money at any point.' },
        { title: 'You choose when it applies', body: 'Set an amount and whether the deposit is required to confirm, so a long or high-value appointment can require one while a quick job does not.' },
        { title: 'Refunds follow your policy, not ours', body: 'Cancellation terms are yours to set and yours to apply. The assistant tells the caller what they are; it does not decide them.' },
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
