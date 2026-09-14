import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For US Businesses', title: 'Every call answered, in every time zone.', benefit: 'A local number in your area code, live the same day.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for US Businesses | Open Lines',
  description: 'A local US number with no document checks and no waiting — answering calls and booking into your calendar the same day. State recording laws handled by disclosing on every call.',
  alternates: { canonical: '/united-states' },
  openGraph: {
    title: 'AI Receptionist for US Businesses',
    description: 'Local numbers in your area code, answering and booking from the day you sign up.',
    url: 'https://www.openlines.ai/united-states',
    images: [OG],
  },
}

const UNITED_STATES: VerticalContent = {
  slug: 'united-states',
  name: 'AI Receptionist for US Businesses',
  shortName: 'United States',
  eyebrow: 'For US Businesses',
  h1: 'Every call answered, in every time zone you sell into.',
  subhead:
    'A local number in your own area code, issued immediately with no documents to submit. It answers, checks your real availability, and books the appointment while the caller is still on the phone.',
  trustline: 'Local numbers issued immediately · Disclosure on every call · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'Where US businesses lose calls',
  painsHeading: 'The calls that go to the next listing',
  pains: [
    { stat: '3 hrs', title: 'Coast-to-coast is a staffing problem', body: 'A five o’clock call in New York is two in Los Angeles. Any business selling beyond its own zone has hours where customers are awake and nobody is answering.' },
    { stat: '1 tap', title: 'Map results dial instantly', body: 'Somebody searching on a phone taps the first listing, and taps the next one just as easily. These are your highest-intent callers and your least loyal.' },
    { stat: '50 states', title: 'Recording rules that vary by state', body: 'Some states require every party to consent, not just one. A business taking calls across state lines cannot reason about this caller by caller.' },
  ],

  solutionLabel: 'What it does',
  solutionHeading: 'Answers, books, and keeps the record straight',
  solutionSub: 'Not an answering service taking messages. It reads live availability and writes the appointment into the calendar your staff already work from.',
  features: [
    { icon: '📍', title: 'Your own area code', body: 'A 212, a 312, a 415 — or keep the number already printed on your trucks and forward it. Customers dial what they have always dialled.' },
    { icon: '🌎', title: 'Covers every zone at once', body: 'The same arrangement answers a seven a.m. call in Boston and a seven p.m. one in Seattle, without anybody being scheduled for either.' },
    { icon: '📅', title: 'Books into your calendar', body: 'Google Calendar, Outlook or Square Appointments. The slot is written in as it is offered, so the next caller cannot be given it.' },
    { icon: '⚖️', title: 'Disclosure on every call', body: 'Callers are told at the start that the call is handled by an automated assistant and that it is recorded — which is also the practical answer to two-party-consent states.' },
  ],

  setup: {
    heading: 'What is different about setting up in the US',
    intro: 'The US is among the fastest countries to start in, because nothing has to be approved before a number can be issued. The considerations that remain are about what is said on the call rather than about paperwork.',
    points: [
      { title: 'No documents, no review', body: 'US local numbers carry no supporting-document requirement, so there is nothing to submit and no queue. Compare Ireland, where documents must be reviewed before any number exists.' },
      { title: 'Two-party consent, handled by default', body: 'States differ on whether one party or all parties must consent to a recording. Disclosing at the start of every call is the approach that holds in the strictest of them, so it is what happens on all of them.' },
      { title: 'Saying it is an AI, early', body: 'Several states now regulate automated callers, and the wording differs. Telling people plainly in the opening seconds satisfies the intent of all of them and is what stops callers feeling misled anyway.' },
      { title: 'This is not legal advice', body: 'State law varies and changes. If you operate somewhere with specific obligations — healthcare, finance, collections — that is a conversation with your own counsel rather than something to infer from a marketing page.' },
    ],
  },

  intake: {
    heading: 'What it takes down on a US call',
    fields: ['Caller’s name', 'Number they are calling from', 'What they need', 'City or ZIP, where it matters', 'When they are available', 'Whether they are an existing customer'],
  },

  demoMock: { name: 'Marcus Webb', service: 'Estimate visit', when: 'Tuesday 9:00 AM', with: 'Dave' },
  textback: { business: 'Sorry we missed you — this is Open Lines answering for Ridgeline HVAC.', reply: 'Need someone out this week if possible' },

  integrationsHeading: 'Works with what you already use',
  integrations: ['Google Calendar', 'Outlook & Microsoft 365', 'Square Appointments', 'HubSpot', 'Slack', 'Stripe'],

  faqs: [
    { q: 'How quickly can a US business get a number?', a: 'The same day. US local numbers carry no supporting-document requirement, so there is nothing to submit and no review to wait on.' },
    { q: 'Can I get a number in my own area code?', a: 'Yes. Ask for the area code during setup if looking local matters to you — or keep the number already on your trucks and forward it instead.' },
    { q: 'What about two-party consent states?', a: 'Every caller is told at the start that the call is handled by an automated assistant and is recorded. That approach holds in the strictest states, so it is used in all of them.' },
    { q: 'Do I have to tell callers it is an AI?', a: 'Several states regulate automated callers and the wording differs. Disclosing plainly in the opening seconds satisfies the intent of all of them, and is what prevents callers feeling misled regardless.' },
    { q: 'Does it handle calls across time zones?', a: 'That is one of the stronger reasons to use it. The same arrangement answers a seven a.m. call on the east coast and a seven p.m. one on the west, with nobody scheduled for either.' },
    { q: 'Is this legal advice?', a: 'No. State law varies and changes, and if you operate in a regulated field the specifics belong with your own counsel rather than with a marketing page.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/google-calendar', label: 'Book into Google Calendar', sub: 'One diary, one copy.' },
      { href: '/integrations/outlook', label: 'Outlook & Microsoft 365', sub: 'Shared and room calendars.' },
    ],
    guides: [
      { href: '/learn/call-recording-consent', label: 'Recording consent', sub: 'What has to be said.' },
      { href: '/learn/disclosing-ai-to-callers', label: 'Disclosing the AI', sub: 'Why early is easier.' },
      { href: '/learn/your-google-listing-and-your-phone', label: 'Calls from map results', sub: 'Your highest-intent callers.' },
    ],
  },

  ctaHeading: 'Answering US calls today, not next week.',
  ctaSub: 'A local number in your area code, no documents, no queue. Seven days free.',
}

export default function UnitedStatesPage() {
  return <VerticalLanding content={UNITED_STATES} />
}
