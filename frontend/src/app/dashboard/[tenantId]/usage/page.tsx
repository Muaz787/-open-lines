'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { capitalize } from '../lib/format'
import { LoadingState, EmptyState } from '../components/PageStates'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const PLAN_ALLOCATIONS: Record<string, number> = {
  starter: 150,
  pro: 400,
  business: 900,
}

const PLAN_PRICE: Record<string, string> = {
  starter: '$99/mo',
  pro: '$199/mo',
  business: '$379/mo',
}

interface UsageSummary {
  plan: string
  minutes_included: number
  minutes_used: number
  minutes_remaining: number
  overage_minutes: number
  overage_cost_cents: number
  usage_pct: number
  billing_period_anchor?: string
}

interface Tenant {
  id: string
  business_name: string
  industry: string
  subscription_plan?: string
  subscription_status?: string
}

function ProgressBar({ pct }: { pct: number }) {
  const capped = Math.min(pct, 100)
  const color = pct >= 100 ? 'var(--db-danger)' : pct >= 80 ? 'var(--db-warn-text)' : 'var(--db-accent)'
  const bgColor = pct >= 100 ? 'var(--db-danger-bg)' : pct >= 80 ? 'var(--db-warn-bg)' : 'var(--db-accent-bg)'

  return (
    <div>
      <div style={{
        height: 10, borderRadius: 10,
        background: bgColor,
        border: '1px solid var(--db-border)',
        overflow: 'hidden',
        position: 'relative',
      }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${capped}%` }}
          transition={{ duration: 0.7, ease: 'easeOut' }}
          style={{ height: '100%', background: color, borderRadius: 10 }}
        />
      </div>
      {pct > 100 && (
        <div style={{ fontSize: 10, color: 'var(--db-danger-text)', marginTop: 4, fontWeight: 600 }}>
          {Math.round(pct - 100)}% over limit — overage charges apply
        </div>
      )}
    </div>
  )
}

export default function UsagePage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [tenant, setTenant]   = useState<Tenant | null>(null)
  const [usage, setUsage]     = useState<UsageSummary | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [tenantRes, usageRes] = await Promise.all([
        fetch(`${API}/onboarding/status/${tenantId}`),
        fetch(`${API}/billing/usage/${tenantId}`),
      ])
      if (tenantRes.ok) setTenant(await tenantRes.json())
      if (usageRes.ok) setUsage(await usageRes.json())
    } catch {}
    finally { setLoading(false) }
  }, [tenantId])

  useEffect(() => { fetchData() }, [fetchData])

  const pct = usage?.usage_pct ?? 0
  const barColor = pct >= 100 ? 'var(--db-danger)' : pct >= 80 ? 'var(--db-warn-text)' : 'var(--db-accent)'

  return (
    <>
      {/* Desktop topbar */}
      <div className="db-topbar">
        <span className="db-topbar-title">Usage</span>
        <div className="db-topbar-right">
          <Link
            href={`/dashboard/${tenantId}/subscription`}
            className="db-btn db-btn--accent-ghost db-btn--sm"
          >
            Manage plan →
          </Link>
        </div>
      </div>

      <div className="db-content">
        {loading ? (
          <LoadingState />
        ) : !usage ? (
          <EmptyState title="Could not load usage data." />
        ) : (
          <>
            {/* ── Main usage card ── */}
            <div className="db-section-card" style={{ marginBottom: 14 }}>
              <div style={{ padding: '18px 18px 0' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--db-muted)', marginBottom: 4 }}>
                      Current Plan
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--db-text)' }}>
                        {capitalize(usage.plan)}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--db-muted)' }}>
                        {PLAN_PRICE[usage.plan] ?? ''}
                      </span>
                      {tenant?.subscription_status === 'active' && (
                        <span className="db-badge db-badge--success">Active</span>
                      )}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 28, fontWeight: 700, color: barColor, fontFamily: 'var(--font-mono), monospace', letterSpacing: '-1px' }}>
                      {pct}%
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--db-muted)' }}>of allowance used</div>
                  </div>
                </div>

                {/* Progress bar */}
                <div style={{ marginBottom: 6 }}>
                  <ProgressBar pct={pct} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--db-faint)', marginBottom: 18, fontFamily: 'var(--font-mono), monospace' }}>
                  <span>0 min</span>
                  <span>{Math.round(usage.minutes_included * 0.8)} min (80%)</span>
                  <span>{usage.minutes_included} min</span>
                </div>
              </div>

              {/* Divider */}
              <div style={{ borderTop: '1px solid var(--db-border-lt)' }} />

              {/* Stat grid */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', borderBottom: 'none' }}>
                {[
                  { label: 'Included',  value: usage.minutes_included,  unit: 'min', color: 'var(--db-text)' },
                  { label: 'Used',      value: usage.minutes_used,       unit: 'min', color: barColor },
                  { label: 'Remaining', value: usage.minutes_remaining,  unit: 'min', color: usage.minutes_remaining > 0 ? 'var(--db-text)' : 'var(--db-danger)' },
                  { label: 'Overage',   value: usage.overage_minutes,    unit: 'min', color: usage.overage_minutes > 0 ? 'var(--db-danger)' : 'var(--db-text)' },
                ].map(({ label, value, unit, color }, i, arr) => (
                  <div key={label} style={{
                    padding: '16px 18px',
                    borderRight: i < arr.length - 1 ? '1px solid var(--db-border-lt)' : 'none',
                  }}>
                    <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--db-faint)', marginBottom: 6 }}>
                      {label}
                    </div>
                    <div style={{ fontSize: 22, fontWeight: 700, color, fontFamily: 'var(--font-mono), monospace', letterSpacing: '-0.5px' }}>
                      {value.toLocaleString()}
                      <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--db-faint)', fontFamily: 'var(--font-dm), sans-serif', marginLeft: 3 }}>{unit}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* ── Overage cost card (only if overage exists) ── */}
            {usage.overage_minutes > 0 && (
              <div className="db-section-card" style={{ marginBottom: 14 }}>
                <div style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--db-muted)', marginBottom: 4 }}>
                      Overage Charges
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--db-text-2)' }}>
                      {usage.overage_minutes} overage min × $0.69 =&nbsp;
                      <span style={{ fontWeight: 700, color: 'var(--db-danger-text)' }}>
                        ${(usage.overage_cost_cents / 100).toFixed(2)}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--db-faint)', marginTop: 3 }}>
                      Billed automatically at end of billing period via Stripe
                    </div>
                  </div>
                  <Link
                    href={`/dashboard/${tenantId}/subscription`}
                    className="db-btn db-btn--accent-ghost"
                  >
                    Upgrade plan →
                  </Link>
                </div>
              </div>
            )}

            {/* ── Billing period ── */}
            {usage.billing_period_anchor && (
              <div className="db-section-card" style={{ marginBottom: 14 }}>
                <div style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--db-accent)', flexShrink: 0 }} />
                  <div>
                    <span style={{ fontSize: 12, color: 'var(--db-text-2)' }}>
                      Billing period started&nbsp;
                      <span style={{ fontWeight: 600, color: 'var(--db-text)' }}>
                        {new Date(usage.billing_period_anchor + 'T00:00:00').toLocaleDateString('en-CA', {
                          month: 'long', day: 'numeric', year: 'numeric',
                        })}
                      </span>
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--db-faint)', marginLeft: 8 }}>
                      · resets monthly
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* ── Plan comparison ── */}
            <div className="db-section-card">
              <div className="db-section-hdr">
                <div className="db-section-title-row">
                  <div className="db-section-icon" style={{ background: '#f4f3f0' }}>📊</div>
                  <span className="db-section-name">Plan Allowances</span>
                </div>
              </div>
              <div>
                {([
                  { id: 'starter',  label: 'Starter',  price: '$99/mo',  note: '+$0.69/min overage' },
                  { id: 'pro',      label: 'Pro',       price: '$199/mo', note: '+$0.69/min overage' },
                  { id: 'business', label: 'Business',  price: '$379/mo', note: '+$0.69/min overage' },
                ] as const).map(({ id, label, price, note }, i, arr) => {
                  const mins = PLAN_ALLOCATIONS[id] ?? 0
                  const isCurrent = usage.plan === id
                  return (
                    <div key={id} style={{
                      display: 'flex', alignItems: 'center', padding: '12px 18px',
                      borderBottom: i < arr.length - 1 ? '1px solid var(--db-border-lt)' : 'none',
                      background: isCurrent ? 'var(--db-accent-bg)' : 'transparent',
                    }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                          <span style={{ fontSize: 13, fontWeight: isCurrent ? 700 : 500, color: 'var(--db-text)' }}>{label}</span>
                          {isCurrent && (
                            <span className="db-badge db-badge--success">Current</span>
                          )}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--db-faint)', marginTop: 2 }}>{note}</div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', fontFamily: 'var(--font-mono), monospace' }}>
                          {mins.toLocaleString()} min
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--db-muted)' }}>{price}</div>
                      </div>
                      {!isCurrent && usage.plan !== 'business' && (
                        <Link
                          href={`/dashboard/${tenantId}/subscription`}
                          className="db-btn db-btn--accent-ghost db-btn--sm"
                          style={{ marginLeft: 14 }}
                        >
                          Switch →
                        </Link>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}
