import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For Salons & Spas', title: 'Every missed call is a client in someone else’s chair.', benefit: 'Books the right stylist, straight into your calendar.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Salons & Spas | Open Lines',
  description: 'Never lose a booking to a missed call. Open Lines answers 24/7 and books the right stylist into Google Calendar, Outlook or Square Appointments.',
  alternates: { canonical: '/salons' },
  openGraph: {
    title: 'AI Receptionist for Salons & Spas',
    description: 'Answer every call and book the right stylist — 24/7, into the calendar you already use.',
    url: 'https://www.openlines.ai/salons',
    images: [OG],
  },
}

const SALONS: VerticalContent = {
  slug: 'salons',
  name: 'AI Receptionist for Salons & Spas',
  shortName: 'Salons & Spas',
  eyebrow: 'For Beauty Salons & Spas',
  h1: 'Your hands are full. Your phone shouldn’t cost you clients.',
  subhead:
    'Open Lines is an AI receptionist that answers every call while you’re with a client — booking appointments straight into your Google, Outlook, or Square Appointments calendar. Stop losing bookings to a phone you can’t pick up.',
  trustline: 'Live in under 10 minutes · Works with your booking software · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'Every missed call is a client in someone else’s chair.',
  pains: [
    { stat: '80%', title: 'Voicemail = goodbye', body: 'Four out of five callers who reach voicemail never call back. They just book the salon that picked up.' },
    { stat: 'After 6pm', title: 'Clients book after hours', body: 'Evenings and Sundays are when clients plan their week. If no one answers, your chair stays empty.' },
    { stat: 'Mid-blowout', title: 'You can’t stop mid-service', body: 'Color, cuts, checkouts, walk-ins — the front desk is stretched, and the phone is always what drops.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'An AI receptionist that books like your best front desk.',
  solutionSub: 'It answers in a warm, natural voice, knows your services and prices from your own website, and books the right service with the right stylist — 24/7.',
  features: [
    { icon: '📅', title: 'Books the right stylist', body: 'Takes the service and the stylist the client asks for, and drops it straight into your calendar.' },
    { icon: '💬', title: 'Answers the FAQs', body: '“Do you do balayage?” “What’s parking like?” “How much for a full set?” — answered from your website.' },
    { icon: '💳', title: 'Takes deposits', body: 'Texts a secure Stripe or Square payment link to lock in the booking and cut no-shows (Pro & Business).' },
    { icon: '👯', title: 'Handles group bookings', body: 'Bridal parties, events and back-to-back appointments — captured and scheduled cleanly.' },
    { icon: '👋', title: 'Knows returning clients', body: 'Greets regulars by name and picks up where they left off.' },
    { icon: '✉️', title: 'Confirms both ways', body: 'Texts the client a confirmation and sends you a summary of every call.' },
  ],

  setup: {
    heading: 'What we configure for salons & spas',
    intro: 'Your AI receptionist is tuned to book like your best front desk — with your services, your stylists, and your no-show protection.',
    points: [
      { title: 'Service & stylist matching', body: 'It learns your service menu and your team, so it books the right treatment with the requested stylist at a genuinely open slot.' },
      { title: 'Deposits to cut no-shows', body: 'On eligible plans it texts a secure Stripe or Square link to take a deposit at booking — protecting your chair from no-shows.' },
      { title: 'Group & bridal bookings', body: 'Bridal parties and back-to-back appointments are captured cleanly and scheduled without tying up your front desk.' },
    ],
  },
  intake: {
    heading: 'Example booking intake',
    fields: [
      'Service requested (and add-ons)',
      'Preferred stylist',
      'Preferred date and time',
      'New client or returning regular',
      'Contact name and phone',
      'Deposit taken (eligible plans)',
    ],
  },

  demoMock: { name: 'Jordan M.', service: 'Balayage + cut', when: 'Thu 2:30 PM', with: 'Nadia' },
  textback: { business: 'Studio Luxe', reply: 'Hi! I wanted to book a colour appointment for this weekend.' },

  integrationsHeading: 'Plugs into the tools you already run.',
  integrations: ['Google Calendar', 'Outlook', 'Square Appointments'],

  faqs: [
    { q: 'Can it book with a specific stylist?', a: 'Yes. If a client asks for a particular stylist and service, it books exactly that — into your live calendar with real availability.' },
    { q: 'Does it work with my calendar?', a: 'It books into Google Calendar, Outlook and Square Appointments with real live availability, so there’s nothing to rip out.' },
    { q: 'What does it sound like?', a: 'A warm, natural human voice. Callers rarely realise it’s AI — and it always discloses that it’s a virtual assistant, as required.' },
    { q: 'What if it can’t answer something?', a: 'It never guesses. It captures the details and texts or emails you to follow up, so nothing falls through.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/square-appointments', label: 'Book into Square Appointments', sub: 'Live Square availability.' },
      { href: '/integrations/google-calendar', label: 'Book into Google Calendar', sub: 'Real-time, no double-booking.' },
      { href: '/integrations/stripe', label: 'Take deposits with Stripe', sub: 'Cut no-shows at the point of booking.' },
    ],
    guides: [
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'How it answers and books.' },
      { href: '/learn/missed-call-text-back', label: 'Turn missed calls into bookings', sub: 'Why answering live wins the client.' },
    ],
  },

  ctaHeading: 'Stop losing clients to a ringing phone.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it answer every call while you focus on the chair in front of you.',
}

export default function SalonsPage() {
  return <VerticalLanding content={SALONS} />
}
