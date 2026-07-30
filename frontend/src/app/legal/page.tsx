import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For Law Firms', title: 'A missed call is a client who dials the next firm.', benefit: 'Intake and consultations, handled 24/7.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Law Firms | Open Lines',
  description: 'Answer every call 24/7, run new-client intake, and book consultations into your calendar. The AI captures the matter — it never gives legal advice.',
  alternates: { canonical: '/legal' },
  openGraph: {
    title: 'AI Receptionist for Law Firms',
    description: 'Answer every call, run intake, and book consultations 24/7 — without a full-time receptionist.',
    url: 'https://www.openlines.ai/legal',
    images: [OG],
  },
}

const LEGAL: VerticalContent = {
  slug: 'legal',
  name: 'AI Receptionist for Law Firms',
  shortName: 'Law Firms',
  eyebrow: 'For Law Firms & Solo Practitioners',
  h1: 'A missed call is a client who dials the next firm.',
  subhead:
    'Open Lines is an AI receptionist that answers every call while you’re in court, in a meeting, or after hours — running new-client intake and booking consultations straight into your calendar. It captures the matter; it never gives legal advice.',
  trustline: 'Live in under 10 minutes · Books into Google & Outlook · Cancel anytime',
  heroArt: 'call',

  painsLabel: 'The real cost',
  painsHeading: 'Legal clients don’t leave a message — they hire whoever answers.',
  pains: [
    { stat: 'In court', title: 'You can’t pick up mid-hearing', body: 'When you’re in front of a judge or with a client, the phone rings out — and a potential retainer walks.' },
    { stat: 'After 5pm', title: 'Intake happens after hours', body: 'People deal with legal problems in the evening. If no one answers, the next firm on Google does.' },
    { stat: '$45k+/yr', title: 'A front desk is expensive', body: 'A full-time receptionist costs more than most solo and small firms want to carry — so calls go unanswered.' },
  ],

  solutionLabel: 'The fix',
  solutionHeading: 'Intake handled like a trained legal receptionist.',
  solutionSub: 'It answers in a professional, natural voice, captures the caller’s matter and contact details, screens the type of case, and books the consultation — 24/7. It stays strictly to intake and scheduling and never offers legal advice.',
  features: [
    { icon: '📋', title: 'Runs new-client intake', body: 'Captures name, contact details, the nature of the matter, and key dates — structured and ready in your inbox.' },
    { icon: '⚖️', title: 'Screens the matter type', body: 'Identifies the practice area (family, real estate, personal injury, business) so the right person follows up.' },
    { icon: '📅', title: 'Books consultations', body: 'Schedules intro calls and consultations into your Google or Outlook calendar with real availability.' },
    { icon: '🚨', title: 'Flags urgent matters', body: 'Time-sensitive matters get marked as urgent so you can call back before a deadline passes.' },
    { icon: '💬', title: 'Answers common questions', body: '“Do you handle wills?” “Do you offer free consultations?” “Where are you located?” — answered from your own site.' },
    { icon: '✉️', title: 'Summarizes every call', body: 'You get a clean, structured summary of each caller — matter, urgency, and suggested next step.' },
  ],

  setup: {
    heading: 'What we configure for law firms',
    intro: 'Your AI receptionist is tuned to the way legal intake actually works — capturing what a paralegal would, while staying firmly inside ethical lines.',
    points: [
      { title: 'Conflict-check capture', body: 'It records the opposing party and key names on the call so your team can run a conflicts check before you agree to act — it never confirms representation itself.' },
      { title: 'Deadline & urgency flags', body: 'Limitation dates, court dates, and “I was served today” trigger an urgent flag so time-sensitive matters reach you fast.' },
      { title: 'Strict ethical boundaries', body: 'It answers factual questions from your site, takes intake, and books — but never gives legal advice, quotes outcomes, or forms a solicitor-client relationship.' },
    ],
  },
  intake: {
    heading: 'Example legal intake',
    fields: [
      'Caller name and contact details',
      'Practice area / type of matter',
      'Short description of the matter',
      'Any deadline or court date',
      'Opposing party (for conflict checks)',
      'Preferred consultation time',
    ],
  },

  demoMock: { name: 'D. Okafor', service: 'Initial consultation', when: 'Wed 10:00 AM' },
  textback: { business: 'Harbourline Law', reply: 'I need to speak to someone about a family matter — is there availability this week?' },

  integrationsHeading: 'Fits the calendar and tools your practice already runs.',
  integrations: ['Google Calendar', 'Outlook', 'HubSpot'],

  faqs: [
    { q: 'Does it give legal advice?', a: 'No — and that’s deliberate. It handles intake and scheduling only, captures the details of the matter, and routes the caller to you. It never offers legal opinions or advice.' },
    { q: 'Can it screen the type of case?', a: 'Yes. It identifies the practice area and the nature of the matter so the right lawyer follows up, and flags anything time-sensitive as urgent.' },
    { q: 'Can it help with conflict checks?', a: 'It captures the opposing party and key names on the call so your team can run a conflicts check before agreeing to act. It does not confirm representation itself.' },
    { q: 'Where does the intake go?', a: 'You get a structured summary by email after every call — name, contact, matter, urgency, and suggested next step — and it can sync to HubSpot as a contact and note.' },
    { q: 'What does it sound like?', a: 'A calm, professional human voice. It always discloses that it’s a virtual assistant, as required, and books consultations into your live calendar.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/google-calendar', label: 'Book consultations into Google Calendar', sub: 'Real-time availability, no double-booking.' },
      { href: '/integrations/outlook', label: 'Book into Outlook & Microsoft 365', sub: 'For firms on Microsoft.' },
      { href: '/integrations/hubspot', label: 'Log every caller to HubSpot', sub: 'Contact + call summary, automatically.' },
    ],
    guides: [
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'How it answers, screens, and books.' },
      { href: '/learn/answering-service-cost', label: 'What does an answering service cost?', sub: '2026 pricing compared.' },
    ],
  },

  ctaHeading: 'Stop sending new clients to voicemail.',
  ctaSub: 'Set up your AI receptionist in under 10 minutes and let it run intake and book consultations while you focus on your cases.',
}

export default function LegalPage() {
  return <VerticalLanding content={LEGAL} />
}
