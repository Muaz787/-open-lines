'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { PaymentForm, UpdatePaymentForm, UpgradePaymentForm } from '../PaymentForm'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const PLANS = [
  { id: 'starter',  label: 'Starter',  price: '$99',  perMonth: 9900,  priceYear: '$990',   saveYear: '$198', minutes: '150 min / mo', features: ['150 min of AI calls', 'Lead capture', 'SMS notifications'] },
  { id: 'pro',      label: 'Pro',       price: '$199', perMonth: 19900, priceYear: '$1,990', saveYear: '$398', minutes: '400 min / mo', features: ['400 min of AI calls', 'Calendar booking', 'WhatsApp alerts'] },
  { id: 'business', label: 'Business',  price: '$379', perMonth: 37900, priceYear: '$3,790', saveYear: '$758', minutes: '900 min / mo', features: ['900 min of AI calls', 'Priority support', 'Custom prompts'] },
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
  interval?: 'month' | 'year'
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
  prorationAmount,
  prorationLoading,
  onConfirm,
  onCancel,
}: {
  currentPlan: Plan | undefined
  newPlan: Plan
  subDetails: SubDetails
  processing: boolean
  prorationAmount?: number | null
  prorationLoading?: boolean
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
        className="plan-confirm-modal"
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
            {upgrade && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-2)' }}>
                {prorationLoading ? 'Calculating charge…' :
                  prorationAmount != null
                    ? `Charged today: ${new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD', minimumFractionDigits: 2 }).format(prorationAmount / 100)} (prorated)`
                    : 'A prorated amount will be charged today'
                }
              </div>
            )}
            {downgrade && periodEnd && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-3)' }}>
                Takes effect {periodEnd}. No charge today — your saved card will be billed at the new rate on {periodEnd}.
              </div>
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

interface SidebarTenant {
  id: string; business_name: string; industry: string
  twilio_phone_number?: string; subscription_plan?: string; subscription_status?: string
}

function SubscriptionPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [sidebarTenant, setSidebarTenant]   = useState<SidebarTenant | null>(null)

  const [subDetails, setSubDetails] = useState<SubDetails | null>(null)
  const [invoices, setInvoices]     = useState<Invoice[]>([])
  const [toast, setToast]           = useState<string | null>(null)

  const [confirmPlan, setConfirmPlan]     = useState<Plan | null>(null)
  const [confirming, setConfirming]       = useState(false)
  const [showCancel, setShowCancel]       = useState(false)
  const [canceling, setCanceling]         = useState(false)
  const [reactivating, setReactivating]  = useState(false)
  const [payingPlan, setPayingPlan]       = useState<Plan | null>(null)
  const [billingInterval, setBillingInterval] = useState<'month' | 'year'>('month')
  const [updatingCard, setUpdatingCard]   = useState(false)
  const [prorationAmount, setProrationAmount]   = useState<number | null>(null)
  const [prorationLoading, setProrationLoading] = useState(false)
  const [upgradePayment, setUpgradePayment]     = useState<{
    clientSecret: string; amountDue: number; currency: string; plan: Plan; subscriptionId: string
  } | null>(null)

  useEffect(() => {
    fetch(`${API}/onboarding/status/${tenantId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setSidebarTenant(d) })
      .catch(() => {})
  }, [tenantId])

  const showToast = (msg: string, ms = 5000) => {
    setToast(msg)
    setTimeout(() => setToast(null), ms)
  }

  const fetchData = useCallback(async () => {
    const [dRes, iRes] = await Promise.all([
      fetch(`${API}/billing/subscription-details/${tenantId}`),
      fetch(`${API}/billing/invoices/${tenantId}`),
    ])
    if (dRes.ok) setSubDetails(await dRes.json())
    if (iRes.ok) setInvoices(await iRes.json())
  }, [tenantId])

  useEffect(() => { fetchData() }, [fetchData])

  useEffect(() => {
    if (!confirmPlan || !subDetails?.has_subscription || !subDetails?.plan) {
      setProrationAmount(null)
      return
    }
    const order: PlanId[] = ['starter', 'pro', 'business']
    const isUp = order.indexOf(confirmPlan.id) > order.indexOf(subDetails.plan as PlanId)
    if (!isUp) { setProrationAmount(null); return }

    setProrationLoading(true)
    fetch(`${API}/billing/proration-preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tenant_id: tenantId, plan: confirmPlan.id }),
    })
      .then(r => r.json())
      .then(d => { if (d.amount_due != null) setProrationAmount(d.amount_due) })
      .catch(() => {})
      .finally(() => setProrationLoading(false))
  }, [confirmPlan, subDetails?.has_subscription, subDetails?.plan, tenantId])

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
      // New subscriber — show payment form
      setConfirmPlan(null)
      setPayingPlan(confirmPlan)
      return
    }

    const order: PlanId[] = ['starter', 'pro', 'business']
    const isUp = order.indexOf(confirmPlan.id) > order.indexOf((subDetails.plan ?? 'starter') as PlanId)

    setConfirming(true)
    try {
      if (isUp) {
        // Upgrade — collect prorated payment
        const res  = await fetch(`${API}/billing/upgrade-plan`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tenant_id: tenantId, plan: confirmPlan.id }),
        })
        const data = await res.json()
        if (!res.ok) { showToast(data.detail ?? 'Upgrade failed — try again'); return }

        setConfirmPlan(null)
        if (data.needs_payment) {
          setUpgradePayment({
            clientSecret: data.client_secret,
            amountDue:    data.amount_due,
            currency:     data.currency ?? 'cad',
            plan:         confirmPlan,
            subscriptionId: data.subscription_id,
          })
        } else {
          showToast(`✓ Upgraded to ${confirmPlan.label}`)
          await fetchData().catch(() => {})
        }
      } else {
        // Downgrade — schedule for next cycle
        const res  = await fetch(`${API}/billing/downgrade-plan`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tenant_id: tenantId, plan: confirmPlan.id }),
        })
        const data = await res.json()
        if (!res.ok) { showToast(data.detail ?? 'Downgrade failed — try again'); return }

        setConfirmPlan(null)
        const effectiveDate = data.effective_date
          ? new Date(data.effective_date * 1000).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' })
          : 'next billing date'
        showToast(`↓ Downgraded to ${confirmPlan.label} — takes effect ${effectiveDate}`)
        await fetchData().catch(() => {})
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'unknown'
      showToast(`Network error — ${msg}`)
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

  const currentPlan = PLANS.find(p => p.id === subDetails?.plan)
  const periodEnd   = subDetails?.current_period_end ? fmtDate(subDetails.current_period_end) : null
  const isCanceling = subDetails?.cancel_at_period_end
  const isActiveSub = !!subDetails?.has_subscription && subDetails?.status === 'active' && !subDetails?.cancel_at_period_end

  return (
    <>

        {/* Desktop topbar */}
        <div className="db-topbar">
          <span className="db-topbar-title">Billing &amp; Payments</span>
          {sidebarTenant?.twilio_phone_number && (
            <div style={{ fontSize: 12, color: '#888' }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#3dba72', marginRight: 5 }} />
              {sidebarTenant.twilio_phone_number}
            </div>
          )}
        </div>

      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
            style={{
              position: 'fixed', top: 72, left: '50%', transform: 'translateX(-50%)',
              background: 'var(--text)', color: 'var(--bg)', padding: '10px 20px',
              borderRadius: 8, fontSize: 13, fontWeight: 500, zIndex: 400,
              boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
              whiteSpace: 'nowrap',
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
            prorationAmount={prorationAmount}
            prorationLoading={prorationLoading}
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
      <div className="db-content">
        <div className="db-body">

        {/* ── Current plan card ── */}
        {subDetails?.has_subscription && subDetails.status !== 'canceled' ? (
          <div style={{ border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg-2)', overflow: 'hidden', marginBottom: 32 }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>
                {currentPlan?.label ?? subDetails.plan} Plan
              </span>
              {!isCanceling && subDetails.status === 'active' && (
                <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'var(--accent-dim)', color: 'var(--accent-text)', letterSpacing: '0.06em' }}>ACTIVE</span>
              )}
              {isCanceling && (
                <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'rgba(255,149,0,.1)', color: '#FF9500', letterSpacing: '0.06em' }}>CANCELING</span>
              )}
              {subDetails.status === 'past_due' && (
                <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'rgba(255,59,48,.09)', color: '#FF3B30', letterSpacing: '0.06em' }}>PAST DUE</span>
              )}
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-3)' }}>
                Billed {subDetails.interval === 'year' ? 'annually' : 'monthly'}
              </span>
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
                onClick={() => setUpdatingCard(true)}
                style={{
                  padding: '8px 16px', fontSize: 12, fontWeight: 500,
                  border: '1px solid var(--border-2)', borderRadius: 7,
                  background: 'var(--bg)', color: 'var(--text-2)',
                  cursor: 'pointer',
                }}
              >
                Update payment method
              </button>
              {isCanceling ? (
                <button
                  onClick={handleReactivate}
                  disabled={reactivating}
                  style={{
                    padding: '8px 16px', fontSize: 12, fontWeight: 600,
                    border: '1px solid var(--accent)', borderRadius: 7,
                    background: 'var(--accent-dim)', color: 'var(--accent-text)',
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

        {/* ── Upgrade payment (proration charge) ── */}
        <AnimatePresence>
          {upgradePayment && (
            <motion.div
              initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10 }}
              style={{ maxWidth: 460, marginBottom: 32 }}
            >
              <div style={{ border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg-2)', overflow: 'hidden' }}>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>Upgrade to {upgradePayment.plan.label}</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-text)' }}>
                    {upgradePayment.plan.price}<span style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-3)' }}>/mo</span>
                  </span>
                </div>
                <UpgradePaymentForm
                  tenantId={tenantId}
                  subscriptionId={upgradePayment.subscriptionId}
                  clientSecret={upgradePayment.clientSecret}
                  amountDue={upgradePayment.amountDue}
                  currency={upgradePayment.currency}
                  planLabel={`${upgradePayment.plan.label} · ${upgradePayment.plan.price}/mo`}
                  onSuccess={async () => {
                    setUpgradePayment(null)
                    showToast(`✓ Upgraded to ${upgradePayment.plan.label}`)
                    await fetchData().catch(() => {})
                  }}
                  onCancel={() => setUpgradePayment(null)}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Update payment method (inline card form) ── */}
        <AnimatePresence>
          {updatingCard && (
            <motion.div
              initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10 }}
              style={{ maxWidth: 460, marginBottom: 32 }}
            >
              <div style={{ border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg-2)', overflow: 'hidden' }}>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>Update payment method</span>
                </div>
                <UpdatePaymentForm
                  tenantId={tenantId}
                  onSuccess={async () => {
                    setUpdatingCard(false)
                    showToast('✓ Payment method updated')
                    await fetchData()
                  }}
                  onCancel={() => setUpdatingCard(false)}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Payment form (when collecting new payment) ── */}
        <AnimatePresence>
          {payingPlan && (
            <motion.div
              initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10 }}
              style={{ maxWidth: 460, marginBottom: 32 }}
            >
              <div style={{ border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg-2)', overflow: 'hidden' }}>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
                    {payingPlan.label} Plan
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-text)' }}>
                    {billingInterval === 'year' ? payingPlan.priceYear : payingPlan.price}
                    <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-3)' }}>{billingInterval === 'year' ? '/yr' : '/mo'}</span>
                  </span>
                </div>
                <PaymentForm
                  tenantId={tenantId}
                  plan={payingPlan.id}
                  interval={billingInterval}
                  planLabel={`${payingPlan.label} · ${billingInterval === 'year' ? payingPlan.priceYear + '/yr' : payingPlan.price + '/mo'}`}
                  onSuccess={async () => {
                    setPayingPlan(null)
                    showToast('🎉 Subscription activated!')
                    await fetchData()
                  }}
                  onCancel={() => setPayingPlan(null)}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Change plan ── */}
        {!payingPlan && (
          <div style={{ marginBottom: 32 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div className="db-section-title">{isActiveSub ? 'Change Plan' : 'Choose a Plan'}</div>
              {/* Monthly / Annual toggle — only for new subscribers (plan changes keep current interval) */}
              {!isActiveSub && (
                <div style={{ display: 'inline-flex', border: '1px solid var(--border-2)', borderRadius: 8, overflow: 'hidden' }}>
                  {(['month', 'year'] as const).map(iv => (
                    <button
                      key={iv}
                      onClick={() => setBillingInterval(iv)}
                      style={{
                        fontSize: 12, fontWeight: 600, padding: '6px 14px', border: 'none', cursor: 'pointer',
                        background: billingInterval === iv ? 'var(--accent-dim)' : 'transparent',
                        color: billingInterval === iv ? 'var(--accent)' : 'var(--text-3)',
                      }}
                    >
                      {iv === 'month' ? 'Monthly' : 'Annual'}
                      {iv === 'year' && <span style={{ marginLeft: 5, fontSize: 10, color: '#16a34a' }}>2 months free</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginTop: 12 }}>
              {PLANS.map(plan => {
                const isCurrent = subDetails?.plan === plan.id && subDetails?.status === 'active' && !isCanceling
                const annual = !isActiveSub && billingInterval === 'year'
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
                      {annual ? plan.priceYear : plan.price}
                      <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-3)' }}>{annual ? '/yr' : '/mo'}</span>
                    </div>
                    {annual && (
                      <div style={{ fontSize: 11, color: '#16a34a', fontWeight: 600, marginBottom: 4 }}>Save {plan.saveYear}/yr</div>
                    )}
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 10 }}>{plan.minutes}</div>
                    {plan.features.map(f => (
                      <div key={f} style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 3, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ color: 'var(--accent-text)', fontSize: 10 }}>✓</span> {f}
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
                <div key={inv.id} className="invoice-row" style={{
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
                  <div className="invoice-row-amount" style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
                    {fmtAmount(inv.amount_paid || inv.amount_due, inv.currency)}
                  </div>
                  <span className="invoice-row-status" style={{
                    fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                    padding: '2px 8px', borderRadius: 4,
                    background: inv.status === 'paid' ? 'var(--accent-dim)' : 'rgba(255,149,0,.1)',
                    color: inv.status === 'paid' ? 'var(--accent)' : '#FF9500',
                  }}>
                    {inv.status}
                  </span>
                  {(inv.invoice_pdf || inv.hosted_invoice_url) ? (
                    <a
                      className="invoice-row-link"
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
                  ) : <div />}
                </div>
              ))}
            </div>
          </div>
        )}

        </div>{/* /db-body */}
      </div>{/* /db-content */}
    </>
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
