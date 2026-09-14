import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For Canadian Businesses', title: 'A Canadian number, answering calls today.', benefit: 'No verification queue. No documents. Live the same afternoon.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Canadian Businesses | Open Lines',
  description: 'A local Canadian number with no document checks and no waiting — answering calls and booking into your calendar the same day. PIPEDA-aware disclosure built in.',
  alternates: { canonical: '/canada' },
  openGraph: {
    title: 'AI Receptionist for Canadian Businesses',
    description: 'Local Canadian numbers, no verification queue, calls answered the same day you sign up.',
    url: 'https://www.openlines.ai/canada',
    images: [OG],
  },
}

const CANADA: VerticalContent = {
  slug: 'canada',
  name: 'AI Receptionist for Canadian Businesses',
  shortName: 'Canada',
  eyebrow: 'For Canadian Businesses',
  h1: 'A Canadian number, answering calls this afternoon.',
  subhead:
    'No documents to submit and no review to wait on. Canadian local numbers are issued immediately, so the gap between deciding and having your phone answered is measured in minutes rather than working days.',
  trustline: 'Local numbers issued immediately · GST/HST on the invoice · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'Where Canadian businesses lose calls',
  painsHeading: 'The calls that never reach you',
  pains: [
    { stat: 'Same day', title: 'No regulatory queue', body: 'Some countries require documents and a review before a number can be issued. Canada does not, which is why a Canadian business can be answering calls the afternoon it signs up.' },
    { stat: '4 zones', title: 'A country six hours wide', body: 'A Halifax business takes calls while Vancouver sleeps and loses them the other way. Nothing staffed to one time zone covers a national customer base.' },
    { stat: 'Winter', title: 'The days nobody gets in', body: 'A storm closes the office and the phone does not know. Calls keep arriving, and the calendar keeps offering a day you will not be open.' },
  ],

  solutionLabel: 'What it does',
  solutionHeading: 'Answers, books, and tells you what happened',
  solutionSub: 'Not a message service. It reads your real availability and writes the appointment into the calendar you already use.',
  features: [
    { icon: '📍', title: 'A real local number', body: 'Choose a number in your own area code — Toronto, Montreal, Calgary, Vancouver — or keep the number you already have and forward it.' },
    { icon: '📅', title: 'Books into your calendar', body: 'Google Calendar, Outlook or Square Appointments. The slot is written in as it is offered, so it is genuinely gone for the next caller.' },
    { icon: '🔔', title: 'Tells you what was said', body: 'A summary of every call by email or text, so you know what happened without listening to anything.' },
    { icon: '🧾', title: 'Billed the way a Canadian supplier bills', body: 'Sales tax at your province’s rate, itemised on the invoice, recoverable in the ordinary way if you are registered. No cross-border paperwork to reconcile.' },
  ],

  setup: {
    heading: 'Why Canada is the fastest country to start in',
    intro: 'Not every country works this way, and the contrast is sharper than most people expect. What follows is about getting a line working — the privacy and tax detail has a guide of its own.',
    points: [
      { title: 'Nothing to submit, nothing to approve', body: 'Canadian local numbers carry no supporting-document requirement at the carrier. There is no bundle to assemble and no review to sit behind, which is why the wait is minutes rather than working days.' },
      { title: 'Ireland, by contrast, cannot do this', body: 'An Irish business must satisfy a regulator before a line exists at all. Worth knowing if you are planning both — start the Irish one first and let it run while everything else is set up.' },
      { title: 'Pick the area code that makes you look local', body: 'A 416 reads differently from a toll-free number to somebody in Toronto. If where you appear to be matters to your customers, choose deliberately rather than taking what comes.' },
      { title: 'One line covering four and a half time zones', body: 'A national customer base means calls arriving when your office is shut at one end of the country and busy at the other. Nothing rostered to one zone covers both ends.' },
    ],
  },

  intake: {
    heading: 'What it takes down on a Canadian call',
    fields: ['Caller’s name', 'Number they are calling from', 'What they need', 'Which location, if you have more than one', 'When they are available', 'Whether they have been to you before'],
  },

  demoMock: { name: 'Priya Raman', service: 'Consultation', when: 'Thursday 2:30 PM', with: 'Daniel' },
  textback: { business: 'Sorry we missed you — this is Open Lines answering for Northside Auto.', reply: 'Can you fit me in Thursday?' },

  integrationsHeading: 'Works with what you already use',
  integrations: ['Google Calendar', 'Outlook & Microsoft 365', 'Square Appointments', 'HubSpot', 'Slack', 'Stripe'],

  faqs: [
    { q: 'How quickly can a Canadian business get a number?', a: 'The same day. Canadian local numbers carry no supporting-document requirement at the carrier, so there is nothing to assemble and no review to sit behind.' },
    { q: 'Can I keep the number I already have?', a: 'Yes, and it is usually the better choice. Forward it, and the number on your van, your invoices and every listing you have ever made stays exactly as it is.' },
    { q: 'Can I choose my area code?', a: 'Ask during setup. Numbers are available across the country, and a local area code reads very differently from a toll-free one if your customers are local.' },
    { q: 'Does it cover other time zones?', a: 'It is the same arrangement whether the call arrives at eight in Halifax or five in Vancouver. Nothing has to be rostered for either end of the country.' },
    { q: 'How is this different from Ireland or the UK?', a: 'Canada has no document requirement at all. An Irish business waits on a regulator before a line exists, and a UK number asks for a registered business address first.' },
    { q: 'What about Quebec and French-speaking customers?', a: 'Calls are handled in English only. For a business serving a substantial francophone customer base that is a genuine limitation, and may be reason to choose a different product — we would rather say so here.' },
    { q: 'Where do I read about privacy and tax?', a: 'The Canada guide covers PIPEDA consent, the provincial legislation in Alberta, British Columbia and Quebec, and how GST or HST appears on your invoice.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/google-calendar', label: 'Book into Google Calendar', sub: 'One diary, one copy.' },
      { href: '/integrations/square-appointments', label: 'On Square Appointments?', sub: 'Services, staff and branches.' },
    ],
    guides: [
      { href: '/learn/ai-receptionist-for-canadian-businesses', label: 'The Canada guide', sub: 'Consent, tax and the French caveat.' },
      { href: '/learn/call-recording-consent', label: 'Recording consent', sub: 'What has to be said, and when.' },
      { href: '/learn/keep-your-business-phone-number', label: 'Keeping your number', sub: 'Forward it rather than replace it.' },
    ],
  },

  ctaHeading: 'Answering Canadian calls today, not next week.',
  ctaSub: 'No documents, no review, no queue. Seven days free, and you will know within a week whether it was worth it.',
}

export default function CanadaPage() {
  return <VerticalLanding content={CANADA} />
}
