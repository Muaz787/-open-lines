/* Single source of truth for subscription plans.
 *
 * Shared by BOTH the public pricing page (app/pricing/PricingCards.tsx) and the
 * in-dashboard "Choose a plan" billing section
 * (app/dashboard/[tenantId]/subscription/page.tsx). Update plans HERE and both
 * surfaces stay in sync automatically — each derives its own display format
 * (marketing theme vs. dashboard db-* theme) from this data.
 *
 * `features` are the feature bullets only; the included-minutes line is NOT a
 * feature — each surface renders minutes separately from the `minutes` field.
 */

export type PlanId = 'starter' | 'pro' | 'business'

export interface Plan {
  id: PlanId
  name: string
  /** Monthly price, USD. */
  price: number
  /** Annual price, USD (2 months free). */
  priceYear: number
  /** Annual saving vs. paying monthly, USD. */
  saveYear: number
  /** Included minutes per month. */
  minutes: number
  /** Highlighted as the recommended plan (pricing page). */
  popular: boolean
  /** Card accent — pricing page only. */
  accent: string
  /** Per-minute overage note. */
  note: string
  features: string[]
}

export const PLANS: Plan[] = [
  {
    id: 'starter',
    name: 'Starter',
    price: 99,
    priceYear: 990,
    saveYear: 198,
    minutes: 150,
    popular: false,
    accent: 'var(--border-2)',
    note: '$0.69 / min overage',
    features: [
      '1 dedicated AI phone line',
      '24/7 AI call answering',
      'Lead capture, qualification & caller recognition',
      'Appointment booking — Google & Outlook Calendar',
      'Book with a specific team member',
      'Transcripts, AI summaries & call insights',
      'SMS confirmations + email, SMS & WhatsApp alerts',
      'Knowledge base — 10 MB / 50-page docs, scanned-doc OCR',
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    price: 199,
    priceYear: 1990,
    saveYear: 398,
    minutes: 400,
    popular: true,
    accent: 'var(--accent)',
    note: '$0.69 / min overage',
    features: [
      'Everything in Starter',
      'AI call routing & overflow — warm-transfer callers to your team',
      'Deposit collection — Stripe & Square',
      'Group & per-person deposits',
      'HubSpot CRM sync',
      'Slack notifications',
      'Larger knowledge base — 25 MB / 300-page docs',
    ],
  },
  {
    id: 'business',
    name: 'Business',
    price: 379,
    priceYear: 3790,
    saveYear: 758,
    minutes: 900,
    popular: false,
    accent: '#3B7EF6',
    note: '$0.69 / min overage',
    features: [
      'Everything in Pro',
      'Call routing at scale — up to 50 destinations & rules',
      'Largest knowledge base — 50 MB / 1,000-page docs',
      'Priority support',
      'Dedicated onboarding & setup',
      'Early access to new features',
    ],
  },
]
