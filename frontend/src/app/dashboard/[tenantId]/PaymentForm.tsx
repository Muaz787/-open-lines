'use client'

import { useState, useEffect, useRef } from 'react'
import { loadStripe, StripeCardNumberElement, PaymentRequest } from '@stripe/stripe-js'
import {
  Elements,
  CardNumberElement,
  CardExpiryElement,
  CardCvcElement,
  PaymentRequestButtonElement,
  useStripe,
  useElements,
} from '@stripe/react-stripe-js'

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? '')
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const CARD_STYLE = {
  style: {
    base: {
      color: '#DDE8F2',
      fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
      fontSize: '14px',
      fontWeight: '400',
      letterSpacing: '0.01em',
      '::placeholder': { color: '#445566' },
    },
    invalid: { color: '#FF453A' },
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

// ─── Public component ─────────────────────────────────────────────────────────

export interface PaymentFormProps {
  tenantId: string
  plan: string
  planLabel: string
  onSuccess: () => void
  onCancel: () => void
}

export function PaymentForm({ tenantId, plan, planLabel, onSuccess, onCancel }: PaymentFormProps) {
  const [clientSecret, setClientSecret]     = useState<string | null>(null)
  const [subscriptionId, setSubscriptionId] = useState<string>('')
  const [loadError, setLoadError]           = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`${API}/billing/create-subscription`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tenant_id: tenantId, plan }),
    })
      .then(r => r.json())
      .then(data => {
        if (cancelled) return
        if (data.needs_payment === false) { onSuccess(); return }
        if (data.client_secret) {
          setClientSecret(data.client_secret)
          setSubscriptionId(data.subscription_id)
        } else {
          setLoadError(data.detail ?? 'Could not initialise payment. Please try again.')
        }
      })
      .catch(() => { if (!cancelled) setLoadError('Network error — please try again.') })
    return () => { cancelled = true }
  }, [tenantId, plan, onSuccess])

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

  if (!clientSecret) {
    return (
      <div style={{ padding: '14px 18px', fontSize: 13, color: 'var(--text-3)' }}>
        Preparing payment form…
      </div>
    )
  }

  return (
    <div className="pay-wrap">
      <div className="pay-header">
        Complete payment for <span className="pay-plan">{planLabel}</span>
      </div>
      <Elements
        stripe={stripePromise}
        options={{
          clientSecret,
          appearance: {
            theme: 'night',
            variables: {
              colorPrimary: '#1A6BFF',
              colorBackground: '#111820',
              colorText: '#DDE8F2',
              colorTextSecondary: '#7A92AA',
              colorDanger: '#FF453A',
              fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
              borderRadius: '8px',
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
