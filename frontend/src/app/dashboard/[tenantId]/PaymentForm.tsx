'use client'

import { useState, useEffect, useRef } from 'react'
import { loadStripe, StripeCardNumberElement, PaymentRequest } from '@stripe/stripe-js'
import {
  Elements,
  CardNumberElement,
  CardExpiryElement,
  CardCvcElement,
  PaymentRequestButtonElement,
  AddressElement,
  useStripe,
  useElements,
} from '@stripe/react-stripe-js'

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? '')
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const CARD_STYLE = {
  style: {
    base: {
      color: '#16161a',
      fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
      fontSize: '14px',
      fontWeight: '400',
      letterSpacing: '0.01em',
      '::placeholder': { color: '#aaa' },
    },
    invalid: { color: '#e53e3e' },
  },
}

function CheckoutForm({
  tenantId,
  subscriptionId,
  clientSecret,
  planLabel,
  onSuccess,
  onCancel,
}: {
  tenantId: string
  subscriptionId: string
  clientSecret: string
  planLabel: string
  onSuccess: () => void
  onCancel: () => void
}) {
  const stripe   = useStripe()
  const elements = useElements()

  const [cardholderName, setCardholderName] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ number?: string; expiry?: string; cvc?: string }>({})
  const [formError, setFormError]     = useState<string | null>(null)
  const [processing, setProcessing]   = useState(false)

  const [paymentRequest, setPaymentRequest] = useState<PaymentRequest | null>(null)
  const [prReady, setPrReady]               = useState(false)

  // Keep ref so the paymentmethod closure always has the latest secret
  const secretRef = useRef(clientSecret)
  useEffect(() => { secretRef.current = clientSecret }, [clientSecret])

  useEffect(() => {
    if (!stripe) return
    const pr = stripe.paymentRequest({
      country: 'CA',
      currency: 'cad',
      total: { label: `Open Lines — ${planLabel}`, amount: 0 },
      requestPayerName: true,
      requestPayerEmail: true,
    })
    pr.canMakePayment().then(result => { if (result) setPrReady(true) })

    pr.on('paymentmethod', async (ev) => {
      const { error } = await stripe.confirmCardPayment(
        secretRef.current,
        { payment_method: ev.paymentMethod.id },
        { handleActions: false },
      )
      if (error) {
        ev.complete('fail')
        setFormError(error.message ?? 'Payment failed.')
        return
      }
      ev.complete('success')
      try {
        await fetch(`${API}/billing/confirm-payment`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tenant_id: tenantId, subscription_id: subscriptionId }),
        })
      } catch {}
      onSuccess()
    })

    setPaymentRequest(pr)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stripe])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!stripe || !elements) return
    const cardNumber = elements.getElement(CardNumberElement)
    if (!cardNumber) return
    if (!cardholderName.trim()) {
      setFormError('Please enter the cardholder name.')
      return
    }
    setProcessing(true)
    setFormError(null)

    const { error } = await stripe.confirmCardPayment(secretRef.current, {
      payment_method: {
        card: cardNumber as StripeCardNumberElement,
        billing_details: { name: cardholderName.trim() },
      },
    })

    if (error) {
      setFormError(error.message ?? 'Payment failed — please try again.')
      setProcessing(false)
      return
    }

    try {
      await fetch(`${API}/billing/confirm-payment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId, subscription_id: subscriptionId }),
      })
    } catch {}
    onSuccess()
  }

  return (
    <form onSubmit={handleSubmit} className="pay-form">

      {/* Apple Pay / Google Pay */}
      {prReady && paymentRequest && (
        <>
          <PaymentRequestButtonElement
            options={{
              paymentRequest,
              style: {
                paymentRequestButton: { type: 'default', theme: 'dark', height: '44px' },
              },
            }}
          />
          <div className="pay-divider"><span>or pay with card</span></div>
        </>
      )}

      {/* Cardholder name */}
      <div className="pay-field">
        <label className="pay-label">Cardholder name</label>
        <input
          className="pay-input"
          type="text"
          placeholder="Jane Smith"
          value={cardholderName}
          onChange={e => setCardholderName(e.target.value)}
          autoComplete="cc-name"
        />
      </div>

      {/* Card number */}
      <div className="pay-field">
        <label className="pay-label">Card number</label>
        <div className="pay-element-wrap">
          <CardNumberElement
            options={{ ...CARD_STYLE, showIcon: true }}
            onChange={e => setFieldErrors(prev => ({ ...prev, number: e.error?.message }))}
          />
        </div>
        {fieldErrors.number && <span className="pay-field-err">{fieldErrors.number}</span>}
      </div>

      {/* Expiry + CVC */}
      <div className="pay-row">
        <div className="pay-field">
          <label className="pay-label">Expiry date</label>
          <div className="pay-element-wrap">
            <CardExpiryElement
              options={CARD_STYLE}
              onChange={e => setFieldErrors(prev => ({ ...prev, expiry: e.error?.message }))}
            />
          </div>
          {fieldErrors.expiry && <span className="pay-field-err">{fieldErrors.expiry}</span>}
        </div>
        <div className="pay-field">
          <label className="pay-label">CVC</label>
          <div className="pay-element-wrap">
            <CardCvcElement
              options={CARD_STYLE}
              onChange={e => setFieldErrors(prev => ({ ...prev, cvc: e.error?.message }))}
            />
          </div>
          {fieldErrors.cvc && <span className="pay-field-err">{fieldErrors.cvc}</span>}
        </div>
      </div>

      {formError && <div className="pay-err">{formError}</div>}

      <div className="pay-actions">
        <button type="submit" disabled={!stripe || processing} className="pay-submit">
          {processing ? 'Processing…' : `Subscribe — ${planLabel}`}
        </button>
        <button type="button" onClick={onCancel} disabled={processing} className="pay-cancel">
          Cancel
        </button>
      </div>

      <p className="pay-secure">
        <svg width="11" height="13" viewBox="0 0 11 13" fill="none" aria-hidden="true">
          <path d="M5.5 0C3.567 0 2 1.343 2 3v1H1a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1H9V3C9 1.343 7.433 0 5.5 0Zm0 1.5C6.88 1.5 7.5 2.2 7.5 3v1h-4V3c0-.8.62-1.5 2-1.5ZM5.5 8a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z" fill="currentColor"/>
        </svg>
        Secured by Stripe · 256-bit SSL encryption
      </p>
    </form>
  )
}

// ─── Update payment method form ───────────────────────────────────────────────

function UpdateCardForm({
  tenantId,
  clientSecret,
  onSuccess,
  onCancel,
}: {
  tenantId: string
  clientSecret: string
  onSuccess: () => void
  onCancel: () => void
}) {
  const stripe   = useStripe()
  const elements = useElements()

  const [cardholderName, setCardholderName] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ number?: string; expiry?: string; cvc?: string }>({})
  const [formError, setFormError]     = useState<string | null>(null)
  const [processing, setProcessing]   = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!stripe || !elements) return
    const cardNumber = elements.getElement(CardNumberElement)
    if (!cardNumber) return
    if (!cardholderName.trim()) { setFormError('Please enter the cardholder name.'); return }
    setProcessing(true)
    setFormError(null)

    const { setupIntent, error } = await stripe.confirmCardSetup(
      clientSecret,
      {
        payment_method: {
          card: cardNumber as StripeCardNumberElement,
          billing_details: { name: cardholderName.trim() },
        },
      },
    )

    if (error) {
      setFormError(error.message ?? 'Card update failed — please try again.')
      setProcessing(false)
      return
    }

    try {
      await fetch(`${API}/billing/update-payment-method`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId, payment_method_id: setupIntent?.payment_method }),
      })
    } catch {}
    onSuccess()
  }

  return (
    <form onSubmit={handleSubmit} className="pay-form">
      <div className="pay-field">
        <label className="pay-label">Cardholder name</label>
        <input className="pay-input" type="text" placeholder="Jane Smith" value={cardholderName}
          onChange={e => setCardholderName(e.target.value)} autoComplete="cc-name" />
      </div>
      <div className="pay-field">
        <label className="pay-label">Card number</label>
        <div className="pay-element-wrap">
          <CardNumberElement options={{ ...CARD_STYLE, showIcon: true }}
            onChange={e => setFieldErrors(prev => ({ ...prev, number: e.error?.message }))} />
        </div>
        {fieldErrors.number && <span className="pay-field-err">{fieldErrors.number}</span>}
      </div>
      <div className="pay-row">
        <div className="pay-field">
          <label className="pay-label">Expiry date</label>
          <div className="pay-element-wrap">
            <CardExpiryElement options={CARD_STYLE}
              onChange={e => setFieldErrors(prev => ({ ...prev, expiry: e.error?.message }))} />
          </div>
          {fieldErrors.expiry && <span className="pay-field-err">{fieldErrors.expiry}</span>}
        </div>
        <div className="pay-field">
          <label className="pay-label">CVC</label>
          <div className="pay-element-wrap">
            <CardCvcElement options={CARD_STYLE}
              onChange={e => setFieldErrors(prev => ({ ...prev, cvc: e.error?.message }))} />
          </div>
          {fieldErrors.cvc && <span className="pay-field-err">{fieldErrors.cvc}</span>}
        </div>
      </div>
      {formError && <div className="pay-err">{formError}</div>}
      <div className="pay-actions">
        <button type="submit" disabled={!stripe || processing} className="pay-submit">
          {processing ? 'Saving…' : 'Save card'}
        </button>
        <button type="button" onClick={onCancel} disabled={processing} className="pay-cancel">Cancel</button>
      </div>
      <p className="pay-secure">
        <svg width="11" height="13" viewBox="0 0 11 13" fill="none" aria-hidden="true">
          <path d="M5.5 0C3.567 0 2 1.343 2 3v1H1a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1H9V3C9 1.343 7.433 0 5.5 0Zm0 1.5C6.88 1.5 7.5 2.2 7.5 3v1h-4V3c0-.8.62-1.5 2-1.5ZM5.5 8a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z" fill="currentColor"/>
        </svg>
        Secured by Stripe · 256-bit SSL encryption
      </p>
    </form>
  )
}

export interface UpdatePaymentFormProps {
  tenantId: string
  onSuccess: () => void
  onCancel: () => void
}

export function UpdatePaymentForm({ tenantId, onSuccess, onCancel }: UpdatePaymentFormProps) {
  const [clientSecret, setClientSecret] = useState<string | null>(null)
  const [loadError, setLoadError]       = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`${API}/billing/setup-intent/${tenantId}`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (cancelled) return
        if (data.client_secret) setClientSecret(data.client_secret)
        else setLoadError(data.detail ?? 'Could not load card form.')
      })
      .catch(() => { if (!cancelled) setLoadError('Network error — please try again.') })
    return () => { cancelled = true }
  }, [tenantId])

  if (loadError) {
    return (
      <div style={{ padding: '14px 16px', fontSize: 13 }}>
        <span style={{ color: '#FF453A' }}>{loadError}</span>
        <button onClick={onCancel} style={{ marginLeft: 12, fontSize: 12, color: 'var(--text-3)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>Cancel</button>
      </div>
    )
  }

  if (!clientSecret) {
    return <div style={{ padding: '14px 16px', fontSize: 13, color: 'var(--text-3)' }}>Loading…</div>
  }

  return (
    <div className="pay-wrap">
      <Elements stripe={stripePromise} options={{ clientSecret, appearance: { theme: 'night', variables: { colorPrimary: '#1A6BFF', colorBackground: '#111820', colorText: '#DDE8F2', colorTextSecondary: '#7A92AA', borderRadius: '8px' } } }}>
        <UpdateCardForm tenantId={tenantId} clientSecret={clientSecret} onSuccess={onSuccess} onCancel={onCancel} />
      </Elements>
    </div>
  )
}

// ─── Upgrade payment form (proration charge for existing subscribers) ─────────

export interface UpgradePaymentFormProps {
  tenantId: string
  subscriptionId: string
  clientSecret: string
  amountDue: number
  currency: string
  planLabel: string
  onSuccess: () => void
  onCancel: () => void
}

export function UpgradePaymentForm({
  tenantId, subscriptionId, clientSecret, amountDue, currency, planLabel, onSuccess, onCancel,
}: UpgradePaymentFormProps) {
  const fmtAmount = new Intl.NumberFormat('en-CA', {
    style: 'currency', currency: currency.toUpperCase(), minimumFractionDigits: 2,
  }).format(amountDue / 100)

  return (
    <div className="pay-wrap">
      <div style={{ marginBottom: 14, padding: '10px 12px', background: 'var(--accent-dim)', borderRadius: 8, border: '1px solid var(--accent)', fontSize: 13 }}>
        <span style={{ fontWeight: 700, color: 'var(--accent-text)' }}>{fmtAmount}</span>
        <span style={{ color: 'var(--text-2)', marginLeft: 6 }}>charged today — prorated upgrade to {planLabel}</span>
      </div>
      <Elements
        stripe={stripePromise}
        options={{
          clientSecret,
          appearance: {
            theme: 'night',
            variables: {
              colorPrimary: '#1A6BFF', colorBackground: '#111820',
              colorText: '#DDE8F2', colorTextSecondary: '#7A92AA',
              colorDanger: '#FF453A', borderRadius: '8px',
            },
          },
        }}
      >
        <CheckoutForm
          tenantId={tenantId}
          subscriptionId={subscriptionId}
          clientSecret={clientSecret}
          planLabel={planLabel}
          onSuccess={onSuccess}
          onCancel={onCancel}
        />
      </Elements>
    </div>
  )
}

// ─── Public component ─────────────────────────────────────────────────────────

export interface PaymentFormProps {
  tenantId: string
  plan: string
  planLabel: string
  interval?: 'month' | 'year'
  onSuccess: () => void
  onCancel: () => void
}

// Shared dark Elements appearance
const ELEMENTS_APPEARANCE = {
  theme: 'night' as const,
  variables: {
    colorPrimary: '#1A6BFF',
    colorBackground: '#111820',
    colorText: '#DDE8F2',
    colorTextSecondary: '#7A92AA',
    colorDanger: '#FF453A',
    fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
    borderRadius: '8px',
  },
}

interface BillingAddress {
  line1?: string
  line2?: string
  city?: string
  state?: string
  postal_code?: string
  country?: string
}

// ─── Step 1: collect billing address (needed for Stripe Tax / GST-HST) ────────
function AddressStep({
  planLabel,
  onContinue,
  onCancel,
  submitting,
}: {
  planLabel: string
  onContinue: (address: BillingAddress, name: string) => void
  onCancel: () => void
  submitting: boolean
}) {
  const elements = useElements()
  const [error, setError]   = useState<string | null>(null)
  const [busy, setBusy]     = useState(false)

  const handleContinue = async () => {
    if (!elements) return
    const el = elements.getElement(AddressElement)
    if (!el) return
    setBusy(true)
    setError(null)
    const { complete, value } = await el.getValue()
    if (!complete) {
      setError('Please enter your full billing address.')
      setBusy(false)
      return
    }
    setBusy(false)
    onContinue(value.address as BillingAddress, value.name ?? '')
  }

  return (
    <div className="pay-form">
      <div className="pay-field">
        <label className="pay-label">Billing address</label>
        <AddressElement options={{ mode: 'billing', fields: { phone: 'never' } }} />
      </div>
      {error && <div className="pay-err">{error}</div>}
      <div className="pay-actions">
        <button type="button" onClick={handleContinue} disabled={busy || submitting} className="pay-submit">
          {busy || submitting ? 'Loading…' : `Continue — ${planLabel}`}
        </button>
        <button type="button" onClick={onCancel} disabled={busy || submitting} className="pay-cancel">
          Cancel
        </button>
      </div>
      <p className="pay-secure">Taxes are calculated based on your billing address.</p>
    </div>
  )
}

export function PaymentForm({ tenantId, plan, planLabel, interval = 'month', onSuccess, onCancel }: PaymentFormProps) {
  const [clientSecret, setClientSecret]     = useState<string | null>(null)
  const [subscriptionId, setSubscriptionId] = useState<string>('')
  const [loadError, setLoadError]           = useState<string | null>(null)
  const [submitting, setSubmitting]         = useState(false)

  // Step 2: once we have the address, create the subscription server-side
  // (which saves the address to the Customer first, so tax is on invoice #1).
  const startSubscription = async (address: BillingAddress, name: string) => {
    setSubmitting(true)
    setLoadError(null)
    try {
      const res = await fetch(`${API}/billing/create-subscription`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId, plan, interval, address, name }),
      })
      const data = await res.json()
      if (data.needs_payment === false) { onSuccess(); return }
      if (data.client_secret) {
        setSubscriptionId(data.subscription_id)
        setClientSecret(data.client_secret)
      } else {
        setLoadError(data.detail ?? 'Could not initialise payment. Please try again.')
      }
    } catch {
      setLoadError('Network error — please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loadError) {
    return (
      <div style={{ padding: '14px 18px', fontSize: 13 }}>
        <span style={{ color: '#FF453A' }}>{loadError}</span>
        <button
          onClick={onCancel}
          style={{ marginLeft: 12, fontSize: 12, color: 'var(--text-3)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}
        >
          Cancel
        </button>
      </div>
    )
  }

  // Phase 1 — address (no clientSecret yet): mount Elements in deferred setup mode
  if (!clientSecret) {
    return (
      <div className="pay-wrap">
        <div className="pay-header">
          Subscribe to <span className="pay-plan">{planLabel}</span>
        </div>
        <Elements
          stripe={stripePromise}
          options={{ mode: 'setup', currency: 'cad', appearance: ELEMENTS_APPEARANCE }}
        >
          <AddressStep
            planLabel={planLabel}
            onContinue={startSubscription}
            onCancel={onCancel}
            submitting={submitting}
          />
        </Elements>
      </div>
    )
  }

  // Phase 2 — card entry against the subscription's PaymentIntent
  return (
    <div className="pay-wrap">
      <div className="pay-header">
        Complete payment for <span className="pay-plan">{planLabel}</span>
      </div>
      <Elements
        stripe={stripePromise}
        options={{ clientSecret, appearance: ELEMENTS_APPEARANCE }}
      >
        <CheckoutForm
          tenantId={tenantId}
          subscriptionId={subscriptionId}
          clientSecret={clientSecret}
          planLabel={planLabel}
          onSuccess={onSuccess}
          onCancel={onCancel}
        />
      </Elements>
    </div>
  )
}

// ─── Standalone billing-address capture ───────────────────────────────────────
// For existing customers created before the subscribe flow collected an address.
// Stripe Tax can't price an upgrade without a location, so we let them add one.

function AddressCollectInner({
  tenantId,
  onSaved,
  onCancel,
}: {
  tenantId: string
  onSaved: () => void
  onCancel: () => void
}) {
  const elements = useElements()
  const [error, setError]   = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!elements) return
    const el = elements.getElement(AddressElement)
    if (!el) return
    setSaving(true)
    setError(null)
    const { complete, value } = await el.getValue()
    if (!complete) {
      setError('Please enter your full billing address.')
      setSaving(false)
      return
    }
    try {
      const res = await fetch(`${API}/billing/billing-address/${tenantId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: value.address, name: value.name ?? '' }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail ?? 'Could not save address.')
        setSaving(false)
        return
      }
      onSaved()
    } catch {
      setError('Network error — please try again.')
      setSaving(false)
    }
  }

  return (
    <div className="pay-form">
      <div className="pay-field">
        <label className="pay-label">Billing address</label>
        <AddressElement options={{ mode: 'billing', fields: { phone: 'never' } }} />
      </div>
      {error && <div className="pay-err">{error}</div>}
      <div className="pay-actions">
        <button type="button" onClick={handleSave} disabled={saving} className="pay-submit">
          {saving ? 'Saving…' : 'Save address'}
        </button>
        <button type="button" onClick={onCancel} disabled={saving} className="pay-cancel">Cancel</button>
      </div>
      <p className="pay-secure">Required so we can calculate sales tax (GST/HST) on your invoice.</p>
    </div>
  )
}

export interface AddressCollectFormProps {
  tenantId: string
  onSaved: () => void
  onCancel: () => void
}

export function AddressCollectForm({ tenantId, onSaved, onCancel }: AddressCollectFormProps) {
  return (
    <div className="pay-wrap">
      <Elements
        stripe={stripePromise}
        options={{ mode: 'setup', currency: 'cad', appearance: ELEMENTS_APPEARANCE }}
      >
        <AddressCollectInner tenantId={tenantId} onSaved={onSaved} onCancel={onCancel} />
      </Elements>
    </div>
  )
}
