'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { motion } from 'framer-motion'

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
  const color = pct >= 100 ? '#ef4444' : pct >= 80 ? '#d97706' : '#3dba72'
  const bgColor = pct >= 100 ? '#fef2f2' : pct >= 80 ? '#fffbeb' : '#f0fdf4'

  return (
    <div>
      <div style={{
        height: 10, borderRadius: 10,
        background: bgColor,
        border: `1px solid ${color}30`,
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
        <div style={{ fontSize: 10, color: '#ef4444', marginTop: 4, fontWeight: 600 }}>
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
  const barColor = pct >= 100 ? '#ef4444' : pct >= 80 ? '#d97706' : '#3dba72'

  return (
    <>
      {/* Desktop topbar */}
      <div className="db-topbar">
        <span className="db-topbar-title">Usage</span>
        <div className="db-topbar-right">
          <Link
            href={`/dashboard/${tenantId}/subscription`}
            style={{ fontSize: 11, fontWeight: 600, color: '#3dba72', textDecoration: 'none', padding: '5px 11px', border: '1px solid #3dba72', borderRadius: 6, background: '#f0fdf4' }}
          >
            Manage plan →
          </Link>
        </div>
      </div>

      <div className="db-content">
        {loading ? (
          <div className="db-empty-v2" style={{ paddingTop: 60 }}>
            <div className="db-empty-v2-title">Loading…</div>
          </div>
        ) : !usage ? (
          <div className="db-empty-v2" style={{ paddingTop: 60 }}>
            <div className="db-empty-v2-title">Could not load usage data.</div>
          </div>
        ) : (
          <>
            {/* ── Main usage card ── */}
            <div className="db-section-card" style={{ marginBottom: 14 }}>
              <div style={{ padding: '18px 18px 0' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#888', marginBottom: 4 }}>
                      Current Plan
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 18, fontWeight: 700, color: '#16161a' }}>
                        {usage.plan.charAt(0).toUpperCase() + usage.plan.slice(1)}
                      </span>
                      <span style={{ fontSize: 11, color: '#888' }}>
                        {PLAN_PRICE[usage.plan] ?? ''}
                      </span>
                      {tenant?.subscription_status === 'active' && (
                        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: '#f0fdf4', color: '#16a34a', letterSpacing: '0.06em' }}>
                          ACTIVE
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 28, fontWeight: 700, color: barColor, fontFamily: 'var(--font-mono), monospace', letterSpacing: '-1px' }}>
                      {pct}%
                    </div>
                    <div style={{ fontSize: 11, color: '#888' }}>of allowance used</div>
                  </div>
                </div>

                {/* Progress bar */}
                <div style={{ marginBottom: 6 }}>
                  <ProgressBar pct={pct} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#aaa', marginBottom: 18, fontFamily: 'var(--font-mono), monospace' }}>
                  <span>0 min</span>
                  <span>{Math.round(usage.minutes_included * 0.8)} min (80%)</span>
                  <span>{usage.minutes_included} min</span>
                </div>
              </div>

              {/* Divider */}
              <div style={{ borderTop: '1px solid #f0ede8' }} />

              {/* Stat grid */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', borderBottom: 'none' }}>
                {[
                  { label: 'Included',  value: usage.minutes_included,  unit: 'min', color: '#16161a' },
                  { label: 'Used',      value: usage.minutes_used,       unit: 'min', color: barColor },
                  { label: 'Remaining', value: usage.minutes_remaining,  unit: 'min', color: usage.minutes_remaining > 0 ? '#16161a' : '#ef4444' },
                  { label: 'Overage',   value: usage.overage_minutes,    unit: 'min', color: usage.overage_minutes > 0 ? '#ef4444' : '#16161a' },
                ].map(({ label, value, unit, color }, i, arr) => (
                  <div key={label} style={{
                    padding: '16px 18px',
                    borderRight: i < arr.length - 1 ? '1px solid #f0ede8' : 'none',
                  }}>
                    <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#aaa', marginBottom: 6 }}>
                      {label}
                    </div>
                    <div style={{ fontSize: 22, fontWeight: 700, color, fontFamily: 'var(--font-mono), monospace', letterSpacing: '-0.5px' }}>
                      {value.toLocaleString()}
                      <span style={{ fontSize: 11, fontWeight: 400, color: '#aaa', fontFamily: 'var(--font-dm), sans-serif', marginLeft: 3 }}>{unit}</span>
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
                    <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#888', marginBottom: 4 }}>
                      Overage Charges
                    </div>
                    <div style={{ fontSize: 13, color: '#555' }}>
                      {usage.overage_minutes} overage min × $0.35 =&nbsp;
                      <span style={{ fontWeight: 700, color: '#ef4444' }}>
                        ${(usage.overage_cost_cents / 100).toFixed(2)}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: '#aaa', marginTop: 3 }}>
                      Billed automatically at end of billing period via Stripe
                    </div>
                  </div>
                  <Link
                    href={`/dashboard/${tenantId}/subscription`}
                    style={{ fontSize: 12, fontWeight: 600, color: '#3dba72', textDecoration: 'none', padding: '7px 13px', border: '1px solid #3dba72', borderRadius: 7, background: '#f0fdf4', whiteSpace: 'nowrap' }}
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
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#3dba72', flexShrink: 0 }} />
                  <div>
                    <span style={{ fontSize: 12, color: '#555' }}>
                      Billing period started&nbsp;
                      <span style={{ fontWeight: 600, color: '#16161a' }}>
                        {new Date(usage.billing_period_anchor + 'T00:00:00').toLocaleDateString('en-CA', {
                          month: 'long', day: 'numeric', year: 'numeric',
                        })}
                      </span>
                    </span>
                    <span style={{ fontSize: 11, color: '#aaa', marginLeft: 8 }}>
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
                  { id: 'starter',  label: 'Starter',  price: '$99/mo',  note: '+$0.35/min overage' },
                  { id: 'pro',      label: 'Pro',       price: '$199/mo', note: '+$0.35/min overage' },
                  { id: 'business', label: 'Business',  price: '$379/mo', note: '+$0.35/min overage' },
                ] as const).map(({ id, label, price, note }, i, arr) => {
                  const mins = PLAN_ALLOCATIONS[id] ?? 0
                  const isCurrent = usage.plan === id
                  return (
                    <div key={id} style={{
                      display: 'flex', alignItems: 'center', padding: '12px 18px',
                      borderBottom: i < arr.length - 1 ? '1px solid #f0ede8' : 'none',
                      background: isCurrent ? '#fafffe' : 'transparent',
                    }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                          <span style={{ fontSize: 13, fontWeight: isCurrent ? 700 : 500, color: '#16161a' }}>{label}</span>
                          {isCurrent && (
                            <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: '#f0fdf4', color: '#16a34a', letterSpacing: '0.07em' }}>
                              CURRENT
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 11, color: '#aaa', marginTop: 2 }}>{note}</div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#16161a', fontFamily: 'var(--font-mono), monospace' }}>
                          {mins.toLocaleString()} min
                        </div>
                        <div style={{ fontSize: 11, color: '#888' }}>{price}</div>
                      </div>
                      {!isCurrent && usage.plan !== 'business' && (
                        <Link
                          href={`/dashboard/${tenantId}/subscription`}
                          style={{ marginLeft: 14, fontSize: 11, fontWeight: 600, color: '#3dba72', textDecoration: 'none', padding: '5px 10px', border: '1px solid #3dba72', borderRadius: 6, background: '#f0fdf4', whiteSpace: 'nowrap' }}
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
