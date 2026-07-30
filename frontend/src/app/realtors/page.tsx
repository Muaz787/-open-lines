import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For Real Estate Agents', title: 'The lead that goes to voicemail goes to another agent.', benefit: 'Answers in one ring, qualifies, and texts back.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Real Estate Agents | Open Lines',
  description: 'The lead that goes to voicemail goes to another agent. Open Lines answers in one ring, qualifies the lead, and texts a confirmation instantly.',
  alternates: { canonical: '/realtors' },
  openGraph: {
    title: 'AI Receptionist for Real Estate Agents',
    description: 'Answer in one ring, qualify the lead, and text a confirmation the moment the call ends.',
    url: 'https://www.openlines.ai/realtors',
    images: [OG],
  },
}

const REALTORS: VerticalContent = {
  slug: 'realtors',
  name: 'AI Receptionist for Real Estate Agents',
  shortName: 'Real Estate',
  eyebrow: 'For Real Estate Agents & Brokers',
  h1: 'The lead that goes to voicemail goes to another agent.',
  subhead:
    'You’re at a showing, on the highway, in a closing. Open Lines answers every call in one ring, qualifies the lead, and texts them a confirmation the moment the call ends — so a five-figure commission never slips away because you couldn’t pick up.',
  trustline: 'Answers every call in one ring, 24/7 · Texts a confirmation after every call · Cancel anytime',
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
    { icon: '📲', title: 'Instant text confirmation', body: 'The AI answers, captures the lead, then texts the caller a confirmation in your name — so they know you’re on it and don’t call the next agent.' },
    { icon: '🎯', title: 'Qualifies the lead', body: 'Buy or sell, timeline, budget, pre-approval status and target area — captured on the call.' },
    { icon: '📅', title: 'Books showings & consults', body: 'Drops buyer and seller appointments straight into your Google or Outlook calendar.' },
    { icon: '🔥', title: 'Routes hot leads to you', body: 'Serious, time-sensitive leads are flagged and pushed to your cell right away.' },
    { icon: '🔗', title: 'Pushes leads to HubSpot', body: 'Every qualified lead lands in HubSpot automatically, plus an email and optional Slack alert — no manual entry.' },
  ],

  setup: {
    heading: 'What we configure for real estate agents',
    intro: 'Your AI receptionist is tuned to win the speed-to-lead race — answering instantly, qualifying, and getting hot leads to your cell.',
    points: [
      { title: 'Instant lead qualification', body: 'It captures intent (buy or sell), timeline, budget, pre-approval status, and target area on the call, so you follow up with the full picture.' },
      { title: 'Hot-lead routing', body: 'Serious, time-sensitive leads are flagged and pushed to your cell right away — plus an optional Slack alert for your team.' },
      { title: 'Text-back that holds the lead', body: 'It texts the caller a confirmation in your name the moment the call ends, so they stop shopping the next agent.' },
    ],
  },
  intake: {
    heading: 'Example lead intake',
    fields: [
      'Buying or selling',
      'Target area / property of interest',
      'Timeline to move',
      'Budget range',
      'Pre-approval status',
      'Contact name and phone',
    ],
  },

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

  related: {
    integrations: [
      { href: '/integrations/hubspot', label: 'Push leads to HubSpot', sub: 'Contact + call summary, automatically.' },
      { href: '/integrations/slack', label: 'Get hot-lead alerts in Slack', sub: 'Your team sees every lead instantly.' },
      { href: '/integrations/google-calendar', label: 'Book showings into Google Calendar', sub: 'Live availability, no clashes.' },
    ],
    guides: [
      { href: '/learn/missed-call-text-back', label: 'Missed-call text-back for agents', sub: 'Win the speed-to-lead race.' },
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'How it answers and qualifies.' },
    ],
  },

  ctaHeading: 'Never lose another commission to voicemail.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and answer every lead — even when you’re showing the next house.',
}

export default function RealtorsPage() {
  return <VerticalLanding content={REALTORS} />
}
