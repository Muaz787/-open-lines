import posthog from 'posthog-js'

// Analytics is optional: every function no-ops when PostHog is not configured
// or when running on the server.
const enabled = () =>
  typeof window !== 'undefined' && !!process.env.NEXT_PUBLIC_POSTHOG_KEY

export function trackEvent(event: string, properties?: Record<string, unknown>) {
  if (!enabled()) return
  posthog.capture(event, properties)
}

// PRIVACY: only pass safe user properties here — never passwords, call
// transcripts, caller phone numbers, knowledge-base content, or calendar
// event details.
export interface SafeUserProps {
  email?: string
  tenant_id?: string
  business_name?: string
  industry?: string
  plan?: string
  created_at?: string
}

export function identifyUser(userId: string, props?: SafeUserProps) {
  if (!enabled()) return
  posthog.identify(userId, props as Record<string, unknown> | undefined)
  // Attach tenant_id to all subsequent events in this session
  if (props?.tenant_id) posthog.register({ tenant_id: props.tenant_id })
}

// Call on logout so the next user on this device is not merged into the
// previous person profile.
export function resetAnalytics() {
  if (!enabled()) return
  posthog.reset()
}

/* ── First-touch attribution ─────────────────────────────────────────────
   Persist the visitor's first UTM params / referrer / landing page so they
   can be attached to signup_completed and onboarding_completed later.
   (PostHog also keeps $initial_utm_* on person profiles natively; this is
   an explicit, queryable copy on the key conversion events.) */

const FT_KEY = 'ol_first_touch'
const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'] as const

export function persistFirstTouch() {
  try {
    if (typeof window === 'undefined' || localStorage.getItem(FT_KEY)) return
    const qs = new URLSearchParams(window.location.search)
    const ft: Record<string, string> = {
      first_landing_page: window.location.pathname,
      initial_referrer: document.referrer || '$direct',
    }
    for (const k of UTM_KEYS) {
      const v = qs.get(k)
      if (v) ft[`initial_${k}`] = v
    }
    localStorage.setItem(FT_KEY, JSON.stringify(ft))
  } catch {
    // localStorage unavailable (private mode etc.) — attribution is best-effort
  }
}

export function getFirstTouch(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(FT_KEY) ?? '{}')
  } catch {
    return {}
  }
}

// Current-page UTM params (for marketing events like landing_page_viewed)
export function getUtmParams(): Record<string, string> {
  if (typeof window === 'undefined') return {}
  const qs = new URLSearchParams(window.location.search)
  const out: Record<string, string> = {}
  for (const k of UTM_KEYS) {
    const v = qs.get(k)
    if (v) out[k] = v
  }
  return out
}
