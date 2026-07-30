import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For Auto Shops & Dealerships', title: 'Every bay is full — and so is your voicemail.', benefit: 'Route calls, capture the vehicle, book service — 24/7.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Auto Shops & Dealers | Open Lines',
  description: 'Never miss a service booking. Open Lines answers 24/7, routes sales, service & collision, captures the vehicle, and books the appointment.',
  alternates: { canonical: '/automotive' },
  openGraph: {
    title: 'AI Receptionist for Auto Shops & Dealerships',
    description: 'Route sales, service & collision, capture the vehicle, and book the appointment — 24/7.',
    url: 'https://www.openlines.ai/automotive',
    images: [OG],
  },
}

const AUTOMOTIVE: VerticalContent = {
  slug: 'automotive',
  name: 'AI Receptionist for Auto Shops & Dealerships',
  shortName: 'Automotive',
  eyebrow: 'For Repair Shops, Body Shops & Dealerships',
  h1: 'Every bay is full — and so is your voicemail.',
  subhead:
    'Open Lines is an AI receptionist that answers every call while your team is under the hood — routing sales, service, and collision calls, capturing the vehicle details, and booking the right appointment straight into your calendar.',
  trustline: 'Live in under 10 minutes · Books into Google & Outlook · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'When the shop is slammed, the phone is the first thing to drop.',
  pains: [
    { stat: 'Heads down', title: 'Your techs can’t stop to answer', body: 'Everyone’s on a car. The phone rings out, and the service booking goes to the shop down the road.' },
    { stat: 'Wrong desk', title: 'Calls land at the wrong department', body: 'Sales, service, and collision get tangled — and the caller gives up before reaching the right person.' },
    { stat: 'After close', title: 'Bookings happen after hours', body: 'Drivers call about a noise or a warning light in the evening. No answer means no appointment.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'A service advisor for the phone that never leaves the desk.',
  solutionSub: 'It answers in a friendly, natural voice, routes the caller to the right department, captures the vehicle and the issue, and books the appointment — 24/7, even when every bay is full.',
  features: [
    { icon: '🔀', title: 'Routes sales, service & collision', body: 'Figures out what the caller needs and captures it for the right department — no more tangled lines.' },
    { icon: '🚗', title: 'Captures the vehicle', body: 'Year, make, model, and the problem — so your advisor has the full picture before the car arrives.' },
    { icon: '📅', title: 'Books the appointment', body: 'Drops service and estimate appointments straight into your Google or Outlook calendar with real availability.' },
    { icon: '💬', title: 'Answers common questions', body: '“Do you do diagnostics?” “Are you open Saturday?” “Do you offer loaners?” — answered from your site.' },
    { icon: '🌙', title: 'Catches after-hours calls', body: 'The evening and weekend calls you’re missing today become booked appointments for the week ahead.' },
    { icon: '✉️', title: 'Summarizes every call', body: 'A clean summary of each caller — vehicle, issue, department, and next step — lands in your inbox.' },
  ],

  setup: {
    heading: 'What we configure for auto shops',
    intro: 'Your AI receptionist is tuned to work like a sharp service advisor — getting the caller to the right department with the vehicle already on file.',
    points: [
      { title: 'Department routing', body: 'It works out whether the caller needs service, sales, or collision, and captures the call for the right desk instead of leaving it tangled on one line.' },
      { title: 'Vehicle capture', body: 'It takes the year, make, and model (and VIN when the caller has it), plus the reported issue, so your advisor has the full picture before the car arrives.' },
      { title: 'Towing & urgent flags', body: 'Breakdowns, no-starts, and collision calls are flagged as urgent so a stranded driver reaches you fast instead of waiting on hold.' },
    ],
  },
  intake: {
    heading: 'Example service intake',
    fields: [
      'Year / make / model (VIN if known)',
      'Reported issue or symptom',
      'Department — service, sales, collision',
      'Preferred drop-off time',
      'Loaner or shuttle needed?',
      'Contact name and phone',
    ],
  },

  demoMock: { name: 'K. Osei', service: 'Brake service · 2019 Civic', when: 'Tue 8:30 AM' },
  textback: { business: 'Rideline Auto', reply: 'My brakes are squealing — can I bring my car in this week?' },

  integrationsHeading: 'Works with the calendar you already run.',
  integrations: ['Google Calendar', 'Outlook'],

  faqs: [
    { q: 'Can it route sales, service, and collision separately?', a: 'Yes. It works out what the caller needs and captures it for the right department, so calls don’t get tangled or dropped between desks.' },
    { q: 'Does it capture the vehicle details?', a: 'It takes the year, make, model, and the problem (and the VIN when the caller has it), so your service advisor has the full picture before the car ever arrives.' },
    { q: 'How does it handle breakdowns and towing calls?', a: 'No-starts, breakdowns, and collision calls are flagged as urgent so a stranded driver reaches you quickly instead of sitting in voicemail.' },
    { q: 'Does it book into my calendar?', a: 'It books service appointments and estimates straight into your Google or Outlook calendar using your live availability.' },
    { q: 'What does it sound like?', a: 'A friendly, natural human voice. It always discloses that it’s a virtual assistant and answers 24/7 — even after you close.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/google-calendar', label: 'Book service into Google Calendar', sub: 'Live availability, no clashes.' },
      { href: '/integrations/outlook', label: 'Book into Outlook & Microsoft 365', sub: 'For shops on Microsoft.' },
    ],
    guides: [
      { href: '/learn/answering-service-cost', label: 'What does an answering service cost?', sub: '2026 pricing compared.' },
      { href: '/learn/missed-call-text-back', label: 'Turn missed calls into booked service', sub: 'Why answering live wins the job.' },
    ],
  },

  ctaHeading: 'Stop sending service bookings to voicemail.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it route, capture, and book while your team stays in the bays.',
}

export default function AutomotivePage() {
  return <VerticalLanding content={AUTOMOTIVE} />
}
