// Google Ads conversion for an activated free trial. The action behind this label
// was created as "Subscribe"; it now means a started trial, so paid subscriptions
// must never be sent to it. They have their own label, below.
export const ADS_TRIAL_SIGNUP_CONVERSION = 'AW-18323006317/ZEN5CKaqnNEcEO3Gi6FE'

const SENT_KEY_PREFIX = 'ol_ads_trial_sent:'
const PENDING_KEY_PREFIX = 'ol_ads_trial_pending:'

export interface ProvisionedTrial {
  tenant_id: string
  onboarding_state?: string
  // Set by the backend only when a trial is running on a live line: 'card' for a
  // Stripe trial, 'fallback' for the card-free trial. Absent otherwise.
  trial_activation?: 'card' | 'fallback'
}

// Every trial path ends here, so they all share one de-duplication rule.
// transaction_id is the tenant id: a random UUID that carries no personal data,
// and that a retried provision resolves to again. Google de-duplicates on it, so
// it still holds if the localStorage check is unavailable or was cleared. No value
// is sent; a free trial has no revenue. Returns whether the tenant is now recorded.
function recordTrialConversion(tenantId: string): boolean {
  if (typeof window === 'undefined' || typeof window.gtag !== 'function') return false

  const sentKey = SENT_KEY_PREFIX + tenantId
  try {
    if (localStorage.getItem(sentKey)) return true
  } catch {
    // Private mode etc. — transaction_id still de-duplicates at Google.
  }

  window.gtag('event', 'conversion', {
    send_to: ADS_TRIAL_SIGNUP_CONVERSION,
    transaction_id: tenantId,
  })

  try {
    localStorage.setItem(sentKey, '1')
  } catch {}
  return true
}

// Call with the /onboarding/provision response. A regulated signup has no trial
// yet (it starts when the permanent number goes live), so it is remembered in this
// browser and resolved by resolvePendingTrialConversion once that is confirmed.
export function trackTrialSignupConversion(provisioned: ProvisionedTrial) {
  const { tenant_id: tenantId, trial_activation: activation, onboarding_state: state } = provisioned
  if (!tenantId) return
  if (activation) {
    recordTrialConversion(tenantId)
  } else if (state === 'regulatory_required') {
    try {
      localStorage.setItem(PENDING_KEY_PREFIX + tenantId, '1')
    } catch {}
  }
}

// Call wherever the server's view of the trial is loaded. Only a signup marked
// pending in this browser can fire, so existing customers never do.
export function resolvePendingTrialConversion(tenantId: string, trialConfirmed: boolean) {
  if (!trialConfirmed) return
  const pendingKey = PENDING_KEY_PREFIX + tenantId
  try {
    if (!localStorage.getItem(pendingKey)) return
    if (recordTrialConversion(tenantId)) localStorage.removeItem(pendingKey)
  } catch {}
}

// Paid subscriptions need their own Google Ads action. Until its label is set this
// does nothing, and it refuses the trial label so the two can never be mixed.
export function trackPaidSubscriptionConversion(tenantId: string, value: number | undefined, currency: string) {
  const sendTo = process.env.NEXT_PUBLIC_GOOGLE_ADS_PAID_CONVERSION
  if (!sendTo || sendTo === ADS_TRIAL_SIGNUP_CONVERSION) return
  if (typeof window === 'undefined' || typeof window.gtag !== 'function') return
  window.gtag('event', 'conversion', { send_to: sendTo, value, currency, transaction_id: tenantId })
}
