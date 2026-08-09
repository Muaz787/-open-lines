'use client'

/* Card capture for the 7-day free trial.
 *
 * Nothing is charged here. /onboarding/setup-card returns a SetupIntent, we
 * confirm it to validate and store the card, and the resulting payment method is
 * handed to /onboarding/provision — which creates the trialing subscription only
 * AFTER the phone line exists. The card is billed 7 days later.
 *
 * The Stripe customer id never touches this component: setup-card returns it
 * inside an encrypted card_setup_token that we pass straight back to provision.
 */

import { useState, useEffect, useMemo } from 'react'
import { loadStripe } from '@stripe/stripe-js'
import {
  Elements,
  PaymentElement,
  AddressElement,
  useStripe,
  useElements,
} from '@stripe/react-stripe-js'

import { PLANS, type PlanId } from '@/lib/plans'
import { trackEvent } from '@/lib/analytics'

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? '')
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export interface CardResult {
  paymentMethodId: string
  cardSetupToken: string
  address: Record<string, string>
  billingName: string
}

/** The date the card gets charged, in the wording the consent text uses. */
export function trialEndDate(days = 7): string {
  return new Date(Date.now() + days * 86_400_000).toLocaleDateString('en-CA', {
    month: 'long', day: 'numeric', year: 'numeric',
  })
}

// Stripe Elements can't read CSS custom properties, so the marketing theme's
// tokens are mirrored here. The onboarding page opts into dark via
// [data-theme="dark"] on the root, so the palette is picked at mount.
function elementsAppearance(dark: boolean) {
  return {
    theme: (dark ? 'night' : 'stripe') as 'night' | 'stripe',
    variables: {
      colorPrimary:       '#34C759',
      colorBackground:    dark ? '#0D1118' : '#FFFFFF',
      colorText:          dark ? '#DDE8F2' : '#001F3F',
      colorTextSecondary: dark ? '#7A92AA' : '#5A6A7A',
      colorDanger:        '#FF3B30',
      fontFamily:         'system-ui, -apple-system, "Segoe UI", sans-serif',
      borderRadius:       '10px',
    },
    rules: {
      '.Label': { fontWeight: '600', fontSize: '12px' },
      '.Input': {
        border: dark ? '1px solid rgba(221,232,242,0.11)' : '1px solid rgba(0,31,63,0.13)',
        boxShadow: 'none',
      },
      '.Input:focus': {
        border: '1px solid #34C759',
        boxShadow: '0 0 0 3px rgba(52,199,89,0.12)',
      },
    },
  }
}

const Check = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
    <polyline points="20 6 9 17 4 12" />
  </svg>
)

