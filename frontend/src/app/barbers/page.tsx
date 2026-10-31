import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'

const OG = { url: '/og/barbers.jpg', width: 1200, height: 630, alt: 'Barbershop calls, covered. 24/7 AI receptionist for barbershops.' }

export const metadata: Metadata = {
  title: 'AI Receptionist for Barbershops | Open Lines',
  description: 'Open Lines answers barbershop calls 24/7, books the right barber, and handles questions about hours, prices and walk-ins.',
  alternates: { canonical: '/barbers' },
  openGraph: {
    title: 'AI Receptionist for Barbershops',
    description: 'Answer calls, book the right barber, and handle walk-in questions 24/7.',
    url: 'https://www.openlines.ai/barbers',
    images: [OG],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'AI Receptionist for Barbershops',
    description: 'Answer calls, book the right barber, and handle walk-in questions 24/7.',
    images: [OG],
  },
}

const BARBERS: VerticalContent = {
  slug: 'barbers',
  name: 'AI Receptionist for Barbershops',
  shortName: 'Barbershops',
  eyebrow: 'For Barbershops',
  h1: 'Keep your hands on the cut. Let Open Lines handle the calls.',
  subhead:
    'Open Lines is an AI receptionist that answers calls while you’re mid-cut, books appointments with the barber a caller asks for, and answers questions about your hours, prices and walk-ins.',
  trustline: 'Books fades, cuts and beard trims with the barber your client wants',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'The phone always rings mid-fade.',
  pains: [
    { stat: 'Every ring', title: 'Interrupts the cut', body: 'Stop to grab the phone and you rush the line-up. Let it ring and the caller may try the shop down the street.' },
    { stat: '3 questions', title: 'Asked all day long', body: '“You open?” “Take walk-ins?” “Is Marcus in today?” — the same calls, on repeat, while your hands are busy.' },
    { stat: 'Nights + Mondays', title: 'Missed when you’re closed', body: 'Clients often call after work. A call after close may be a booking you never hear about.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'It answers the way your shop would.',
  solutionSub: 'Give it your shop hours, cut prices and barbers. It fills open chairs and fields walk-in questions, so the clippers keep moving.',
  features: [
    { icon: '💈', title: 'Books the right barber', body: 'Client wants a specific barber and service? It checks that barber’s availability and books an open time in your calendar.' },
    { icon: '🚶', title: 'Handles walk-in questions', body: 'Explains your walk-in policy from your knowledge base and offers the next open appointment.' },
    { icon: '🕒', title: 'Checks a barber’s times', body: 'When a caller asks for a barber by name, it checks that barber’s open times.' },
    { icon: '💬', title: 'Answers common questions', body: 'Opening times, cut prices, directions and parking, pulled from what you’ve told it about the shop.' },
    { icon: '📲', title: 'Confirms by text', body: 'Texts the client a confirmation after booking.' },
    { icon: '🌙', title: 'Works 24/7', body: 'After close, weekends and holidays, your AI receptionist is there to take the call.' },
  ],

  setup: {
    heading: 'What we configure for barbershops',
    intro: 'Your AI receptionist is set up with your barbers, your services and your walk-in policy.',
    points: [
      { title: 'Barber & chair matching', body: 'Add your barbers and services, and it can book the requested barber at an open time in your connected calendar.' },
      { title: 'Walk-in questions', body: 'Add your walk-in policy to its knowledge base. It explains the policy and can offer the next open appointment. It doesn’t track how busy the shop is right now.' },
      { title: 'Barber availability', body: 'It checks a named barber’s calendar availability when a caller asks to book with them.' },
    ],
  },
  intake: {
    heading: 'Example booking intake',
    fields: [
      'Service requested (cut, fade, beard)',
      'Preferred barber',
      'Preferred date and time',
      'Walk-in or booked appointment',
      'Contact name and phone',
      'Confirmation text sent',
    ],
  },

  demoMock: { name: 'Chris D.', service: 'Skin fade + beard', when: 'Sat 11:00 AM', with: 'Marcus' },
  textback: { business: 'Sample Barbershop', reply: 'You got any spots for a fade today?' },

  integrationsHeading: 'Plugs into the tools you already run.',
  integrations: ['Google Calendar', 'Outlook', 'Square Appointments'],

  faqs: [
    { q: 'Can it book with a specific barber?', a: 'Yes. Add your team, and it checks the requested barber’s availability and books the service the caller asks for.' },
    { q: 'Can it handle walk-in questions?', a: 'Yes. It explains your walk-in policy and can offer the next open appointment. It doesn’t quote live wait times, because it can’t see how busy the shop is.' },
    { q: 'Does it work with my calendar?', a: 'Google Calendar, Outlook and Square Appointments are supported. Shops on another app can still take calls and messages, but bookings won’t land in that app.' },
    { q: 'Will callers know it’s AI?', a: 'Yes. Right at the start, callers hear that they’ve reached a virtual receptionist and that the line may be recorded.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/square-appointments', label: 'Book into Square Appointments', sub: 'Live Square availability.' },
      { href: '/integrations/google-calendar', label: 'Book into Google Calendar', sub: 'Checks live availability.' },
    ],
    guides: [
      { href: '/learn/walk-ins-versus-appointments', label: 'Walk-ins versus appointments', sub: 'What the phone should say.' },
      { href: '/learn/can-you-fit-me-in-today', label: '"Can you fit me in today?"', sub: 'The caller who never rings twice.' },
      { href: '/learn/booking-with-a-specific-team-member', label: 'Asking for a barber by name', sub: 'Per-person availability.' },
      { href: '/learn/missed-call-text-back', label: 'Turn missed calls into booked chairs', sub: 'Why answering live wins the booking.' },
    ],
  },

  ctaHeading: 'Keep the clippers moving. Let the AI answer.',
  ctaSub: 'Under 10 minutes to set up, then the phone stops pulling you away from the fade.',
}

export default function BarbersPage() {
  return <VerticalLanding content={BARBERS} />
}
