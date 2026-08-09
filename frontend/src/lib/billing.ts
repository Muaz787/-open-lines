// Single source of truth for how the admin UI classifies a tenant's billing state.
//
// Two states are NOT Stripe subscription statuses and must be DERIVED:
//   - Free trial: card-free, so there is no Stripe subscription during it and
//     `subscription_status` stays null/'none'. It's derived from created_at.
//   - Comp: billing_exempt tenants (live line, no charge), regardless of status.
// Reading `subscription_status` alone (as the revenue route + tenant detail used
// to) shows a free-trial tenant as "none"/"no subscription" — the bug this fixes.
//
// There are now TWO kinds of trial and both must be kept out of revenue:
//   - 'trial'    — legacy card-free trial, derived from created_at (no Stripe sub)
//   - 'trialing' — card trial, a real Stripe subscription in `trialing` status
// Use isTrial() rather than comparing to either string, so a caller can't count
// one kind and silently miss the other.

export const TRIAL_DAYS = 7

export function withinTrial(created: string | null | undefined): boolean {
  if (!created) return false
  return Date.now() - new Date(created).getTime() < TRIAL_DAYS * 86_400_000
}

export interface BillingTenant {
  subscription_status: string | null
  billing_exempt?: boolean | null
  created_at: string
}

// Returns: 'comped' | 'active' | 'trialing' | 'past_due' | 'canceled'
//        | 'trial' (legacy card-free trial) | 'expired' (trial lapsed, never subscribed)
export function billingStatus(t: BillingTenant): string {
  if (t.billing_exempt) return 'comped'
  if (t.subscription_status && t.subscription_status !== 'none') return t.subscription_status
  return withinTrial(t.created_at) ? 'trial' : 'expired'
}

/** True for either trial kind. Neither contributes revenue. */
export function isTrial(status: string): boolean {
  return status === 'trial' || status === 'trialing'
}

/** True only for tenants actually paying — the set MRR is summed over. */
export function isPaying(status: string): boolean {
  return status === 'active'
}
