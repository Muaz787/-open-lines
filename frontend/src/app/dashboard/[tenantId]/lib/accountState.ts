// The one place that turns a tenant's account state into dashboard wording. Three
// facts stay separate here, each with its own label, because one says nothing about
// the others: a line can work while billing is unverified. Nothing is called paid
// unless a direct Stripe lookup confirmed it. See services/account_state.py.

export interface Account {
  plan: string | null
  feature_plan: string | null
  phone_line: 'on' | 'off' | 'none'
  source: 'subscription' | 'manual' | 'complimentary' | 'trial' | 'none'
  subscription: 'none' | 'trialing' | 'active' | 'past_due' | 'canceling' | 'canceled'
  has_provider_subscription: boolean
  line_active: boolean
  pending_activation: boolean
}

// What /billing/subscription-details found at Stripe. Undefined means not asked yet.
export type ProviderState = 'ok' | 'none' | 'missing' | 'unavailable'

export type StatusTone = 'success' | 'warn' | 'danger' | 'neutral'

export interface Labelled {
  label: string
  tone: StatusTone
}

export interface AccountView {
  planLabel: string
  phoneLine: Labelled
  features: Labelled
  subscription: Labelled
  // Prompt this account to choose a plan. False while loading, so nobody is told
  // to buy a plan they already have because a request is slow.
  needsPlan: boolean
  // Show the self-service plan picker on Billing. False for accounts that must not
  // start paying by accident: complimentary, manual, and anything Stripe can't confirm.
  canChoosePlan: boolean
  // Shown on Billing in place of plan details when there is nothing to manage.
  billingNotice: { title: string; body: string } | null
}

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

const NEUTRAL = (label: string): Labelled => ({ label, tone: 'neutral' })

function phoneLineOf(account: Account): Labelled {
  if (account.phone_line === 'on') return { label: 'On', tone: 'success' }
  if (account.phone_line === 'off') return { label: 'Off', tone: 'warn' }
  return NEUTRAL('No number yet')
}

function featuresOf(account: Account): Labelled {
  return account.feature_plan ? NEUTRAL(capitalize(account.feature_plan)) : NEUTRAL('No paid plan')
}

const UNKNOWN: AccountView = {
  planLabel: 'Plan unavailable',
  phoneLine: NEUTRAL('Unavailable'),
  features: NEUTRAL('Unavailable'),
  subscription: NEUTRAL('Unavailable'),
  needsPlan: false,
  canChoosePlan: false,
  billingNotice: {
    title: 'We couldn’t load your plan',
    body: 'This doesn’t change your account. Try again in a moment.',
  },
}

const LOADING: AccountView = {
  ...UNKNOWN,
  planLabel: '',
  phoneLine: NEUTRAL(''),
  features: NEUTRAL(''),
  subscription: NEUTRAL(''),
  billingNotice: null,
}

function subscriptionView(account: Account, provider?: ProviderState): Pick<AccountView, 'planLabel' | 'subscription' | 'needsPlan' | 'canChoosePlan' | 'billingNotice'> {
  const plan = account.plan ? capitalize(account.plan) : null
  const planName = plan ? `${plan} plan` : 'Plan'
  const none = { needsPlan: false, billingNotice: null }

  if (account.source === 'complimentary') {
    return {
      planLabel: plan ? `${plan} (complimentary)` : 'Complimentary',
      subscription: NEUTRAL('Complimentary'),
      needsPlan: false,
      canChoosePlan: false,
      billingNotice: {
        title: 'Complimentary account',
        body: 'Open Lines provides this account at no charge, so there’s no paid subscription to manage and no plan to choose. To talk about a paid plan, email support@openlines.ai.',
      },
    }
  }

  if (account.source === 'manual') {
    return {
      planLabel: plan ? `${plan} (manual access)` : 'Manual access',
      subscription: NEUTRAL('Manual'),
      needsPlan: false,
      canChoosePlan: false,
      billingNotice: {
        title: 'No paid subscription',
        body: `${plan ? `${plan} features were` : 'Access was'} set up on this account by Open Lines, so there’s no paid subscription to manage. To move to a paid plan, email support@openlines.ai.`,
      },
    }
  }

  if (account.source === 'subscription' && account.subscription !== 'canceled') {
    // Stripe has the last word on anything that claims to be a live subscription.
    if (provider === undefined) {
      return { ...none, planLabel: planName, subscription: NEUTRAL('Checking…'), canChoosePlan: false }
    }
    if (provider === 'missing') {
      return {
        planLabel: planName,
        subscription: { label: 'Unverified', tone: 'warn' },
        needsPlan: false,
        canChoosePlan: false,
        billingNotice: {
          title: 'We couldn’t verify your subscription',
          body: 'Our billing provider couldn’t confirm a subscription for this account. Your phone line and features aren’t changed by this. Please contact support@openlines.ai before choosing a plan, so you aren’t billed twice.',
        },
      }
    }
    if (provider === 'unavailable') {
      return { ...none, planLabel: planName, subscription: { label: 'Not verified right now', tone: 'warn' }, canChoosePlan: false }
    }
    switch (account.subscription) {
      case 'trialing':
        return { ...none, planLabel: plan ? `${plan} trial` : 'Free trial', subscription: NEUTRAL('Trial'), canChoosePlan: true }
      case 'active':
        return { ...none, planLabel: planName, subscription: { label: 'Active', tone: 'success' }, canChoosePlan: true }
      case 'canceling':
        return { ...none, planLabel: planName, subscription: { label: 'Canceling', tone: 'warn' }, canChoosePlan: true }
      case 'past_due':
        return { ...none, planLabel: planName, subscription: { label: 'Past due', tone: 'danger' }, canChoosePlan: true }
    }
  }

  if (account.subscription === 'canceled') {
    return { planLabel: 'No active plan', subscription: NEUTRAL('Canceled'), needsPlan: true, canChoosePlan: true, billingNotice: null }
  }

  if (account.source === 'trial') {
    return { planLabel: 'Free trial', subscription: NEUTRAL('Trial'), needsPlan: true, canChoosePlan: true, billingNotice: null }
  }

  if (account.pending_activation) {
    return { ...none, planLabel: 'Awaiting activation', subscription: NEUTRAL('Starts at activation'), canChoosePlan: false }
  }

  return { planLabel: 'No active plan', subscription: NEUTRAL('None'), needsPlan: true, canChoosePlan: true, billingNotice: null }
}

export function presentAccount(
  account: Account | null | undefined,
  state: 'loading' | 'ready' | 'error',
  provider?: ProviderState,
): AccountView {
  if (state === 'loading') return LOADING
  if (state === 'error' || !account) return UNKNOWN
  return {
    ...subscriptionView(account, provider),
    phoneLine: phoneLineOf(account),
    features: featuresOf(account),
  }
}
