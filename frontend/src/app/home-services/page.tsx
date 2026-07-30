import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For HVAC, Plumbing & Electrical', title: 'Answer every service call while your hands are full.', benefit: 'Triage emergencies and book the job, 24/7.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Home Service Businesses | Open Lines',
  description: 'Win the job while you’re on the tools. Open Lines answers HVAC, plumbing & electrical calls 24/7, triages emergencies, and books the service call.',
  alternates: { canonical: '/home-services' },
  openGraph: {
    title: 'AI Receptionist for Home Service Businesses',
    description: 'Answer every call, triage emergencies, and book the service call — 24/7, even on the tools.',
    url: 'https://www.openlines.ai/home-services',
    images: [OG],
  },
}

const HOME_SERVICES: VerticalContent = {
  slug: 'home-services',
  name: 'AI Receptionist for Home Service Businesses',
  shortName: 'Home Services',
  eyebrow: 'For HVAC, Plumbing & Electrical',
  h1: 'You’re under a sink. The next emergency call goes to voicemail.',
  subhead:
    'Open Lines is an AI receptionist that answers every call while your hands are full — triaging urgent jobs from routine ones, capturing the address and the problem, and booking the service call straight into your calendar.',
  trustline: 'Live in under 10 minutes · Answers 24/7 · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'Emergencies don’t wait for you to climb out of the crawlspace.',
  pains: [
    { stat: '1 job', title: 'One missed call = one lost job', body: 'A burst pipe or dead furnace is booked with whoever answers first. Voicemail loses the job every time.' },
    { stat: 'Nights', title: 'The worst breakdowns are after hours', body: 'No heat at 11pm, flooding on a Sunday — that’s exactly when nobody’s at the phone.' },
    { stat: 'On the tools', title: 'You can’t answer mid-repair', body: 'You’re on a roof, under a house, or driving between jobs. The phone is the first thing to drop.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'A dispatcher that never misses a call.',
  solutionSub: 'It answers in a friendly, natural voice, tells an emergency from a routine job, captures the address and the problem, and books the service call — 24/7, even when every tech is already out.',
  features: [
    { icon: '🚨', title: 'Triages urgent vs. routine', body: 'No heat, no water, sparks — flagged urgent so you can respond fast. Routine jobs get booked in normally.' },
    { icon: '📍', title: 'Captures the job details', body: 'Address, the problem, the equipment, and access notes — everything the tech needs before they roll.' },
    { icon: '📅', title: 'Books the service call', body: 'Drops the appointment straight into your Google or Outlook calendar with real availability.' },
    { icon: '💬', title: 'Answers the basics', body: '“Do you service my area?” “What are your call-out rates?” “Are you licensed?” — answered from your site.' },
    { icon: '🌙', title: 'Covers nights & weekends', body: 'The after-hours emergencies you’re currently missing become booked jobs on Monday morning.' },
    { icon: '✉️', title: 'Texts you the details', body: 'Every call comes through as a clean summary by text and email so nothing gets lost between jobs.' },
  ],

  setup: {
    heading: 'What we configure for home-service businesses',
    intro: 'Your AI receptionist is tuned to triage like an experienced dispatcher — so the emergency jobs get to you fast and the routine ones get booked cleanly.',
    points: [
      { title: 'Emergency triage rules', body: 'No heat, no water, gas smell, sparking, or flooding are flagged as emergencies and pushed to you immediately; routine maintenance is booked into the next open slot.' },
      { title: 'Service-area screening', body: 'It checks the caller’s address or postal code against the areas you cover, so you don’t drive an hour for a job outside your zone.' },
      { title: 'Job-ready details', body: 'It captures the equipment, the fault, and access notes (gate codes, parking, pets) so your tech rolls with everything they need.' },
    ],
  },
  intake: {
    heading: 'Example service intake',
    fields: [
      'Service address and postal code',
      'Nature of the fault (what’s happening)',
      'Equipment make / model',
      'Urgency — emergency vs. routine',
      'Access notes (gate, parking, pets)',
      'Preferred time window',
    ],
  },

  demoMock: { name: 'M. Tran', service: 'No-heat call-out', when: 'Today 4:00 PM' },
  textback: { business: 'PeakFlow Heating', reply: 'My furnace stopped working and it’s freezing — can someone come out today?' },

  integrationsHeading: 'Works with the calendar you already run.',
  integrations: ['Google Calendar', 'Outlook'],

  faqs: [
    { q: 'Can it tell an emergency from a routine job?', a: 'Yes. It’s tuned to flag urgent situations — no heat, no water, gas or electrical hazards — as high priority so you can respond fast, and book everything else normally.' },
    { q: 'Does it capture the address and the problem?', a: 'Every time. You get the address, the nature of the fault, the equipment, and any access notes — everything a tech needs before rolling to site.' },
    { q: 'Does it check my service area?', a: 'It screens the caller’s address or postal code against the areas you cover, so out-of-area calls are handled without wasting a truck roll.' },
    { q: 'What happens after hours?', a: 'It answers 24/7. The late-night and weekend breakdowns you’re missing today get captured and booked, and urgent ones are flagged immediately.' },
    { q: 'What does it sound like?', a: 'A friendly, natural human voice. It always discloses that it’s a virtual assistant and books into your live calendar.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/google-calendar', label: 'Book jobs into Google Calendar', sub: 'Live availability, no clashes.' },
      { href: '/integrations/outlook', label: 'Book into Outlook & Microsoft 365', sub: 'For teams on Microsoft.' },
    ],
    guides: [
      { href: '/learn/missed-call-text-back', label: 'Turn missed calls into booked jobs', sub: 'Why answering live wins the job.' },
      { href: '/learn/answering-service-cost', label: 'What does an answering service cost?', sub: '2026 pricing compared.' },
    ],
  },

  ctaHeading: 'Stop losing jobs to a ringing phone.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it triage and book while you stay on the tools.',
}

export default function HomeServicesPage() {
  return <VerticalLanding content={HOME_SERVICES} />
}
