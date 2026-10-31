// The one place that turns a tenant's account state into dashboard wording. Having
// a plan and paying for it are separate facts, so nothing here calls an account
// subscribed unless a provider subscription exists. See services/account_state.py.

export interface Account {
  plan: string | null
  source: 'subscription' | 'manual' | 'complimentary' | 'trial' | 'none'
  subscription: 'none' | 'trialing' | 'active' | 'past_due' | 'canceling' | 'canceled'
  has_provider_subscription: boolean
  line_active: boolean
  pending_activation: boolean
}

// What /billing/subscription-details found at Stripe.
export type ProviderState = 'ok' | 'none' | 'missing' | 'unavailable'

export type StatusTone = 'success' | 'warn' | 'danger' | 'neutral'

export interface AccountView {
  planLabel: string
  statusLabel: string | null
  tone: StatusTone
  // Offer plans to choose. False while loading, so nobody is told to buy a plan
  // they already have because a request is slow.
  needsPlan: boolean
  // Shown on Billing in place of plan details when there is nothing to manage.
  billingNotice: { title: string; body: string } | null
}

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

const UNKNOWN: AccountView = {
  planLabel: 'Plan unavailable',
  statusLabel: null,
  tone: 'neutral',
  needsPlan: false,
  billingNotice: {
    title: 'We couldn’t load your plan',
    body: 'This doesn’t change your account. Try again in a moment.',
  },
}

const LOADING: AccountView = { ...UNKNOWN, planLabel: '', billingNotice: null }

export function presentAccount(
  account: Account | null | undefined,
  state: 'loading' | 'ready' | 'error',
  provider?: ProviderState,
): AccountView {
  if (state === 'loading') return LOADING
  if (state === 'error' || !account) return UNKNOWN

  const plan = account.plan ? capitalize(account.plan) : null

  // The tenant row says subscribed, but Stripe has no such subscription.
  if (provider === 'missing') {
    return {
      planLabel: plan ? `${plan} plan` : 'Plan',
      statusLabel: 'Needs review',
      tone: 'warn',
      needsPlan: false,
      billingNotice: {
        title: 'We couldn’t find your subscription',
        body: 'Our billing provider has no subscription for this account. Please contact support@openlines.ai before choosing a plan, so you aren’t billed twice.',
      },
    }
  }

  if (account.source === 'complimentary') {
    return {
      planLabel: plan ? `${plan} (complimentary)` : 'Complimentary',
      statusLabel: 'Complimentary',
      tone: 'success',
      needsPlan: false,
      billingNotice: {
        title: 'Complimentary account',
        body: 'Open Lines provides this account at no charge, so there’s no paid subscription to manage.',
      },
    }
  }

  if (account.source === 'manual') {
    return {
      planLabel: plan ? `${plan} (manual access)` : 'Manual access',
      statusLabel: 'Manual',
      tone: 'neutral',
      needsPlan: false,
      billingNotice: {
        title: 'No paid subscription',
        body: `${plan ? `${plan} features were` : 'Access was'} set up on this account by Open Lines. There’s no paid subscription, so there’s nothing to manage here.`,
      },
    }
  }

  if (account.source === 'subscription') {
    const label = plan ? `${plan} plan` : 'Plan'
    switch (account.subscription) {
      case 'trialing':
        return { planLabel: plan ? `${plan} trial` : 'Free trial', statusLabel: 'Trial', tone: 'neutral', needsPlan: false, billingNotice: null }
      case 'active':
        return { planLabel: label, statusLabel: 'Active', tone: 'success', needsPlan: false, billingNotice: null }
      case 'canceling':
        return { planLabel: label, statusLabel: 'Canceling', tone: 'warn', needsPlan: false, billingNotice: null }
      case 'past_due':
        return { planLabel: label, statusLabel: 'Past due', tone: 'danger', needsPlan: false, billingNotice: null }
    }
    return { planLabel: 'No active plan', statusLabel: 'Canceled', tone: 'neutral', needsPlan: true, billingNotice: null }
  }

  if (account.source === 'trial') {
    return { planLabel: 'Free trial', statusLabel: 'Trial', tone: 'neutral', needsPlan: true, billingNotice: null }
  }

  if (account.pending_activation) {
    return { planLabel: 'Awaiting activation', statusLabel: null, tone: 'neutral', needsPlan: false, billingNotice: null }
  }

  return { planLabel: 'No active plan', statusLabel: null, tone: 'neutral', needsPlan: true, billingNotice: null }
}
