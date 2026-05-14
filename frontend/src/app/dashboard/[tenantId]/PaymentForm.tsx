'use client'

import { useState, useEffect } from 'react'
import { loadStripe } from '@stripe/stripe-js'
import {
  Elements,
  PaymentElement,
  useStripe,
  useElements,
} from '@stripe/react-stripe-js'

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? '')
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

function CheckoutForm({
  tenantId,
  subscriptionId,
  planLabel,
  onSuccess,
  onCancel,
}: {
  tenantId: string
  subscriptionId: string
  planLabel: string
  onSuccess: () => void
  onCancel: () => void
}) {
  const stripe   = useStripe()
  const elements = useElements()
  const [error, setError]         = useState<string | null>(null)
  const [processing, setProcessing] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!stripe || !elements) return
    setProcessing(true)
    setError(null)

    const { error: confirmError } = await stripe.confirmPayment({
      elements,
      redirect: 'if_required',
    })

    if (confirmError) {
      setError(confirmError.message ?? 'Payment failed — please try again.')
      setProcessing(false)
      return
    }

    // Immediately sync subscription status to DB (don't wait for webhook)
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
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <PaymentElement options={{ layout: 'tabs' }} />

      {error && (
        <div style={{
          fontSize: 12, color: '#FF3B30',
          padding: '9px 12px',
          background: 'rgba(255,59,48,.08)',
          border: '1px solid rgba(255,59,48,.18)',
          borderRadius: 6,
        }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
        <button
          type="submit"
          disabled={!stripe || processing}
          style={{
            flex: 1,
            padding: '12px 20px',
            background: processing ? 'var(--accent)' : 'var(--text)',
            color: 'var(--bg)',
            border: 'none',
            borderRadius: 8,
            fontSize: 13,
            fontWeight: 600,
            cursor: !stripe || processing ? 'default' : 'pointer',
            opacity: !stripe || processing ? 0.7 : 1,
            transition: 'opacity 0.2s',
          }}
        >
          {processing ? 'Processing…' : `Subscribe — ${planLabel}`}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={processing}
          style={{
            padding: '12px 16px',
            background: 'transparent',
            color: 'var(--text-3)',
            border: '1px solid var(--border-2)',
            borderRadius: 8,
            fontSize: 13,
            cursor: processing ? 'default' : 'pointer',
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

export interface PaymentFormProps {
  tenantId: string
  plan: string
  planLabel: string
  onSuccess: () => void
  onCancel: () => void
}

export function PaymentForm({ tenantId, plan, planLabel, onSuccess, onCancel }: PaymentFormProps) {
  const [clientSecret, setClientSecret]   = useState<string | null>(null)
  const [subscriptionId, setSubscriptionId] = useState<string>('')
  const [loadError, setLoadError]         = useState<string | null>(null)

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
        if (data.needs_payment === false) {
          // Upgrade with existing payment method — no payment step needed
          onSuccess()
          return
        }
        if (data.client_secret) {
          setClientSecret(data.client_secret)
          setSubscriptionId(data.subscription_id)
        } else {
          setLoadError(data.detail ?? 'Could not initialize payment. Please try again.')
        }
      })
      .catch(() => {
        if (!cancelled) setLoadError('Network error — please try again.')
      })
    return () => { cancelled = true }
  }, [tenantId, plan, onSuccess])

  if (loadError) {
    return (
      <div style={{ padding: '14px 18px', fontSize: 13 }}>
        <span style={{ color: '#FF3B30' }}>{loadError}</span>
        <button
          onClick={onCancel}
          style={{
            marginLeft: 12, fontSize: 12, color: 'var(--text-3)',
            background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline',
          }}
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
    <div style={{ padding: '18px' }}>
      <div style={{ marginBottom: 16, fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
        Complete payment for <span style={{ color: 'var(--accent)' }}>{planLabel}</span>
      </div>
      <Elements
        stripe={stripePromise}
        options={{
          clientSecret,
          appearance: {
            theme: 'night',
            variables: {
              colorPrimary: '#1A6BFF',
              colorBackground: '#1A2236',
              colorText: '#E2E8F0',
              colorTextSecondary: '#94A3B8',
              colorDanger: '#FF3B30',
              fontFamily: 'system-ui, -apple-system, sans-serif',
              borderRadius: '8px',
              spacingUnit: '4px',
            },
            rules: {
              '.Input': {
                border: '1px solid rgba(255,255,255,0.12)',
                boxShadow: 'none',
              },
              '.Input:focus': {
                border: '1px solid #1A6BFF',
                boxShadow: '0 0 0 2px rgba(26,107,255,0.18)',
              },
            },
          },
        }}
      >
        <CheckoutForm
          tenantId={tenantId}
          subscriptionId={subscriptionId}
          planLabel={planLabel}
          onSuccess={onSuccess}
          onCancel={onCancel}
        />
      </Elements>
    </div>
  )
}
