import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For Courier & Delivery', title: 'Dispatch is slammed. The next order rings out.', benefit: 'Capture every order and feed dispatch, 24/7.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Courier & Delivery | Open Lines',
  description: 'Never miss an order to a busy line. Open Lines answers 24/7, captures pickup and drop-off details, and sends a clean order straight to dispatch.',
  alternates: { canonical: '/courier' },
  openGraph: {
    title: 'AI Receptionist for Courier & Delivery Companies',
    description: 'Capture pickup and drop-off details and feed dispatch — 24/7, no busy signal.',
    url: 'https://www.openlines.ai/courier',
    images: [OG],
  },
}

const COURIER: VerticalContent = {
  slug: 'courier',
  name: 'AI Receptionist for Courier & Delivery Companies',
  shortName: 'Courier',
  eyebrow: 'For Courier & Delivery Companies',
  h1: 'Dispatch is slammed. The next order rings out.',
  subhead:
    'Open Lines is an AI receptionist that answers every call when your dispatch line is busy — capturing pickup and drop-off details, timing, and package info, and sending them straight to your team, 24/7.',
  trustline: 'Live in under 10 minutes · Answers 24/7 · Cancel anytime',
  heroArt: 'textback',

  painsLabel: 'The real cost',
  painsHeading: 'A phone that’s always busy is an order booked with someone else.',
  pains: [
    { stat: 'Peak load', title: 'Dispatch can’t answer everything', body: 'When the board is full, incoming order calls ring out — and the customer books the next courier.' },
    { stat: 'One line', title: 'Callers hit a busy signal', body: 'A single line during a rush means new orders can’t even get through to be booked.' },
    { stat: 'After hours', title: 'Orders come in around the clock', body: 'Same-day and next-morning pickups get arranged late. No answer means no order.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'An intake line that never gives a busy signal.',
  solutionSub: 'It answers in a clear, natural voice, captures the pickup and drop-off addresses, timing, and package details, and sends a clean order straight to dispatch — 24/7, even when every line is tied up.',
  features: [
    { icon: '📦', title: 'Captures pickup & drop-off', body: 'Both addresses, contact names, and timing — everything dispatch needs to assign the job.' },
    { icon: '⚖️', title: 'Takes the package details', body: 'Size, weight, and any special handling, so the right vehicle and driver get assigned.' },
    { icon: '⚡', title: 'Handles overflow instantly', body: 'When dispatch is busy or the line is tied up, it picks up so no order ever hits a busy signal.' },
    { icon: '💬', title: 'Answers common questions', body: '“Do you deliver to my area?” “How fast is same-day?” “What are your rates?” — answered from your site.' },
    { icon: '🌙', title: 'Runs around the clock', body: 'Late-night and early-morning order calls get captured while your team is off the phones.' },
    { icon: '✉️', title: 'Sends orders to dispatch', body: 'Every call arrives as a clean, structured order by text and email so nothing is lost in the rush.' },
  ],

  setup: {
    heading: 'What we configure for courier companies',
    intro: 'Your AI receptionist is tuned to take an order the way your best dispatcher would — complete, validated, and ready to assign.',
    points: [
      { title: 'Address & zone validation', body: 'It reads back the pickup and drop-off addresses to confirm them, and checks them against your service zones so out-of-area orders are flagged before they’re booked.' },
      { title: 'Package & handling details', body: 'It captures size, weight, and special handling (fragile, refrigerated, oversized) so the right vehicle and driver get assigned.' },
      { title: 'Clean dispatch handoff', body: 'Each order arrives as a structured summary — both addresses, timing, package, and contacts — ready to drop onto the board with no re-keying.' },
    ],
  },
  intake: {
    heading: 'Example order intake',
    fields: [
      'Pickup address and contact',
      'Drop-off address and contact',
      'Package size / weight',
      'Time window (same-day / scheduled)',
      'Special handling notes',
      'Billing / account reference',
    ],
  },

  demoMock: { name: 'L. Fernandes', service: 'Same-day pickup', when: 'Today 2:00 PM' },
  textback: { business: 'RapidRoute Courier', reply: 'I need a same-day pickup downtown going to the east end — can you do it today?' },

  integrationsHeading: 'Fits the tools you already run.',
  integrations: ['Google Calendar', 'Outlook'],

  faqs: [
    { q: 'Does it capture full pickup and drop-off details?', a: 'Yes. It takes both addresses, contact names, timing, and the package details, reads the addresses back to confirm them, then sends a clean order to your dispatch team.' },
    { q: 'What happens when our line is busy?', a: 'That’s exactly what it’s for — it answers the overflow so new orders never hit a busy signal or ring out during a rush.' },
    { q: 'Can it check our service zones?', a: 'It checks pickup and drop-off addresses against the areas you cover and flags anything out of zone before the order is booked.' },
    { q: 'Can it run after hours?', a: 'It answers 24/7, so late-night and early-morning order calls get captured while your team is off the phones.' },
    { q: 'What does it sound like?', a: 'A clear, natural human voice. It always discloses that it’s a virtual assistant and sends every order to you by text and email.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/google-calendar', label: 'Put scheduled pickups on Google Calendar', sub: 'Timed orders on the calendar.' },
      { href: '/integrations/slack', label: 'Push new orders into Slack', sub: 'Dispatch sees every order instantly.' },
    ],
    guides: [
      { href: '/learn/automate-your-workflow-2026-ai', label: 'Automate your workflow with AI', sub: 'Where AI saves the most time.' },
      { href: '/learn/missed-call-text-back', label: 'Turn missed calls into booked orders', sub: 'Why answering live wins the order.' },
    ],
  },

  ctaHeading: 'Stop losing orders to a busy line.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it capture orders and feed dispatch around the clock.',
}

export default function CourierPage() {
  return <VerticalLanding content={COURIER} />
}
