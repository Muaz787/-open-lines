import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'

export const metadata: Metadata = {
  title: 'AI Receptionist for Real Estate Agents — Open Lines',
  description: 'The lead that goes to voicemail goes to another agent. Open Lines answers every call in one ring, qualifies the lead, and texts back instantly on missed calls. Start a 7-day free trial — no credit card.',
  alternates: { canonical: '/realtors' },
}

const REALTORS: VerticalContent = {
  slug: 'realtors',
  eyebrow: 'For Real Estate Agents & Brokers',
  h1: 'The lead that goes to voicemail goes to another agent.',
  subhead:
    'You’re at a showing, on the highway, in a closing. Open Lines answers every call in one ring, qualifies the lead, and texts them back instantly — so a five-figure commission never slips away because you couldn’t pick up.',
  trustline: 'Answers in one ring, 24/7 · Instant missed-call text-back · Cancel anytime',
  heroArt: 'textback',

  painsLabel: 'The real cost',
  painsHeading: 'You can’t be on the road and on the phone.',
  pains: [
    { stat: '78%', title: 'First to respond wins', body: 'Most buyers work with the first agent who answers. Miss the call and the lead is gone before your voicemail even beeps.' },
    { stat: '$10k+', title: 'Walks with every miss', body: 'One buyer or listing lead can be a five-figure commission. Voicemail doesn’t sell homes — a fast response does.' },
    { stat: '9pm Zillow', title: 'Leads come at the worst time', body: 'Showings, open houses, dinner, late-night portal inquiries — your phone rings exactly when you can’t answer it.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'An AI inside sales agent that never misses a lead.',
  solutionSub: 'Open Lines picks up on the first ring, finds out what the caller needs, and gets the details to you and your CRM — day or night, showing or not.',
  features: [
    { icon: '📞', title: 'Answers in one ring, 24/7', body: 'Every call is picked up instantly — even when you’re mid-showing or your line is busy.' },
    { icon: '📲', title: 'Instant missed-call text-back', body: 'If a call is missed, the lead gets an immediate SMS in your name — so they never go cold or call the next agent.' },
    { icon: '🎯', title: 'Qualifies the lead', body: 'Buy or sell, timeline, budget, pre-approval status and target area — captured on the call.' },
    { icon: '📅', title: 'Books showings & consults', body: 'Drops buyer and seller appointments straight into your Google or Outlook calendar.' },
    { icon: '🔥', title: 'Routes hot leads to you', body: 'Serious, time-sensitive leads are flagged and pushed to your cell right away.' },
    { icon: '🔗', title: 'Pushes leads to HubSpot', body: 'Every qualified lead lands in HubSpot automatically, plus an email and optional Slack alert — no manual entry.' },
  ],

  demoMock: { name: 'Buyer lead', service: 'Buyer consultation', when: 'Wed 5:15 PM', with: 'you' },
  textback: { business: 'The Reyes Group', reply: 'Hi, is the 3-bed on Maple St still available? I’d love to see it.' },

  integrationsHeading: 'Plugs into the tools you already run.',
  integrations: ['Google Calendar', 'Outlook', 'HubSpot', 'Slack'],

  faqs: [
    { q: 'Does it really text back missed calls?', a: 'Yes — the moment a call is missed, the lead gets an SMS in your business name, so they know you’re on it instead of moving to the next agent.' },
    { q: 'Can it qualify leads?', a: 'It captures intent (buy/sell), timeline, budget, pre-approval status and target area, then hands you a clean summary.' },
    { q: 'Does it connect to my CRM?', a: 'It pushes qualified leads into HubSpot automatically, and emails you a full summary after every call so nothing needs manual entry.' },
    { q: 'Will callers know it’s AI?', a: 'It sounds natural and professional, and always discloses that it’s a virtual assistant, as required.' },
  ],

  ctaHeading: 'Never lose another commission to voicemail.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and answer every lead — even when you’re showing the next house.',
}

export default function RealtorsPage() {
  return <VerticalLanding content={REALTORS} />
}
