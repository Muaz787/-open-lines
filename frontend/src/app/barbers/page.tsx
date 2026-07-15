import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'

export const metadata: Metadata = {
  title: 'AI Receptionist for Barbershops — Open Lines',
  description: 'Stop putting down the clippers to answer the phone. Open Lines answers every call, books chairs with the right barber, and handles walk-in questions 24/7. Start a 7-day free trial — no credit card.',
  alternates: { canonical: '/barbers' },
}

const BARBERS: VerticalContent = {
  slug: 'barbers',
  eyebrow: 'For Barbershops',
  h1: 'Never put down the clippers to answer the phone again.',
  subhead:
    'Open Lines is an AI receptionist that answers every call mid-cut — booking chairs, quoting walk-in waits, and telling callers which barber is in. The phone stops interrupting your fade, and no booking gets missed.',
  trustline: 'Live in under 10 minutes · Books with the right barber · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'The phone always rings mid-fade.',
  pains: [
    { stat: 'Every ring', title: 'Interrupts the cut', body: 'Stop to grab the phone and you rush the line-up. Let it ring and the booking goes to the shop down the street.' },
    { stat: '3 questions', title: 'Asked all day long', body: '“You open?” “Take walk-ins?” “Is Marcus in today?” — the same calls, on repeat, while your hands are busy.' },
    { stat: 'Nights + Mondays', title: 'Missed when you’re closed', body: 'Guys book when they clock off work. A call after close is a head of hair you never hear from again.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'It answers like the guy behind the counter.',
  solutionSub: 'Open Lines knows your hours, prices and barbers from your own website, books chairs into your app, and handles the walk-in questions — so you keep the clippers moving.',
  features: [
    { icon: '💈', title: 'Books the right barber', body: 'Client wants a specific barber and service? It books that chair, at a real open slot, in your booking app.' },
    { icon: '🚶', title: 'Quotes walk-in waits', body: 'Answers “are you busy right now?” and points walk-ins to the next available time.' },
    { icon: '🕒', title: 'Knows who’s in today', body: 'Tells callers which barbers are working and when they’re next free.' },
    { icon: '💬', title: 'Answers instantly', body: 'Hours, pricing, location, parking — all handled from your website, no interruption to you.' },
    { icon: '📲', title: 'Cuts no-shows', body: 'Texts a confirmation and reminder so booked chairs actually show up.' },
    { icon: '🌙', title: 'Works 24/7', body: 'After close, weekends, holidays — every call gets answered and booked.' },
  ],

  demoMock: { name: 'Chris D.', service: 'Skin fade + beard', when: 'Sat 11:00 AM', with: 'Marcus' },
  textback: { business: 'Fade Co.', reply: 'You got any spots for a fade today?' },

  integrationsHeading: 'Plugs into the tools you already run.',
  integrations: ['Squire', 'Booksy', 'Fresha', 'Square Appointments', 'Google Calendar', 'Outlook'],

  faqs: [
    { q: 'Can it book with a specific barber?', a: 'Yes. It books the barber and service the caller asks for, using your real live availability.' },
    { q: 'Can it handle walk-in questions?', a: 'It answers how busy you are and quotes the next open slot, so walk-in callers know when to come in.' },
    { q: 'Does it work with Squire or Booksy?', a: 'It books into Squire, Booksy, Fresha, Square Appointments, Google Calendar and Outlook — no change to how you already run the shop.' },
    { q: 'Will callers know it’s AI?', a: 'It sounds natural and to the point, and always discloses that it’s a virtual assistant, as required.' },
  ],

  ctaHeading: 'Keep the clippers moving. Let the AI answer.',
  ctaSub: 'Set it up in under 10 minutes and never lose another booking to a phone you couldn’t reach.',
}

export default function BarbersPage() {
  return <VerticalLanding content={BARBERS} />
}
