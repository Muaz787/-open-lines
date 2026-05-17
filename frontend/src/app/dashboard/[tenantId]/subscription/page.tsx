'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { PaymentForm } from '../PaymentForm'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const PLANS = [
  { id: 'starter',  label: 'Starter',  price: '$79',  perMonth: 7900,  minutes: '150 min / mo', features: ['150 min of AI calls', 'Lead capture', 'SMS notifications'] },
  { id: 'pro',      label: 'Pro',       price: '$159', perMonth: 15900, minutes: '400 min / mo', features: ['400 min of AI calls', 'Calendar booking', 'WhatsApp alerts'] },
  { id: 'business', label: 'Business',  price: '$299', perMonth: 29900, minutes: '900 min / mo', features: ['900 min of AI calls', 'Priority support', 'Custom prompts'] },
] as const

type PlanId = 'starter' | 'pro' | 'business'
type Plan = typeof PLANS[number]

interface PaymentMethod {
  brand: string
  last4: string
  exp_month: number
  exp_year: number
}

interface SubDetails {
  has_subscription: boolean
  plan?: PlanId
  status?: string
  cancel_at_period_end?: boolean
  current_period_start?: number
  current_period_end?: number
  next_invoice_amount?: number
  payment_method?: PaymentMethod
}

interface Invoice {
  id: string
  amount_paid: number
  amount_due: number
  currency: string
  status: string
  created: number
  invoice_pdf?: string
  hosted_invoice_url?: string
}

function fmtAmount(cents: number, currency = 'usd'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: currency.toUpperCase(), minimumFractionDigits: 0,
  }).format(cents / 100)
}

function fmtDate(unix: number): string {
  return new Date(unix * 1000).toLocaleDateString('en-CA', {
    month: 'short', day: 'numeric', year: 'numeric',
  })
}

function cardBrand(brand: string): string {
  const map: Record<string, string> = {
    visa: 'Visa', mastercard: 'Mastercard', amex: 'Amex',
    discover: 'Discover', jcb: 'JCB', unionpay: 'UnionPay',
  }
  return map[brand.toLowerCase()] ?? brand.charAt(0).toUpperCase() + brand.slice(1)
}

function isUpgrade(from: PlanId | undefined, to: PlanId): boolean {
  const order: PlanId[] = ['starter', 'pro', 'business']
  return order.indexOf(to) > order.indexOf(from ?? 'starter')
}

// ── Confirmation modal ───────────────────────────────────────────────────────

