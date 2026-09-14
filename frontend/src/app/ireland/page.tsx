import type { Metadata } from 'next'
import VerticalLanding, { type VerticalContent } from '../components/VerticalLanding'
import { ogImageUrl } from '@/lib/og-card'

const OG = ogImageUrl({ eyebrow: 'For Irish Businesses', title: 'An Irish number takes a filing. Here is exactly what it needs.', benefit: 'Test free while it clears. Your trial starts when the +353 goes live.' })

export const metadata: Metadata = {
  title: 'AI Receptionist for Irish Businesses | Open Lines',
  description: 'Irish numbers require a regulatory filing — nine details and a proof of address. Here is the full list, what the wait involves, and why your paid trial does not start until your +353 is live.',
  alternates: { canonical: '/ireland' },
  openGraph: {
    title: 'AI Receptionist for Irish Businesses',
    description: 'The exact regulatory requirements for a +353 number, and free testing while yours clears.',
    url: 'https://www.openlines.ai/ireland',
    images: [OG],
  },
}

const IRELAND: VerticalContent = {
  slug: 'ireland',
  name: 'AI Receptionist for Irish Businesses',
  shortName: 'Ireland',
  eyebrow: 'For Irish Businesses',
  h1: 'An Irish number takes a filing. Here is exactly what it needs.',
  subhead:
    'Ireland is the one country we serve where you cannot simply be given a number. A regulator has to be satisfied first. Most providers are vague about that; below is the actual list of what is asked for, what the wait involves, and what you can do in the meantime.',
  trustline: 'Nine details and a proof of address · Free testing while it clears · Trial starts when your +353 is live',
  heroArt: 'call',

  painsLabel: 'Before you start',
  painsHeading: 'What makes Ireland different',
  pains: [
    { stat: '9', title: 'Details the regulator asks for', body: 'Not a form we invented. Irish local business numbering carries a defined set of end-user details, and every one of them has to be supplied before a number can be issued.' },
    { stat: '1', title: 'Supporting document', body: 'A proof of address for the business. This is the item most likely to send a filing back, because the address has to match what is on the document rather than what is on your website.' },
    { stat: 'Days', title: 'A wait nobody controls', body: 'The review is the regulator’s and the carrier’s, not ours. Anyone promising you a same-day Irish number is describing a country other than Ireland.' },
  ],

  solutionLabel: 'How it works here',
  solutionHeading: 'Answering calls before the filing clears',
  solutionSub: 'The wait applies to the permanent Irish number, not to everything else. The rest is set up while the review runs.',
  features: [
    { icon: '📞', title: 'A free test line in the meantime', body: 'While a genuine review is pending you get a temporary number to try the whole thing on. Calls to it are accounted separately and never reach your bill.' },
    { icon: '⏳', title: 'Your trial waits for your number', body: 'The seven days do not begin at signup, at the card, at the filing, or when the test line starts working. They begin when your permanent +353 is live and verified at the provider — so you never spend trial days waiting on a regulator.' },
    { icon: '📅', title: 'Everything else set up now', body: 'Your website read, calendar connected, answers written, notifications pointed where you want them. None of that waits on the filing.' },
    { icon: '🇮🇪', title: 'Or forward the number you have', body: 'If you already hold an Irish number with a carrier, forwarding it sidesteps the issuing question entirely and works immediately.' },
  ],

  setup: {
    heading: 'Exactly what the filing asks for',
    intro: 'Verified against the carrier’s regulation for Irish local business numbers. These requirements are set by the provider and can change, so this is what is asked for today rather than a promise about next quarter — but it has been stable, and it is what you should gather before starting.',
    points: [
      { title: 'About the business: four items', body: 'Registered business name, business website, business registration number, and a business identity declaration. The registration number is the CRO number for most Irish companies — have it to hand rather than looking it up mid-form.' },
      { title: 'About you: three items', body: 'First name, last name and an email address for the person making the filing. This should be somebody who can answer a query about it, not a shared inbox nobody watches.' },
      { title: 'Two administrative items', body: 'Whether the number is being sub-assigned, and a free-text comments field. Both are straightforward, and the comments field is where anything unusual about your setup should be explained rather than left to be guessed at.' },
      { title: 'One document: proof of address', body: 'A document evidencing the business address. This is the single most common cause of a rejected filing — the address on the document must match the address you entered, including the parts people abbreviate.' },
    ],
  },

  intake: {
    heading: 'Have these ready before you begin',
    fields: ['Registered business name, exactly as filed', 'CRO or business registration number', 'Business website address', 'Proof of address document', 'Name and email of whoever is filing', 'The business address, matching the document'],
  },

  demoMock: { name: 'Aoife Brennan', service: 'Consultation', when: 'Tuesday 11:00 AM', with: 'Dani' },
  textback: { business: 'Sorry we missed you — this is Open Lines answering for Corrib Dental.', reply: 'Looking to book a check-up' },

  integrationsHeading: 'Works with what you already use',
  integrations: ['Square Appointments', 'Google Calendar', 'Outlook & Microsoft 365', 'HubSpot', 'Slack', 'Stripe'],

  faqs: [
    { q: 'Why does an Irish number need a regulatory filing?', a: 'Irish local business numbering carries end-user requirements set by the regulator and enforced by the carrier. It is not a policy of ours and it is not something any provider can waive — if one tells you otherwise, ask what number they are actually selling you.' },
    { q: 'What exactly is asked for?', a: 'Nine details — registered business name, business website, business registration number, a business identity declaration, your first and last name, an email address, whether the number is sub-assigned, and a comments field — plus one supporting document evidencing your business address.' },
    { q: 'How long does it take?', a: 'Days rather than minutes, and the timing belongs to the regulator and the carrier rather than to us. We will not give you a figure we cannot control, which is why the trial is structured so the wait does not cost you anything.' },
    { q: 'What causes a filing to be rejected?', a: 'Most often the proof of address — the address on the document not matching the address entered. Check that before submitting, including the parts people shorten.' },
    { q: 'Can I do anything while I am waiting?', a: 'Yes. You get a temporary test number to try the whole thing on, and calls to it are accounted separately and never reach your bill. Your website, calendar, answers and notifications are all set up during the wait.' },
    { q: 'When does my paid trial start?', a: 'Only once your permanent +353 is live, with approval confirmed directly at the provider. Not at signup, not when you enter a card, not when the filing goes in, and not when the test line starts working.' },
    { q: 'Can I use my existing Irish number instead?', a: 'Yes, and it is the fastest route. Forwarding a number you already hold with an Irish carrier avoids the issuing question altogether and works straight away.' },
    { q: 'Is this different from the UK?', a: 'Yes. A UK number asks for a registered business address; Ireland asks for a full set of business identity details and a supporting document. Canada and the United States ask for nothing at all.' },
  ],

  related: {
    integrations: [
      { href: '/integrations/square-appointments', label: 'Square Appointments', sub: 'Services, staff and branches.' },
      { href: '/integrations/google-calendar', label: 'Google Calendar', sub: 'One diary, one copy.' },
    ],
    guides: [
      { href: '/learn/irish-business-phone-number', label: 'The Ireland guide', sub: 'The wait, and where it goes wrong.' },
      { href: '/learn/what-happens-to-your-number-if-you-leave', label: 'If you leave', sub: 'What happens to the number.' },
      { href: '/learn/keep-your-business-phone-number', label: 'Forwarding instead', sub: 'The immediate route.' },
    ],
  },

  ctaHeading: 'Start the filing, test it free while it clears.',
  ctaSub: 'Gather the nine details and your proof of address, and your seven days begin when your +353 does — not before.',
}

export default function IrelandPage() {
  return <VerticalLanding content={IRELAND} />
}
