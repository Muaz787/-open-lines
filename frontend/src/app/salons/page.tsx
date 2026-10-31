import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'

const OG = { url: '/og/salons.jpg', width: 1200, height: 630, alt: 'Salon calls, covered. 24/7 AI receptionist for salons.' }

export const metadata: Metadata = {
  title: 'AI Receptionist for Salons & Spas | Open Lines',
  description: 'Open Lines answers salon calls 24/7 and books the right stylist into Google Calendar, Outlook or Square Appointments.',
  alternates: { canonical: '/salons' },
  openGraph: {
    title: 'AI Receptionist for Salons & Spas',
    description: 'Answer calls and book the right stylist 24/7, in the calendar you already use.',
    url: 'https://www.openlines.ai/salons',
    images: [OG],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'AI Receptionist for Salons & Spas',
    description: 'Answer calls and book the right stylist 24/7, in the calendar you already use.',
    images: [OG],
  },
}

const SALONS: VerticalContent = {
  slug: 'salons',
  name: 'AI Receptionist for Salons & Spas',
  shortName: 'Salons & Spas',
  eyebrow: 'For Beauty Salons & Spas',
  h1: 'Your hands are full. Let Open Lines handle the calls.',
  subhead:
    'Open Lines is an AI receptionist that answers calls while you’re with a client and books appointments into your Google, Outlook or Square Appointments calendar.',
  trustline: 'Works with Google Calendar, Outlook and Square Appointments',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'A missed call can put a client in someone else’s chair.',
  pains: [
    { stat: 'Voicemail', title: 'Callers may move on', body: 'A caller who reaches voicemail may not leave a message, and may book with the salon that picks up.' },
    { stat: 'After 6pm', title: 'Clients book after hours', body: 'Clients often plan their week in the evening or on a day off, when no one is at the front desk.' },
    { stat: 'Mid-blowout', title: 'You can’t stop mid-service', body: 'Color, cuts, checkouts, walk-ins — the front desk is stretched, and the phone is always what drops.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'An AI receptionist set up around your salon.',
  solutionSub: 'It answers in a natural voice, uses the services and prices from your website and knowledge base, and books the service and stylist the client asks for, 24/7.',
  features: [
    { icon: '📅', title: 'Books the right stylist', body: 'Takes the service and stylist the client asks for, checks availability and books it in your calendar.' },
    { icon: '💬', title: 'Answers the FAQs', body: '“Do you do balayage?” “What’s parking like?” “How much for a full set?” — answered from your website and knowledge base.' },
    { icon: '💳', title: 'Takes deposits', body: 'Texts a secure Stripe or Square payment link to secure the booking and help reduce no-shows (Pro & Business).' },
    { icon: '👯', title: 'Handles group bookings', body: 'Takes the party size for bridal parties and events, and books around your availability.' },
    { icon: '👋', title: 'Recognises returning clients', body: 'Greets returning callers by name, using their earlier calls.' },
    { icon: '✉️', title: 'Confirms both ways', body: 'Texts the client a confirmation and sends you a summary after each call.' },
  ],

  setup: {
    heading: 'What we configure for salons & spas',
    intro: 'Your AI receptionist is set up with your services, your stylists and, on eligible plans, your deposit rules.',
    points: [
      { title: 'Service & stylist matching', body: 'Add your services and team, and it can book the requested treatment with the requested stylist at an open time.' },
      { title: 'Deposits to cut no-shows', body: 'On eligible plans it texts a secure Stripe or Square link to take a deposit at booking, which can help reduce no-shows.' },
      { title: 'Group & bridal bookings', body: 'It takes the party size for group appointments so your front desk doesn’t have to.' },
    ],
  },
  intake: {
    heading: 'Example booking details',
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
  textback: { business: 'Sample Salon', reply: 'Hi! I wanted to book a colour appointment for this weekend.' },

  integrationsHeading: 'Plugs into the tools you already run.',
  integrations: ['Google Calendar', 'Outlook', 'Square Appointments'],

  faqs: [
    { q: 'Can it book with a specific stylist?', a: 'Yes. Add your team, and if a client asks for a particular stylist it checks that person’s availability and books them.' },
    { q: 'Does it book into the salon calendar we already use?', a: 'It works with Google Calendar, Outlook and Square Appointments. If you use another booking system, it can’t book into that system directly.' },
    { q: 'What does it sound like to a client booking in?', a: 'A natural voice. Each call opens by saying it’s a virtual receptionist and that the call may be recorded.' },
    { q: 'What if it can’t answer something?', a: 'It notes the client’s question and contact details, and your post-call summary shows what to follow up on.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/square-appointments', label: 'Book into Square Appointments', sub: 'Live Square availability.' },
      { href: '/integrations/google-calendar', label: 'Book into Google Calendar', sub: 'Checks live availability.' },
      { href: '/integrations/stripe', label: 'Take deposits with Stripe', sub: 'Help reduce no-shows at booking.' },
    ],
    guides: [
      { href: '/learn/can-you-fit-me-in-today', label: '"Can you fit me in today?"', sub: 'Your highest-intent caller.' },
      { href: '/learn/patch-tests-and-colour-appointments', label: 'Colour and patch tests', sub: 'Why the timing decides it.' },
      { href: '/learn/booking-a-consultation-first', label: 'When a consultation comes first', sub: 'Extensions and corrections.' },
      { href: '/learn/booking-with-a-specific-team-member', label: 'Asking for a stylist by name', sub: 'Per-person availability.' },
      { href: '/learn/missed-call-text-back', label: 'Turn missed calls into bookings', sub: 'Why answering live wins the client.' },
    ],
  },

  ctaHeading: 'Get back to the client in your chair.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it answer calls while you focus on the client in front of you.',
}

export default function SalonsPage() {
  return <VerticalLanding content={SALONS} />
}