function CardForm({
  plan,
  businessName,
  country,
  cardSetupToken,
  onComplete,
  onBack,
  busy,
}: {
  plan: PlanId
  businessName: string
  country: string
  cardSetupToken: string
  onComplete: (r: CardResult) => void
  onBack: () => void
  busy: boolean
}) {
  const stripe   = useStripe()
  const elements = useElements()
  const [error, setError]       = useState<string | null>(null)
  const [working, setWorking]   = useState(false)

  const p = PLANS.find(x => x.id === plan)!
  const charge = trialEndDate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!stripe || !elements) return
    setError(null)
    setWorking(true)

    try {
      const addressEl = elements.getElement(AddressElement)
      const addr = await addressEl?.getValue()
      if (!addr?.complete) {
        setError('Please enter your full billing address.')
        setWorking(false)
        return
      }

      // Validates and stores the card. `redirect: 'if_required'` keeps the user
      // here for ordinary cards while still supporting a 3-D Secure challenge.
      const { error: confirmError, setupIntent } = await stripe.confirmSetup({
        elements,
        redirect: 'if_required',
      })

      if (confirmError) {
        setError(confirmError.message ?? 'We couldn’t verify that card. Please check the details and try again.')
        trackEvent('card_setup_failed', { plan, code: confirmError.code ?? '' })
        setWorking(false)
        return
      }

      const pm = setupIntent?.payment_method
      const paymentMethodId = typeof pm === 'string' ? pm : (pm?.id ?? '')
      if (!paymentMethodId) {
        setError('We couldn’t verify that card. Please try again.')
        setWorking(false)
        return
      }

      trackEvent('card_added', { plan })
      onComplete({
        paymentMethodId,
        cardSetupToken,
        address: addr.value.address as unknown as Record<string, string>,
        billingName: addr.value.name ?? businessName,
      })
    } catch {
      setError('Something went wrong. Please try again.')
      setWorking(false)
    }
  }

  const disabled = working || busy

  return (
    <form onSubmit={handleSubmit}>
      {/* What they are agreeing to, stated before the card fields rather than
          buried under them. */}
      <div style={{
        margin: '0 0 18px', padding: '16px 18px', borderRadius: 12,
        background: 'rgba(52,199,89,0.08)', border: '1.5px solid rgba(52,199,89,0.30)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
          <span style={{ fontSize: 13.5, color: 'var(--text-2)' }}>{p.name} plan</span>
          <span style={{ fontSize: 13.5, color: 'var(--text-2)' }}>${p.price}/mo after trial</span>
        </div>

        {/* Someone is about to type a card number. The one thing they need to be
            certain of is that pressing the button charges them nothing, so it gets
            its own row and the largest type in the block. */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12,
          margin: '10px 0', paddingTop: 10, borderTop: '1px solid rgba(52,199,89,0.25)',
        }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>Due today</span>
          <span style={{
            fontSize: 20, fontWeight: 700, color: 'var(--accent-text)', letterSpacing: '-0.01em',
            fontFamily: 'var(--font-syne), sans-serif',
          }}>$0.00</span>
        </div>

        <div style={{ fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.6 }}>
          Your card is saved but not charged. On <strong style={{ color: 'var(--text)' }}>{charge}</strong> your
          7-day trial ends and we&rsquo;ll charge <strong style={{ color: 'var(--text)' }}>${p.price} + tax</strong> per
          month — cancel any time before then and you pay nothing.
        </div>
      </div>

      <div className="form-group">
        <label className="form-label">Billing Address</label>
        <AddressElement
          options={{
            mode: 'billing',
            fields: { phone: 'never' },
            // Type-ahead address suggestions. `automatic` is Stripe's default, but
            // it's spelled out because the behaviour depends on context: Stripe
            // supplies the Places lookup for free only when the Address Element
            // shares an Elements group with the Payment Element, which it does
            // here. Mounted standalone it would silently fall back to plain text
            // inputs unless given a Google Maps key of our own.
            autocomplete: { mode: 'automatic' },
            // They already told us their country two steps ago — no reason to make
            // them find it in the dropdown again. Editable, just pre-selected.
            defaultValues: { address: { country: country || 'CA' } },
          }}
        />
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 6 }}>
          Start typing your street address and we&rsquo;ll fill in the rest. Required so we can
          calculate sales tax (GST/HST) on your invoice.
        </div>
      </div>

      <div className="form-group">
        <label className="form-label">Card Details</label>
        <PaymentElement options={{ layout: 'tabs' }} />
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', margin: '4px 0 16px' }}>
        {['Cancel anytime before ' + charge, 'No setup fees', 'Business number included'].map(t => (
          <span key={t} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: 'var(--text-3)' }}>
            <span style={{ color: '#22c55e', display: 'inline-flex' }}><Check /></span>{t}
          </span>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 10 }}>
        <button type="button" className="btn-ghost" onClick={onBack} disabled={disabled}
          style={{ flex: '0 0 auto', padding: '13px 20px' }}>← Back</button>
        <button type="submit" className="btn-submit" style={{ flex: 1, margin: 0 }} disabled={disabled}>
          {disabled ? 'Setting up…' : 'Start My Free Trial →'}
        </button>
      </div>

      <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 12, lineHeight: 1.5 }}>
        By starting your trial you agree to our{' '}
        <a href="/terms" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-text)' }}>Terms of Service</a>
        {' '}and{' '}
        <a href="/privacy" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-text)' }}>Privacy Policy</a>,
        {' '}including the automatic renewal described above. Payments are processed by Stripe — we never see your card number.
      </div>

      {error && <div className="error-msg">{error}</div>}
    </form>
  )
}

export function TrialCardStep({
  plan,
  email,
  businessName,
  country = 'CA',
  onComplete,
  onBack,
  busy = false,
}: {
  plan: PlanId
  email: string
  businessName: string
  country?: string
  onComplete: (r: CardResult) => void
  onBack: () => void
  busy?: boolean
}) {
  const [clientSecret, setClientSecret] = useState('')
  const [token, setToken]               = useState('')
  const [loadError, setLoadError]       = useState<string | null>(null)

  const dark = useMemo(
    () => typeof document !== 'undefined' && document.documentElement.dataset.theme === 'dark',
    [],
  )

  // Bumped by "Try again" to re-run the effect. State is only ever set after an
  // await (and behind the cancelled guard), so a fast Back-click mid-request
  // can't write into an unmounted component.
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      try {
        const res = await fetch(`${API}/onboarding/setup-card`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plan, email, business_name: businessName }),
        })
        if (!res.ok) throw new Error(String(res.status))
        const data = await res.json()
        if (cancelled) return
        setClientSecret(data.client_secret)
        setToken(data.card_setup_token)
      } catch {
        if (!cancelled) setLoadError('We couldn’t start the payment step. Please try again.')
      }
    }
    void run()
    return () => { cancelled = true }
  }, [plan, email, businessName, attempt])

  if (loadError) {
    return (
      <div>
        <div className="error-msg" style={{ textAlign: 'left', marginBottom: 14 }}>{loadError}</div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button type="button" className="btn-ghost" onClick={onBack} style={{ flex: '0 0 auto', padding: '13px 20px' }}>← Back</button>
          <button type="button" className="btn-submit" style={{ flex: 1, margin: 0 }}
            onClick={() => { setLoadError(null); setAttempt(a => a + 1) }}>Try again</button>
        </div>
      </div>
    )
  }

  if (!clientSecret) {
    return (
      <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--text-3)', fontSize: 13 }}>
        Preparing secure payment…
      </div>
    )
  }

  return (
    <Elements stripe={stripePromise} options={{ clientSecret, appearance: elementsAppearance(dark) }}>
      <CardForm
        plan={plan}
        businessName={businessName}
        country={country}
        cardSetupToken={token}
        onComplete={onComplete}
        onBack={onBack}
        busy={busy}
      />
    </Elements>
  )
}