function ConfirmModal({
  currentPlan,
  newPlan,
  subDetails,
  processing,
  onConfirm,
  onCancel,
}: {
  currentPlan: Plan | undefined
  newPlan: Plan
  subDetails: SubDetails
  processing: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const hasActiveSub = subDetails.has_subscription &&
    subDetails.status === 'active' &&
    !subDetails.cancel_at_period_end

  const upgrade = hasActiveSub && currentPlan ? isUpgrade(currentPlan.id, newPlan.id) : false
  const downgrade = hasActiveSub && currentPlan && !upgrade && currentPlan.id !== newPlan.id
  const actionLabel = !hasActiveSub ? 'Subscribe' : upgrade ? 'Upgrade' : 'Downgrade'

  const pm = subDetails.payment_method
  const periodEnd = subDetails.current_period_end ? fmtDate(subDetails.current_period_end) : null

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 300, padding: 20,
      }}
      onClick={onCancel}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--bg-2)',
          border: '1px solid var(--border-2)',
          borderRadius: 16,
          padding: '28px 28px 24px',
          width: '100%',
          maxWidth: 420,
          boxShadow: '0 24px 64px rgba(0,0,0,0.28)',
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 6 }}>
            {actionLabel} plan
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--font-syne), sans-serif', letterSpacing: '-0.02em' }}>
            {newPlan.label} · {newPlan.price}/mo
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>
            {newPlan.minutes}
          </div>
        </div>

        {/* From → To */}
        {hasActiveSub && currentPlan && (
          <div style={{
            background: 'var(--bg-3)', border: '1px solid var(--border)',
            borderRadius: 10, padding: '12px 16px', marginBottom: 18,
            display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', gap: 10,
          }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 4 }}>Current</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{currentPlan.label}</div>
              <div style={{ fontSize: 12, color: 'var(--text-3)' }}>{currentPlan.price}/mo</div>
            </div>
            <div style={{ fontSize: 16, color: 'var(--text-3)' }}>→</div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase', color: upgrade ? 'var(--accent)' : 'var(--text-3)', marginBottom: 4 }}>New</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: upgrade ? 'var(--accent)' : 'var(--text)' }}>{newPlan.label}</div>
              <div style={{ fontSize: 12, color: 'var(--text-3)' }}>{newPlan.price}/mo</div>
            </div>
          </div>
        )}

        {/* Charge note */}
        {(!hasActiveSub || upgrade || downgrade) && (
          <div style={{
            fontSize: 12, color: 'var(--text-2)', lineHeight: 1.65,
            padding: '12px 14px', background: 'var(--bg)',
            border: '1px solid var(--border)', borderRadius: 8, marginBottom: 18,
          }}>
            {!hasActiveSub && (
              <>You&apos;ll enter your payment details next. You won&apos;t be charged until you confirm payment.</>
            )}
            {upgrade && (
              <>A prorated charge will apply today for the remainder of your billing period.{periodEnd ? <> Your full {newPlan.price}/mo charge begins on {periodEnd}.</> : null}</>
            )}
            {downgrade && (
              <>Your plan will switch to {newPlan.label} at the end of your current period{periodEnd ? <> on {periodEnd}</> : null}. No charge today.</>
            )}
          </div>
        )}

        {/* Payment method (for upgrades with card on file) */}
        {hasActiveSub && pm && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            fontSize: 12, color: 'var(--text-3)', marginBottom: 20,
          }}>
            <svg width="22" height="15" viewBox="0 0 22 15" fill="none">
              <rect x="0.5" y="0.5" width="21" height="14" rx="2.5" stroke="var(--border-2)"/>
              <rect x="0" y="3.5" width="22" height="3" fill="var(--border)"/>
            </svg>
            <span>
              {cardBrand(pm.brand)} ••••{pm.last4}
              <span style={{ marginLeft: 8, opacity: 0.65 }}>exp {pm.exp_month}/{pm.exp_year}</span>
            </span>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={onCancel}
            disabled={processing}
            style={{
              flex: 1, padding: '11px 0',
              background: 'transparent',
              border: '1px solid var(--border-2)',
              borderRadius: 8, fontSize: 13, color: 'var(--text-3)',
              cursor: processing ? 'default' : 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={processing}
            style={{
              flex: 2, padding: '11px 0',
              background: 'var(--text)', color: 'var(--bg)',
              border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600,
              cursor: processing ? 'default' : 'pointer',
              opacity: processing ? 0.65 : 1,
            }}
          >
            {processing ? 'Processing…' : !hasActiveSub ? 'Continue to payment →' : `Confirm ${actionLabel} →`}
          </button>
        </div>
      </motion.div>
    </div>
  )
}

// ── Cancel confirmation modal ────────────────────────────────────────────────

function CancelModal({
  periodEnd,
  processing,
  onConfirm,
  onCancel,
}: {
  periodEnd: string | null
  processing: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 300, padding: 20 }}
      onClick={onCancel}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--bg-2)', border: '1px solid var(--border-2)',
          borderRadius: 16, padding: '28px 28px 24px', width: '100%', maxWidth: 380,
          boxShadow: '0 24px 64px rgba(0,0,0,0.28)',
        }}
      >
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', marginBottom: 10, fontFamily: 'var(--font-syne), sans-serif' }}>
          Cancel subscription?
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.65, marginBottom: 24 }}>
          Your AI receptionist will stay active until the end of your billing period
          {periodEnd ? ` on ${periodEnd}` : ''}.
          After that, calls will no longer be handled.
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={onCancel} disabled={processing} style={{ flex: 1, padding: '10px 0', background: 'transparent', border: '1px solid var(--border-2)', borderRadius: 8, fontSize: 13, color: 'var(--text-3)', cursor: 'pointer' }}>
            Keep subscription
          </button>
          <button onClick={onConfirm} disabled={processing} style={{ flex: 1, padding: '10px 0', background: 'rgba(255,59,48,.12)', border: '1px solid rgba(255,59,48,.25)', borderRadius: 8, fontSize: 13, fontWeight: 600, color: '#FF3B30', cursor: processing ? 'default' : 'pointer', opacity: processing ? 0.65 : 1 }}>
            {processing ? 'Canceling…' : 'Yes, cancel'}
          </button>
        </div>
      </motion.div>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

function SubscriptionPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const router = useRouter()

  const [subDetails, setSubDetails] = useState<SubDetails | null>(null)
  const [invoices, setInvoices]     = useState<Invoice[]>([])
  const [loading, setLoading]       = useState(true)
  const [toast, setToast]           = useState<string | null>(null)

  const [confirmPlan, setConfirmPlan]     = useState<Plan | null>(null)
  const [confirming, setConfirming]       = useState(false)
  const [showCancel, setShowCancel]       = useState(false)
  const [canceling, setCanceling]         = useState(false)
  const [reactivating, setReactivating]  = useState(false)
  const [payingPlan, setPayingPlan]       = useState<Plan | null>(null)
  const [portalLoading, setPortalLoading] = useState(false)
  const [menuOpen, setMenuOpen]           = useState(false)

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) router.replace('/login')
    })
  }, [router])

  const showToast = (msg: string, ms = 5000) => {
    setToast(msg)
    setTimeout(() => setToast(null), ms)
  }

  const fetchData = useCallback(async () => {
    try {
      const [dRes, iRes] = await Promise.all([
        fetch(`${API}/billing/subscription-details/${tenantId}`),
        fetch(`${API}/billing/invoices/${tenantId}`),
      ])
      if (dRes.ok) setSubDetails(await dRes.json())
      if (iRes.ok) setInvoices(await iRes.json())
    } finally {
      setLoading(false)
    }
  }, [tenantId])

  useEffect(() => { fetchData() }, [fetchData])

  const handlePlanClick = (plan: Plan) => {
    if (!subDetails) return  // still loading or errored
    const currentId = subDetails.plan
    const isActive  = subDetails.status === 'active' && !subDetails.cancel_at_period_end
    if (plan.id === currentId && isActive) return
    setConfirmPlan(plan)
  }

  const handleConfirm = async () => {
    if (!confirmPlan || !subDetails) return
    const isActiveSub = subDetails.has_subscription &&
      subDetails.status === 'active' &&
      !subDetails.cancel_at_period_end

    if (!isActiveSub) {
      // No active subscription → show payment form
      setConfirmPlan(null)
      setPayingPlan(confirmPlan)
      return
    }

    // Active subscription → direct upgrade/downgrade
    setConfirming(true)
    try {
      const res  = await fetch(`${API}/billing/create-subscription`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId, plan: confirmPlan.id }),
      })
      const data = await res.json()
      if (res.ok && data.needs_payment === false) {
        setConfirmPlan(null)
        showToast(`✓ Switched to ${confirmPlan.label} plan`)
        await fetchData()
      } else if (res.ok && data.needs_payment) {
        setConfirmPlan(null)
        setPayingPlan(confirmPlan)
      } else {
        showToast(data.detail ?? 'Plan change failed — try again')
      }
    } catch {
      showToast('Network error — try again')
    } finally {
      setConfirming(false)
    }
  }

  const handleCancelConfirm = async () => {
    setCanceling(true)
    try {
      const res = await fetch(`${API}/billing/cancel/${tenantId}`, { method: 'POST' })
      if (res.ok) {
        showToast('Subscription will cancel at the end of your billing period.')
        setShowCancel(false)
        await fetchData()
      } else {
        showToast('Failed to cancel — try again')
      }
    } catch {
      showToast('Network error — try again')
    } finally {
      setCanceling(false)
    }
  }

  const handleReactivate = async () => {
    setReactivating(true)
    try {
      const res = await fetch(`${API}/billing/reactivate/${tenantId}`, { method: 'POST' })
      if (res.ok) {
        showToast('✓ Subscription reactivated')
        await fetchData()
      } else {
        showToast('Failed to reactivate — try again')
      }
    } catch {
      showToast('Network error — try again')
    } finally {
      setReactivating(false)
    }
  }

  const openPortal = async () => {
    setPortalLoading(true)
    try {
      const res  = await fetch(`${API}/billing/portal/${tenantId}`, { method: 'POST' })
      const data = await res.json()
      if (res.ok && data.url) {
        window.location.href = data.url
      } else {
        showToast(data.detail ?? 'Could not open billing portal')
      }
    } catch {
      showToast('Network error — try again')
    } finally {
      setPortalLoading(false)
    }
  }

  const handleLogout = async () => {
    await supabase.auth.signOut()
    router.replace('/login')
  }

  const currentPlan = PLANS.find(p => p.id === subDetails?.plan)
  const periodEnd   = subDetails?.current_period_end ? fmtDate(subDetails.current_period_end) : null
  const isCanceling = subDetails?.cancel_at_period_end

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
        <div style={{ fontSize: 13, color: 'var(--text-3)' }}>Loading…</div>
      </div>
    )
  }

  return (
    <div className="db-page">

      {/* ── Nav ── */}
      <div className="db-nav">
        <div className="nav-logo">
          <svg width="26" height="26" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
            <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
          </svg>
          <span className="logo-name" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Open Lines</span>
        </div>
        <button
          className="db-hamburger"
          onClick={() => setMenuOpen(o => !o)}
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
        >
          {menuOpen ? (
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
              <line x1="4" y1="4" x2="16" y2="16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
              <line x1="16" y1="4" x2="4" y2="16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
              <line x1="2" y1="5"  x2="18" y2="5"  stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
              <line x1="2" y1="10" x2="18" y2="10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
              <line x1="2" y1="15" x2="18" y2="15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            </svg>
          )}
        </button>
      </div>

      {/* Hamburger dropdown */}
      <AnimatePresence>
        {menuOpen && (
          <motion.div
            className="db-mobile-menu"
            initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.16, ease: 'easeOut' }}
          >
            <Link href={`/dashboard/${tenantId}`} className="db-mobile-item" onClick={() => setMenuOpen(false)}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
                <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
              </svg>
              Dashboard
            </Link>
            <button className="db-mobile-item" style={{ opacity: 0.5, cursor: 'default' }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/>
              </svg>
              Manage Subscription
            </button>
            <div className="db-mobile-divider" />
            <button className="db-mobile-item db-mobile-item-danger" onClick={handleLogout}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
              </svg>
              Sign out
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
            style={{
              position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)',
              background: 'var(--text)', color: 'var(--bg)', padding: '10px 20px',
              borderRadius: 8, fontSize: 13, fontWeight: 500, zIndex: 200,
              boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
            }}
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Modals */}
      <AnimatePresence>
        {confirmPlan && subDetails && (
          <ConfirmModal
            currentPlan={currentPlan}
            newPlan={confirmPlan}
            subDetails={subDetails}
            processing={confirming}
            onConfirm={handleConfirm}
            onCancel={() => setConfirmPlan(null)}
          />
        )}
      </AnimatePresence>
      <AnimatePresence>
        {showCancel && (
          <CancelModal
            periodEnd={periodEnd}
            processing={canceling}
            onConfirm={handleCancelConfirm}
            onCancel={() => setShowCancel(false)}
          />
        )}
      </AnimatePresence>

      {/* ── Body ── */}
      <div className="db-body">

        {/* Back link + header */}
        <div style={{ marginBottom: 28 }}>
          <Link href={`/dashboard/${tenantId}`} style={{ fontSize: 12, color: 'var(--text-3)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 14 }}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M8 2L4 6l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
            Back to Dashboard
          </Link>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--font-syne), sans-serif', letterSpacing: '-0.02em' }}>
            Manage Subscription
          </div>
        </div>

        {/* ── Current plan card ── */}
        {subDetails?.has_subscription && subDetails.status !== 'canceled' ? (
          <div style={{ border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg-2)', overflow: 'hidden', marginBottom: 32 }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>
                {currentPlan?.label ?? subDetails.plan} Plan
              </span>
              {!isCanceling && subDetails.status === 'active' && (
                <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'var(--accent-dim)', color: 'var(--accent)', letterSpacing: '0.06em' }}>ACTIVE</span>
              )}
              {isCanceling && (
                <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'rgba(255,149,0,.1)', color: '#FF9500', letterSpacing: '0.06em' }}>CANCELING</span>
              )}
              {subDetails.status === 'past_due' && (
                <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'rgba(255,59,48,.09)', color: '#FF3B30', letterSpacing: '0.06em' }}>PAST DUE</span>
              )}
            </div>

            <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '14px 24px' }}>
              {/* Billing dates */}
              {subDetails.current_period_end && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 4 }}>
                    {isCanceling ? 'Cancels on' : 'Next billing date'}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{fmtDate(subDetails.current_period_end)}</div>
                </div>
              )}
              {/* Next invoice */}
              {subDetails.next_invoice_amount != null && !isCanceling && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 4 }}>Next charge</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{fmtAmount(subDetails.next_invoice_amount)}</div>
                </div>
              )}
              {/* Payment method */}
              {subDetails.payment_method && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 4 }}>Payment method</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>
                    ••••{subDetails.payment_method.last4}
                    <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-3)', marginLeft: 6 }}>
                      {cardBrand(subDetails.payment_method.brand)}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
                    exp {subDetails.payment_method.exp_month}/{subDetails.payment_method.exp_year}
                  </div>
                </div>
              )}
            </div>

            {/* Action buttons */}
            <div style={{ padding: '0 20px 16px', display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button
                onClick={openPortal}
                disabled={portalLoading}
                style={{
                  padding: '8px 16px', fontSize: 12, fontWeight: 500,
                  border: '1px solid var(--border-2)', borderRadius: 7,
                  background: 'var(--bg)', color: 'var(--text-2)',
                  cursor: portalLoading ? 'default' : 'pointer',
                  opacity: portalLoading ? 0.65 : 1,
                }}
              >
                {portalLoading ? 'Opening…' : 'Update payment method'}
              </button>
              {isCanceling ? (
                <button
                  onClick={handleReactivate}
                  disabled={reactivating}
                  style={{
                    padding: '8px 16px', fontSize: 12, fontWeight: 600,
                    border: '1px solid var(--accent)', borderRadius: 7,
                    background: 'var(--accent-dim)', color: 'var(--accent)',
                    cursor: reactivating ? 'default' : 'pointer',
                    opacity: reactivating ? 0.65 : 1,
                  }}
                >
                  {reactivating ? 'Reactivating…' : 'Reactivate subscription'}
                </button>
              ) : (
                <button
                  onClick={() => setShowCancel(true)}
                  style={{
                    padding: '8px 16px', fontSize: 12, fontWeight: 500,
                    border: '1px solid rgba(255,59,48,.25)', borderRadius: 7,
                    background: 'transparent', color: '#FF3B30',
                    cursor: 'pointer',
                  }}
                >
                  Cancel subscription
                </button>
              )}
            </div>

            {isCanceling && periodEnd && (
              <div style={{ padding: '0 20px 16px', fontSize: 12, color: '#FF9500' }}>
                Your subscription will remain active until {periodEnd}, then automatically cancel.
              </div>
            )}
          </div>
        ) : (
          <div style={{ border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg-2)', padding: '20px', marginBottom: 32 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>No active subscription</div>
            <div style={{ fontSize: 13, color: 'var(--text-3)' }}>Choose a plan below to get started.</div>
          </div>
        )}

        {/* ── Payment form (when collecting new payment) ── */}
        <AnimatePresence>
          {payingPlan && (
            <motion.div
              initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10 }}
              style={{ border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg-2)', marginBottom: 32, overflow: 'hidden' }}
            >
              <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
                Subscribe to {payingPlan.label} — {payingPlan.price}/mo
              </div>
              <PaymentForm
                tenantId={tenantId}
                plan={payingPlan.id}
                planLabel={`${payingPlan.label} · ${payingPlan.price}/mo`}
                onSuccess={async () => {
                  setPayingPlan(null)
                  showToast('🎉 Subscription activated!')
                  await fetchData()
                }}
                onCancel={() => setPayingPlan(null)}
              />
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Change plan ── */}
        {!payingPlan && (
          <div style={{ marginBottom: 32 }}>
            <div className="db-section-title">Change Plan</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
              {PLANS.map(plan => {
                const isCurrent = subDetails?.plan === plan.id && subDetails?.status === 'active' && !isCanceling
                return (
                  <button
                    key={plan.id}
                    onClick={() => handlePlanClick(plan)}
                    style={{
                      textAlign: 'left', padding: '16px 18px',
                      border: `1px solid ${isCurrent ? 'var(--accent)' : 'var(--border-2)'}`,
                      borderRadius: 10,
                      background: isCurrent ? 'var(--accent-dim)' : 'var(--bg-2)',
                      cursor: isCurrent ? 'default' : 'pointer',
                      transition: 'border-color 0.15s',
                    }}
                  >
                    <div style={{ fontSize: 14, fontWeight: 700, color: isCurrent ? 'var(--accent)' : 'var(--text)', marginBottom: 2, display: 'flex', alignItems: 'center', gap: 6 }}>
                      {plan.label}
                      {isCurrent && <span style={{ fontSize: 10 }}>✓</span>}
                    </div>
                    <div style={{ fontSize: 19, fontWeight: 700, color: isCurrent ? 'var(--accent)' : 'var(--text)', fontFamily: 'var(--font-syne), sans-serif', marginBottom: 2 }}>
                      {plan.price}<span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-3)' }}>/mo</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 10 }}>{plan.minutes}</div>
                    {plan.features.map(f => (
                      <div key={f} style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 3, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ color: 'var(--accent)', fontSize: 10 }}>✓</span> {f}
                      </div>
                    ))}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* ── Billing history ── */}
        {invoices.length > 0 && (
          <div style={{ marginBottom: 32 }}>
            <div className="db-section-title">Billing History</div>
            <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', background: 'var(--bg-2)' }}>
              {invoices.map((inv, i) => (
                <div key={inv.id} style={{
                  display: 'grid', gridTemplateColumns: '1fr auto auto auto',
                  alignItems: 'center', gap: 16,
                  padding: '12px 18px',
                  borderTop: i > 0 ? '1px solid var(--border)' : 'none',
                }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>
                      {fmtDate(inv.created)}
                    </div>
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
                    {fmtAmount(inv.amount_paid || inv.amount_due, inv.currency)}
                  </div>
                  <span style={{
                    fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                    padding: '2px 8px', borderRadius: 4,
                    background: inv.status === 'paid' ? 'var(--accent-dim)' : 'rgba(255,149,0,.1)',
                    color: inv.status === 'paid' ? 'var(--accent)' : '#FF9500',
                  }}>
                    {inv.status}
                  </span>
                  {(inv.invoice_pdf || inv.hosted_invoice_url) && (
                    <a
                      href={inv.invoice_pdf ?? inv.hosted_invoice_url ?? '#'}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: 12, color: 'var(--text-3)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
                      </svg>
                      PDF
                    </a>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  )
}

export default function SubscriptionPageWrapper() {
  return (
    <Suspense fallback={
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
        <div style={{ fontSize: 13, color: 'var(--text-3)' }}>Loading…</div>
      </div>
    }>
      <SubscriptionPage />
    </Suspense>
  )
}
