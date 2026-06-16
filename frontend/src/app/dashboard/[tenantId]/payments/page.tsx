'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { Toast } from '../components/Toast'
import { LoadingState } from '../components/PageStates'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface Settings {
  eligible: boolean
  stripe_connected: boolean
  deposits_enabled: boolean
  deposit_cents: number
  deposit_mandatory: boolean
  deposit_expiry_min: number
  deposit_label: string
  currency: string
}

interface Payment {
  id: string
  caller_name?: string
  caller_phone?: string
  service?: string
  amount_cents: number
  status: string
  created_at: string
  paid_at?: string
}

interface StripeStatus {
  connected: boolean
  charges_enabled?: boolean
  account_id?: string
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; bg: string; color: string }> = {
    pending:   { label: 'Pending',   bg: 'rgba(251,191,36,0.12)', color: '#f59e0b' },
    succeeded: { label: 'Paid',      bg: 'rgba(52,199,89,0.12)',  color: 'var(--db-accent-text)' },
    expired:   { label: 'Expired',   bg: 'rgba(156,163,175,0.12)', color: 'var(--db-muted)' },
    failed:    { label: 'Failed',    bg: 'rgba(239,68,68,0.12)',   color: '#ef4444' },
    refunded:  { label: 'Refunded',  bg: 'rgba(99,102,241,0.12)',  color: '#818cf8' },
  }
  const s = map[status] ?? { label: status, bg: 'var(--db-bg-2)', color: 'var(--db-muted)' }
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 20,
      background: s.bg, color: s.color, fontSize: 11, fontWeight: 600,
    }}>
      {s.label}
    </span>
  )
}

function LockIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2"/>
      <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
    </svg>
  )
}

function StripeIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" fill="#635BFF"/>
      <path d="M14.5 12.5c0-.83.69-1.5 2.1-1.5.94 0 1.9.22 2.4.44V9.6A8.7 8.7 0 0 0 16.5 9c-2.8 0-4.5 1.46-4.5 3.6 0 3.53 4.83 2.96 4.83 4.49 0 .98-.86 1.41-2.06 1.41a8.8 8.8 0 0 1-2.77-.56v1.87c.66.28 1.66.5 2.77.5 2.88 0 4.73-1.4 4.73-3.6 0-3.78-4.96-3.1-4.96-4.71z" fill="white"/>
    </svg>
  )
}

