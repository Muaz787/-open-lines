import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For Restaurants & Cafés', title: 'The phone rings through dinner service. Nobody can grab it.', benefit: 'Take reservations and answer FAQs, 24/7.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Restaurants | Open Lines',
  description: 'Never miss a reservation during the rush. Open Lines answers your restaurant phone 24/7, takes bookings, and answers hours & menu questions.',
  alternates: { canonical: '/restaurants' },
  openGraph: {
    title: 'AI Receptionist for Restaurants',
    description: 'Take reservations, answer FAQs, and capture large parties — 24/7, even mid-service.',
    url: 'https://www.openlines.ai/restaurants',
    images: [OG],
  },
}

const RESTAURANTS: VerticalContent = {
  slug: 'restaurants',
  name: 'AI Receptionist for Restaurants',
  shortName: 'Restaurants',
  eyebrow: 'For Restaurants & Cafés',
  h1: 'The phone rings through dinner service. Nobody can grab it.',
  subhead:
    'Open Lines is an AI receptionist that answers every call during the rush — taking reservations, answering hours and menu questions, and capturing large-party and catering enquiries, so your team stays on the floor.',
  trustline: 'Live in under 10 minutes · Answers 24/7 · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'Every unanswered call during service is a table you didn’t fill.',
  pains: [
    { stat: 'Peak hours', title: 'Nobody can stop to answer', body: 'When the room is full, the phone is the last thing your team can pick up — and the caller books elsewhere.' },
    { stat: 'Same questions', title: 'The phone asks the same things', body: '“Are you open?” “Do you take walk-ins?” “Is there parking?” — answered a hundred times a night, off the floor.' },
    { stat: 'Big parties', title: 'Large bookings slip away', body: 'Group dinners and catering are your best revenue — and the calls come in when no one’s free to take them.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'A host for the phone, so your team stays on the floor.',
  solutionSub: 'It answers in a warm, natural voice, takes reservations, answers the questions callers ask on repeat, and captures large-party and catering enquiries — 24/7, even mid-service.',
  features: [
    { icon: '📅', title: 'Takes reservations', body: 'Captures date, party size, and name, and books the reservation — or drops it into your calendar for the front of house.' },
    { icon: '💬', title: 'Answers the FAQs', body: '“What are your hours?” “Do you have vegan options?” “Is there parking?” — answered instantly from your own site.' },
    { icon: '🎉', title: 'Captures large parties & events', body: 'Group dinners, private events, and catering enquiries are captured cleanly and sent straight to you.' },
    { icon: '🌙', title: 'Answers after close', body: 'People plan dinner late at night. The AI books the reservation while your lights are off.' },
    { icon: '📞', title: 'Handles the overflow', body: 'When every line is busy mid-rush, it picks up the calls your team simply can’t.' },
    { icon: '✉️', title: 'Sends you every enquiry', body: 'Reservations and event enquiries arrive as a clean summary so nothing gets missed in the weeds.' },
  ],

  setup: {
    heading: 'What we configure for restaurants',
    intro: 'Your AI receptionist is tuned to the rhythm of service — protecting the floor from the phone while never dropping a booking.',
    points: [
      { title: 'Reservations & large parties', body: 'It takes standard bookings, and routes big-group, private-event, and catering enquiries to you as priority — the revenue you can’t afford to miss.' },
      { title: 'Dietary & FAQ answers', body: 'Hours, parking, walk-ins, vegan/gluten-free options and allergen questions are answered straight from your own site, so the team isn’t pulled off the floor.' },
      { title: 'Peak-hour overflow', body: 'When every line is busy mid-service, it picks up the overflow so callers reach a friendly voice instead of a busy signal.' },
    ],
  },
  intake: {
    heading: 'Example reservation intake',
    fields: [
      'Reservation date and time',
      'Party size',
      'Guest name and phone',
      'Dietary / allergy notes',
      'Occasion (event, large party)',
      'Any special requests',
    ],
  },

  demoMock: { name: 'S. Alvarez', service: 'Dinner reservation · party of 6', when: 'Sat 7:30 PM' },
  textback: { business: 'Cedar & Salt', reply: 'Do you have a table for six this Saturday evening?' },

  integrationsHeading: 'Works with the calendar you already run.',
  integrations: ['Google Calendar', 'Outlook'],

  faqs: [
    { q: 'Can it take reservations?', a: 'Yes. It captures the date, party size, and guest name and books the reservation — or routes it to your front of house with a clean summary.' },
    { q: 'Does it answer menu and hours questions?', a: 'It answers the questions callers ask on repeat — hours, parking, dietary options, walk-ins — straight from your own website, so your team isn’t pulled off the floor.' },
    { q: 'What about large parties and catering?', a: 'Group dinners, private events, and catering enquiries are captured cleanly and sent to you right away, so your highest-value bookings don’t slip.' },
    { q: 'Can it handle the phone during the rush?', a: 'That’s the point — when every line is busy mid-service it picks up the overflow, so callers get a warm voice instead of a busy signal.' },
    { q: 'What does it sound like?', a: 'A warm, natural human voice. It always discloses that it’s a virtual assistant, and it answers 24/7 — even after you close.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/google-calendar', label: 'Send reservations to Google Calendar', sub: 'Front-of-house sees every booking.' },
      { href: '/integrations/stripe', label: 'Take deposits on large parties', sub: 'Cut no-shows with a secure Stripe link.' },
    ],
    guides: [
      { href: '/learn/missed-call-text-back', label: 'Turn missed calls into filled tables', sub: 'Why answering live wins the booking.' },
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'How it answers and books.' },
    ],
  },

  ctaHeading: 'Stop letting the phone ring through service.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it answer, book, and capture events while your team runs the room.',
}

export default function RestaurantsPage() {
  return <VerticalLanding content={RESTAURANTS} />
}
