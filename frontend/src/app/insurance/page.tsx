import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'

export const metadata: Metadata = {
  title: 'AI Receptionist for Insurance Brokers & Agencies — Open Lines',
  description: 'Never miss a quote request. Open Lines answers your insurance agency’s phone 24/7, takes new-quote and policy intake, flags claims, and books callbacks with a licensed advisor. 7-day free trial — no credit card.',
  alternates: { canonical: '/insurance' },
}

const INSURANCE: VerticalContent = {
  slug: 'insurance',
  eyebrow: 'For Insurance Brokers & Agencies',
  h1: 'A quote request on hold is a quote request lost.',
  subhead:
    'Open Lines is an AI receptionist that answers every call while your advisors are on the line — taking new-quote and policy intake, flagging claims for priority, and booking callbacks with a licensed advisor.',
  trustline: 'Live in under 10 minutes · Books into Google & Outlook · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'Shoppers call three brokers. Only the one who answers gets the quote.',
  pains: [
    { stat: 'On the phone', title: 'Advisors are already on calls', body: 'Your licensed team is busy with existing clients. New-quote calls ring out and the shopper moves on.' },
    { stat: 'Claim panic', title: 'Claims call in stressed', body: 'A client after an accident needs to reach someone now. Voicemail is exactly the wrong answer.' },
    { stat: 'After hours', title: 'Quotes get shopped in the evening', body: 'People compare insurance after work. If no one picks up, the next agency writes the policy.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'Intake handled, claims flagged, callbacks booked.',
  solutionSub: 'It answers in a professional, natural voice, takes new-quote and policy intake, flags claims as priority, and books a callback with a licensed advisor — 24/7. It captures details; it never gives regulated advice or binds coverage.',
  features: [
    { icon: '📋', title: 'Takes new-quote intake', body: 'Captures the coverage type, key details, and contact info so an advisor can prepare the quote before calling back.' },
    { icon: '🚨', title: 'Flags claims for priority', body: 'Callers reporting a claim are marked urgent and routed for a fast callback — no one waits on hold in a crisis.' },
    { icon: '📅', title: 'Books advisor callbacks', body: 'Schedules a callback with a licensed advisor straight into your Google or Outlook calendar.' },
    { icon: '💬', title: 'Answers common questions', body: '“Do you write commercial?” “What do you need for a home quote?” “Where are you located?” — from your site.' },
    { icon: '🌙', title: 'Covers after hours', body: 'The evening and weekend quote-shoppers you’re missing today become booked callbacks for your team.' },
    { icon: '✉️', title: 'Summarizes every call', body: 'A structured summary of each caller — coverage type, urgency, and next step — lands in your inbox and CRM.' },
  ],

  demoMock: { name: 'P. Nowak', service: 'Auto quote callback', when: 'Thu 11:00 AM' },
  textback: { business: 'Northgate Insurance', reply: 'I’m looking for a quote on home and auto — can someone call me back?' },

  integrationsHeading: 'Works with the calendar and CRM you already run.',
  integrations: ['Google Calendar', 'Outlook', 'HubSpot'],

  faqs: [
    { q: 'Does it give insurance advice or bind coverage?', a: 'No. It handles intake and scheduling only — it captures the caller’s details and books a callback with a licensed advisor. It never gives regulated advice or binds coverage.' },
    { q: 'How does it handle claims?', a: 'Callers reporting a claim are flagged as urgent and routed for a priority callback, so no one is left waiting on hold after an accident.' },
    { q: 'Where does the intake go?', a: 'You get a structured summary after every call — coverage type, details, urgency, and next step — and it can sync to HubSpot as a contact and note.' },
    { q: 'What does it sound like?', a: 'A calm, professional human voice. It always discloses that it’s a virtual assistant and books callbacks into your live calendar.' },
  ],

  ctaHeading: 'Stop letting quote requests ring out.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it take intake and book callbacks while your advisors focus on clients.',
}

export default function InsurancePage() {
  return <VerticalLanding content={INSURANCE} />
}
