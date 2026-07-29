import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'

export const metadata: Metadata = {
  title: 'AI Receptionist for Courier & Delivery Companies — Open Lines',
  description: 'Never miss an order to a busy line. Open Lines answers your courier or delivery phone 24/7, captures pickup and drop-off details, and sends them straight to dispatch. 7-day free trial — no credit card.',
  alternates: { canonical: '/courier' },
}

const COURIER: VerticalContent = {
  slug: 'courier',
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

  demoMock: { name: 'L. Fernandes', service: 'Same-day pickup', when: 'Today 2:00 PM' },
  textback: { business: 'RapidRoute Courier', reply: 'I need a same-day pickup downtown going to the east end — can you do it today?' },

  integrationsHeading: 'Fits the tools you already run.',
  integrations: ['Google Calendar', 'Outlook'],

  faqs: [
    { q: 'Does it capture full pickup and drop-off details?', a: 'Yes. It takes both addresses, contact names, timing, and the package details, then sends a clean order straight to your dispatch team.' },
    { q: 'What happens when our line is busy?', a: 'That’s exactly what it’s for — it answers the overflow so new orders never hit a busy signal or ring out during a rush.' },
    { q: 'Can it run after hours?', a: 'It answers 24/7, so late-night and early-morning order calls get captured while your team is off the phones.' },
    { q: 'What does it sound like?', a: 'A clear, natural human voice. It always discloses that it’s a virtual assistant and sends every order to you by text and email.' },
  ],

  ctaHeading: 'Stop losing orders to a busy line.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it capture orders and feed dispatch around the clock.',
}

export default function CourierPage() {
  return <VerticalLanding content={COURIER} />
}
