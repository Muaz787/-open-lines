import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For Contractors & Builders', title: 'The lead that funds your next quarter just hit voicemail.', benefit: 'Qualify projects and book site visits, 24/7.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Contractors & Builders | Open Lines',
  description: 'Stop losing project leads to voicemail. Open Lines answers 24/7, qualifies scope, timeline & budget, and books site visits and estimates.',
  alternates: { canonical: '/contractors' },
  openGraph: {
    title: 'AI Receptionist for Contractors & Builders',
    description: 'Answer every call, qualify the project, and book site visits and estimates — 24/7.',
    url: 'https://www.openlines.ai/contractors',
    images: [OG],
  },
}

const CONTRACTORS: VerticalContent = {
  slug: 'contractors',
  name: 'AI Receptionist for Contractors & Builders',
  shortName: 'Contractors',
  eyebrow: 'For Contractors & Builders',
  h1: 'The lead that funds your next quarter just hit voicemail.',
  subhead:
    'Open Lines is an AI receptionist that answers every call while you’re on site — qualifying the project, capturing scope and budget, and booking site visits and estimates straight into your calendar.',
  trustline: 'Live in under 10 minutes · Books into Google & Outlook · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'A single reno lead can be worth more than a month of ad spend.',
  pains: [
    { stat: 'On site', title: 'You can’t answer with a nail gun in hand', body: 'You’re framing, pouring, or up a ladder. The phone rings out and the estimate goes to whoever answered.' },
    { stat: 'Big tickets', title: 'The leads you miss are the expensive ones', body: 'Kitchens, additions, full builds — high-value projects start with a call you didn’t catch.' },
    { stat: 'Tire-kickers', title: 'Your time is wasted on unqualified calls', body: 'Without screening, you drive across town for jobs that were never a real fit.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'A project intake line that qualifies before you drive out.',
  solutionSub: 'It answers in a professional, natural voice, captures the scope, timeline and budget, screens whether it’s a fit, and books the site visit or estimate — 24/7, so no lead sits in voicemail.',
  features: [
    { icon: '📐', title: 'Qualifies the project', body: 'Captures scope, timeline, and budget range up front so you know it’s worth the drive before you book it.' },
    { icon: '📅', title: 'Books site visits & estimates', body: 'Drops the appointment straight into your Google or Outlook calendar with your real availability.' },
    { icon: '📍', title: 'Captures the details', body: 'Property address, project type, and what the client actually wants — ready for you before you arrive.' },
    { icon: '💬', title: 'Answers common questions', body: '“Do you do additions?” “Are you licensed and insured?” “What areas do you cover?” — answered from your site.' },
    { icon: '🌙', title: 'Catches after-hours leads', body: 'Homeowners research projects in the evening. Those calls become booked estimates instead of missed ones.' },
    { icon: '✉️', title: 'Summarizes every lead', body: 'A clean summary of each call — scope, budget, urgency, and next step — lands in your inbox.' },
  ],

  setup: {
    heading: 'What we configure for contractors',
    intro: 'Your AI receptionist is tuned to qualify a job the way you would on a first phone call — so the estimates you drive to are worth the trip.',
    points: [
      { title: 'Project qualification', body: 'It captures the project type, rough scope, desired timeline, and a budget range, so you can tell a real job from a tire-kicker before booking.' },
      { title: 'Service-area & fit screening', body: 'It checks the property location against the areas you serve and the kinds of work you take, and flags anything out of scope.' },
      { title: 'Estimate scheduling', body: 'Once a lead qualifies, it books the site visit or estimate into your live calendar and captures the address and access details.' },
    ],
  },
  intake: {
    heading: 'Example project intake',
    fields: [
      'Project type (reno, addition, new build)',
      'Property address',
      'Scope summary — what they want done',
      'Rough budget range',
      'Desired timeline / start date',
      'Preferred site-visit time',
    ],
  },

  demoMock: { name: 'R. Bell', service: 'Kitchen reno estimate', when: 'Fri 9:00 AM' },
  textback: { business: 'Ironwood Builders', reply: 'We’re looking to renovate our kitchen this spring — can we get an estimate?' },

  integrationsHeading: 'Works with the calendar and CRM you already run.',
  integrations: ['Google Calendar', 'Outlook', 'HubSpot'],

  faqs: [
    { q: 'Can it qualify leads before I book a visit?', a: 'Yes. It captures scope, timeline, and budget range so you can see whether a project is a real fit before you spend an afternoon driving to it.' },
    { q: 'Does it book estimates into my calendar?', a: 'It books site visits and estimates straight into your Google or Outlook calendar using your live availability.' },
    { q: 'Can it screen out-of-area or out-of-scope jobs?', a: 'It checks the property location against the areas you serve and the work you take, and flags anything outside your scope so you don’t waste a trip.' },
    { q: 'What about calls that come in while I’m on site?', a: 'That’s exactly the point — it answers every call, 24/7, so the leads you can’t pick up become booked estimates instead of voicemails.' },
    { q: 'What does it sound like?', a: 'A professional, natural human voice. It always discloses that it’s a virtual assistant and captures everything you need for the job.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/stripe', label: 'Take a deposit to hold the job', sub: 'Cut no-shows with a secure Stripe link.' },
      { href: '/integrations/hubspot', label: 'Log every lead to HubSpot', sub: 'Contact + call summary, automatically.' },
      { href: '/integrations/google-calendar', label: 'Book estimates into Google Calendar', sub: 'Live availability, no clashes.' },
    ],
    guides: [
      { href: '/learn/missed-call-text-back', label: 'Turn missed calls into booked jobs', sub: 'Why answering live wins the lead.' },
      { href: '/learn/virtual-receptionist-small-business', label: 'The small-business receptionist guide', sub: 'Live vs. AI, and how to choose.' },
    ],
  },

  ctaHeading: 'Stop letting project leads ring out.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it qualify and book while you stay on the build.',
}

export default function ContractorsPage() {
  return <VerticalLanding content={CONTRACTORS} />
}