export default function PaymentsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [settings, setSettings]         = useState<Settings | null>(null)
  const [stripeStatus, setStripeStatus] = useState<StripeStatus | null>(null)
  const [payments, setPayments]         = useState<Payment[]>([])
  const [loading, setLoading]           = useState(true)
  const [saving, setSaving]             = useState(false)
  const [connecting, setConnecting]     = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const [toast, setToast]               = useState<string | null>(null)

  // Editable form state
  const [depositEnabled, setDepositEnabled] = useState(false)
  const [depositCents, setDepositCents]     = useState(2500)
  const [amountStr, setAmountStr]           = useState('25.00')
  const [currency, setCurrency]             = useState('CAD')
  const [mandatory, setMandatory]           = useState(true)
  const [expiryMin, setExpiryMin]           = useState(120)
  const [label, setLabel]                   = useState('Appointment Deposit')

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  const load = useCallback(async () => {
    try {
      const [sRes, stRes, pRes] = await Promise.all([
        fetch(`${API}/payments/settings/${tenantId}`),
        fetch(`${API}/stripe-connect/status/${tenantId}`),
        fetch(`${API}/payments/list/${tenantId}`),
      ])
      if (sRes.ok) {
        const s: Settings = await sRes.json()
        setSettings(s)
        setDepositEnabled(s.deposits_enabled)
        setDepositCents(s.deposit_cents)
        setAmountStr((s.deposit_cents / 100).toFixed(2))
        setCurrency(s.currency || 'CAD')
        setMandatory(s.deposit_mandatory)
        setExpiryMin(s.deposit_expiry_min)
        setLabel(s.deposit_label || 'Appointment Deposit')
      }
      if (stRes.ok) setStripeStatus(await stRes.json())
      if (pRes.ok) {
        const d = await pRes.json()
        setPayments(d.payments || [])
      }
    } finally {
      setLoading(false)
    }
  }, [tenantId])

  useEffect(() => {
    load()
    const params  = new URLSearchParams(window.location.search)
    const stripe  = params.get('stripe')
    const acctId  = params.get('account_id')

    if (stripe === 'return' && acctId) {
      // Stripe redirected back after onboarding — verify account server-side
      window.history.replaceState({}, '', window.location.pathname)
      fetch(`${API}/stripe-connect/verify/${tenantId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: acctId }),
      }).then(r => r.json()).then(data => {
        if (data.charges_enabled) {
          showToast('Stripe connected! Charges enabled.')
        } else {
          showToast('Stripe account created — finish onboarding to enable charges.')
        }
        load()
      }).catch(() => {
        showToast('Could not verify Stripe account — try reconnecting.')
        load()
      })
    } else if (stripe === 'refresh' && acctId) {
      // Link expired — restart onboarding for this account
      window.history.replaceState({}, '', window.location.pathname)
      setConnecting(true)
      fetch(`${API}/stripe-connect/onboard/${tenantId}`, { method: 'POST' })
        .then(r => r.json())
        .then(d => { if (d.url) window.location.href = d.url })
        .catch(() => { showToast('Could not refresh onboarding link.'); setConnecting(false) })
    } else if (stripe === 'error') {
      showToast('Stripe connection failed. Please try again.')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [load, tenantId])

  const handleConnect = async () => {
    setConnecting(true)
    try {
      const res = await fetch(`${API}/stripe-connect/onboard/${tenantId}`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        showToast(err.detail || 'Connect failed')
        return
      }
      const { url } = await res.json()
      window.location.href = url
    } catch {
      showToast('Network error — try again.')
    } finally {
      setConnecting(false)
    }
  }

  const handleDisconnect = async () => {
    if (!confirm('Disconnect Stripe? Deposits will stop working immediately.')) return
    setDisconnecting(true)
    try {
      const res = await fetch(`${API}/stripe-connect/disconnect/${tenantId}`, { method: 'POST' })
      if (res.ok) {
        showToast('Stripe disconnected.')
        await load()
      } else {
        showToast('Disconnect failed — try again.')
      }
    } catch {
      showToast('Network error.')
    } finally {
      setDisconnecting(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await fetch(`${API}/payments/settings/${tenantId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          deposits_enabled:   depositEnabled,
          deposit_cents:      depositCents,
          deposit_mandatory:  mandatory,
          deposit_expiry_min: expiryMin,
          deposit_label:      label,
        }),
      })
      if (res.ok) {
        showToast('Settings saved.')
        await load()
      } else {
        const err = await res.json().catch(() => ({}))
        showToast(err.detail || 'Save failed.')
      }
    } catch {
      showToast('Network error.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <LoadingState />

  const isConnected   = stripeStatus?.connected && stripeStatus?.charges_enabled
  const isEligible    = settings?.eligible ?? false
  const totalRevenue  = payments.filter(p => p.status === 'succeeded').reduce((s, p) => s + p.amount_cents, 0)
  const pendingCount  = payments.filter(p => p.status === 'pending').length

  return (
    <>
      <Toast message={toast} />

      <div className="db-topbar">
        <span className="db-topbar-title">Payments</span>
      </div>

      <div className="db-content">
        <div style={{ maxWidth: 640 }}>

          {/* Plan gate */}
          {!isEligible && (
            <div className="db-card" style={{ padding: '18px 20px', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 14, background: 'var(--db-bg-2)' }}>
              <div style={{ color: 'var(--db-muted)', flexShrink: 0 }}><LockIcon /></div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 3 }}>
                  Payments require a Pro or Business plan
                </div>
                <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>
                  Collect deposits from callers during booking. Upgrade to unlock.
                </div>
              </div>
              <Link href={`/dashboard/${tenantId}/subscription`} className="db-btn db-btn--accent-ghost" style={{ flexShrink: 0, fontSize: 12 }}>
                Upgrade
              </Link>
            </div>
          )}

          {/* Stats row */}
          {payments.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
              {[
                { label: 'Total collected', value: `$${(totalRevenue / 100).toFixed(2)}` },
                { label: 'Payments',        value: payments.filter(p => p.status === 'succeeded').length },
                { label: 'Awaiting payment', value: pendingCount },
              ].map(({ label, value }) => (
                <div key={label} className="db-card" style={{ padding: '14px 16px' }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--db-text)', marginBottom: 3 }}>{value}</div>
                  <div style={{ fontSize: 11, color: 'var(--db-muted)' }}>{label}</div>
                </div>
              ))}
            </div>
          )}

          {/* Stripe Connect */}
          <div className="db-card" style={{ marginBottom: 16, overflow: 'hidden' }}>
            <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--db-border-lt)', display: 'flex', alignItems: 'flex-start', gap: 14 }}>
              <div style={{ flexShrink: 0, marginTop: 2 }}><StripeIcon /></div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--db-text)', marginBottom: 4 }}>Stripe Connect</div>
                <div style={{ fontSize: 12, color: 'var(--db-muted)', lineHeight: 1.6 }}>
                  Connect your Stripe account so deposit payments go directly to your bank. Takes ~5 minutes.
                </div>
              </div>
            </div>
            <div style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              {isConnected ? (
                <>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: 13, color: 'var(--db-accent-text)' }}>✓</span>
                      <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--db-accent-text)' }}>Connected</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--db-faint)', marginTop: 2 }}>Charges enabled — deposits will go to your bank</div>
                  </div>
                  <button className="db-btn db-btn--ghost db-btn--sm" onClick={handleDisconnect} disabled={disconnecting || !isEligible}>
                    {disconnecting ? 'Disconnecting…' : 'Disconnect'}
                  </button>
                </>
              ) : stripeStatus?.connected && !stripeStatus.charges_enabled ? (
                <>
                  <div style={{ fontSize: 13, color: '#f59e0b' }}>⚠ Onboarding incomplete — finish setting up your Stripe account</div>
                  <button className="db-btn db-btn--dark" style={{ fontSize: 12 }} onClick={handleConnect} disabled={connecting || !isEligible}>
                    {connecting ? 'Opening…' : 'Continue setup'}
                  </button>
                </>
              ) : (
                <button className="db-btn db-btn--dark" style={{ fontSize: 13 }} onClick={handleConnect} disabled={connecting || !isEligible}>
                  {connecting ? 'Opening Stripe…' : 'Connect Stripe'}
                </button>
              )}
            </div>
          </div>

          {/* Deposit settings */}
          <div className="db-card" style={{ marginBottom: 20, overflow: 'hidden', opacity: isEligible ? 1 : 0.5, pointerEvents: isEligible ? 'auto' : 'none' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--db-border-lt)' }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)' }}>Deposit settings</div>
              <div style={{ fontSize: 12, color: 'var(--db-muted)', marginTop: 2 }}>
                Configure how your AI collects deposits during the booking call.
              </div>
            </div>
            <div style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 16 }}>

              {/* Enable toggle */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--db-text)' }}>Enable deposits</div>
                  <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>AI will request a deposit after every booking</div>
                </div>
                <button
                  role="switch"
                  aria-checked={depositEnabled}
                  onClick={() => setDepositEnabled(v => !v)}
                  disabled={!isConnected}
                  style={{
                    width: 40, height: 22, borderRadius: 11, border: 'none', cursor: isConnected ? 'pointer' : 'not-allowed',
                    background: depositEnabled ? 'var(--db-accent-text)' : 'var(--db-border)',
                    position: 'relative', transition: 'background 0.2s', flexShrink: 0,
                  }}
                >
                  <span style={{
                    position: 'absolute', top: 3, left: depositEnabled ? 21 : 3,
                    width: 16, height: 16, borderRadius: '50%', background: '#fff',
                    transition: 'left 0.2s',
                  }} />
                </button>
              </div>

              {/* Deposit amount */}
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--db-text-2)', marginBottom: 6 }}>
                  Deposit amount ({currency})
                </label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, maxWidth: 200 }}>
                  <span style={{
                    fontSize: 13, fontWeight: 600, color: 'var(--db-text-2)',
                    flexShrink: 0, userSelect: 'none', minWidth: 36,
                  }}>{currency}</span>
                  <input
                    type="text"
                    inputMode="decimal"
                    placeholder="25.00"
                    value={amountStr}
                    onFocus={e => e.target.select()}
                    onChange={e => {
                      const v = e.target.value
                      if (/^(\d{0,6}\.?\d{0,2})?$/.test(v)) {
                        setAmountStr(v)
                        const num = parseFloat(v)
                        if (!isNaN(num)) setDepositCents(Math.round(num * 100))
                      }
                    }}
                    onBlur={() => {
                      const num = parseFloat(amountStr)
                      const clamped = isNaN(num) || num < 0.5 ? 0.5 : num
                      setDepositCents(Math.round(clamped * 100))
                      setAmountStr(clamped.toFixed(2))
                    }}
                    className="db-input"
                    style={{ flex: 1, fontSize: 16, height: 48, textAlign: 'right', letterSpacing: '0.02em' }}
                  />
                </div>
                <div style={{ fontSize: 11, color: 'var(--db-faint)', marginTop: 5 }}>Minimum 0.50 {currency}</div>
              </div>

              {/* Mandatory toggle */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--db-text)' }}>Mandatory</div>
                  <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>
                    {mandatory
                      ? 'Booking is held pending payment'
                      : 'AI offers deposit but booking is confirmed without it'}
                  </div>
                </div>
                <button
                  role="switch"
                  aria-checked={mandatory}
                  onClick={() => setMandatory(v => !v)}
                  style={{
                    width: 40, height: 22, borderRadius: 11, border: 'none', cursor: 'pointer',
                    background: mandatory ? 'var(--db-accent-text)' : 'var(--db-border)',
                    position: 'relative', transition: 'background 0.2s', flexShrink: 0,
                  }}
                >
                  <span style={{
                    position: 'absolute', top: 3, left: mandatory ? 21 : 3,
                    width: 16, height: 16, borderRadius: '50%', background: '#fff',
                    transition: 'left 0.2s',
                  }} />
                </button>
              </div>

              {/* Link expiry */}
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--db-text-2)', marginBottom: 6 }}>
                  Payment link expires after
                </label>
                <select
                  value={expiryMin}
                  onChange={e => setExpiryMin(Number(e.target.value))}
                  className="db-input"
                  style={{ width: 160 }}
                >
                  <option value={30}>30 minutes</option>
                  <option value={60}>1 hour</option>
                  <option value={120}>2 hours</option>
                  <option value={240}>4 hours</option>
                  <option value={480}>8 hours</option>
                  <option value={1440}>24 hours</option>
                </select>
              </div>

              <button
                className="db-btn db-btn--dark"
                style={{ alignSelf: 'flex-start', fontSize: 13 }}
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? 'Saving…' : 'Save settings'}
              </button>
            </div>
          </div>

          {/* Payment history */}
          {payments.length === 0 ? (
            <div className="db-card" style={{ padding: '32px 20px', textAlign: 'center' }}>
              <div style={{ fontSize: 28, marginBottom: 10 }}>💳</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 6 }}>No payments yet</div>
              <div style={{ fontSize: 12, color: 'var(--db-muted)', lineHeight: 1.6 }}>
                Deposits will appear here after your first booking with payment enabled.
              </div>
            </div>
          ) : (
            <div>
              <div className="db-page-heading" style={{ marginBottom: 12, fontSize: 14 }}>Payment history</div>

              {/* Mobile card list — shown below ~600 px */}
              <div className="db-card" style={{ overflow: 'hidden' }} id="payments-mobile">
                <style>{`
                  @media (min-width: 600px) { #payments-mobile .pay-cards { display: none !important; } }
                  @media (max-width: 599px) { #payments-mobile .pay-table-wrap { display: none !important; } }
                `}</style>

                {/* Card layout for mobile */}
                <div className="pay-cards">
                  {payments.map((p, i) => (
                    <div key={p.id} style={{
                      padding: '14px 16px',
                      borderBottom: i < payments.length - 1 ? '1px solid var(--db-border-lt)' : 'none',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: 6 }}>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)' }}>{p.caller_name || '—'}</div>
                          {p.caller_phone && <div style={{ fontSize: 11, color: 'var(--db-faint)', marginTop: 2 }}>{p.caller_phone}</div>}
                        </div>
                        <StatusBadge status={p.status} />
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ fontSize: 12, color: 'var(--db-text-2)' }}>{p.service || '—'}</div>
                        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--db-text)' }}>${(p.amount_cents / 100).toFixed(2)}</span>
                          <span style={{ fontSize: 11, color: 'var(--db-muted)' }}>{new Date(p.created_at).toLocaleDateString()}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Table layout for desktop */}
                <div className="pay-table-wrap" style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 480 }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--db-border-lt)' }}>
                        {['Status', 'Date', 'Customer', 'Service', 'Amount'].map(h => (
                          <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: 'var(--db-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {payments.map((p, i) => (
                        <tr key={p.id} style={{ borderBottom: i < payments.length - 1 ? '1px solid var(--db-border-lt)' : 'none' }}>
                          <td style={{ padding: '12px 14px' }}><StatusBadge status={p.status} /></td>
                          <td style={{ padding: '12px 14px', fontSize: 12, color: 'var(--db-muted)', whiteSpace: 'nowrap' }}>
                            {new Date(p.created_at).toLocaleDateString()}
                          </td>
                          <td style={{ padding: '12px 14px' }}>
                            <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--db-text)' }}>{p.caller_name || '—'}</div>
                            {p.caller_phone && <div style={{ fontSize: 11, color: 'var(--db-faint)' }}>{p.caller_phone}</div>}
                          </td>
                          <td style={{ padding: '12px 14px', fontSize: 13, color: 'var(--db-text-2)' }}>{p.service || '—'}</td>
                          <td style={{ padding: '12px 14px', fontSize: 13, fontWeight: 600, color: 'var(--db-text)', whiteSpace: 'nowrap' }}>
                            ${(p.amount_cents / 100).toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
