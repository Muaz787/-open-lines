'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'
import { supabase } from '@/lib/supabase'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const BOOKING_INDUSTRIES = new Set([
  'realtor', 'clinic', 'dental', 'legal', 'plumber',
  'builder', 'restaurant', 'beauty', 'custom',
])

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

function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 28 28" fill="none" width={size} height={size}>
      <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    </svg>
  )
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
  const router = useRouter()

  const [tenant, setTenant]     = useState<Tenant | null>(null)
  const [usage, setUsage]       = useState<UsageSummary | null>(null)
  const [loading, setLoading]   = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)
  const [userEmail, setUserEmail] = useState('')
  const [userName, setUserName]   = useState('')

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) router.replace('/login')
      else {
        setUserEmail(data.user.email ?? '')
        setUserName(data.user.user_metadata?.full_name ?? '')
      }
    })
  }, [router])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [tenantRes, usageRes] = await Promise.all([
        supabase.from('tenants').select('*').eq('id', tenantId).single(),
        fetch(`${API}/billing/usage/${tenantId}`),
      ])
      if (tenantRes.data) setTenant(tenantRes.data)
      if (usageRes.ok) setUsage(await usageRes.json())
    } catch {}
    finally { setLoading(false) }
  }, [tenantId])

  useEffect(() => { fetchData() }, [fetchData])

  const handleLogout = async () => {
    await supabase.auth.signOut()
    router.replace('/login')
  }

  // ── Icons ──────────────────────────────────────────────────
  const IconDashboard = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <rect x="1.5" y="1.5" width="5" height="5" rx="1.2"/>
      <rect x="8.5" y="1.5" width="5" height="5" rx="1.2"/>
      <rect x="1.5" y="8.5" width="5" height="5" rx="1.2"/>
      <rect x="8.5" y="8.5" width="5" height="5" rx="1.2"/>
    </svg>
  )
  const IconKB = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <path d="M2 11.5V3.5A1 1 0 013 2.5H9.5L12.5 5.5V11.5A1 1 0 0111.5 12.5H3A1 1 0 012 11.5Z"/>
      <path d="M9 2.5V6H12.5"/>
    </svg>
  )
  const IconLeads = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.35" width="14" height="14">
      <path d="M7.5 1.5l1.47 3.29 3.63.52-2.63 2.47.62 3.61L7.5 9.72 4.41 11.4l.62-3.61L2.4 5.31l3.63-.52z" strokeLinejoin="round"/>
    </svg>
  )
  const IconCalls = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <path d="M2 2.5h4l1.5 3.5-2 1.5a9 9 0 003 3l1.5-2 3.5 1.5V13a1 1 0 01-1 1C5.5 14 1 9.5 1 3.5a1 1 0 011-1z" strokeLinejoin="round"/>
    </svg>
  )
  const IconCalendar = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <rect x="1.5" y="2.5" width="12" height="11" rx="1.5"/>
      <path d="M1.5 6.5h12M5 1.5v2M10 1.5v2"/>
    </svg>
  )
  const IconSettings = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <circle cx="7.5" cy="4.8" r="2.3"/>
      <path d="M2 13.5c0-3.04 2.46-5.5 5.5-5.5s5.5 2.46 5.5 5.5" strokeLinecap="round"/>
    </svg>
  )
  const IconSub = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <rect x="1.5" y="3.5" width="12" height="9" rx="1.5"/>
      <path d="M1.5 6.5h12"/>
      <path strokeLinecap="round" d="M5 10h2M8.5 10h1.5"/>
    </svg>
  )
  const IconBilling = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <path d="M1.5 7.5L7.5 2l6 5.5" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M3 7v5.5a.5.5 0 00.5.5H6V9.5h3v3.5h2.5a.5.5 0 00.5-.5V7" strokeLinejoin="round"/>
    </svg>
  )
  const IconUsage = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <rect x="1.5" y="9.5" width="2.5" height="4" rx="0.5"/>
      <rect x="6.25" y="6" width="2.5" height="7.5" rx="0.5"/>
      <rect x="11" y="2.5" width="2.5" height="11" rx="0.5"/>
    </svg>
  )
  const IconSignOut = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <path d="M6 2H3a1 1 0 00-1 1v9a1 1 0 001 1h3"/>
      <path strokeLinecap="round" d="M10 10l3-3-3-3M13 7H6"/>
    </svg>
  )

  const planBadge = () => {
    if (tenant?.subscription_status === 'active' && tenant?.subscription_plan)
      return <span className="db-nav-badge db-badge-green">{tenant.subscription_plan}</span>
    if (!tenant?.subscription_status || tenant.subscription_status === 'none' || tenant.subscription_status === 'incomplete')
      return <span className="db-nav-badge db-badge-amber">Free</span>
    if (tenant.subscription_status === 'past_due')
      return <span className="db-nav-badge db-badge-red">Past due</span>
    return null
  }

  const isSubscribed = tenant?.subscription_status === 'active' || tenant?.subscription_status === 'canceling'

  const Sidebar = ({ mobile = false, onClose }: { mobile?: boolean; onClose?: () => void }) => (
    <>
      <div className="db-sidebar-logo">
        <div className="db-logo-icon"><LogoMark size={22} /></div>
        <span className="db-logo-name">open lines</span>
      </div>
      {tenant && (
        <div className="db-clinic-sw">
          <div className="db-clinic-name">{tenant.business_name}</div>
          <div className="db-clinic-tag">{tenant.industry} · Active</div>
        </div>
      )}
      <div className="db-sidebar-nav">
        <div className="db-nav-label">Main</div>
        <Link href={`/dashboard/${tenantId}`} className="db-nav-item" onClick={onClose}>
          <IconDashboard />
          Dashboard
        </Link>
        <Link href={`/dashboard/${tenantId}/knowledge-base`} className="db-nav-item" onClick={onClose}>
          <IconKB />
          Knowledge Base
        </Link>
        <Link href={`/dashboard/${tenantId}/leads`} className="db-nav-item" onClick={onClose}>
          <IconLeads />
          Leads
        </Link>
        <Link href={`/dashboard/${tenantId}/calls`} className="db-nav-item" onClick={onClose}>
          <IconCalls />
          Calls
        </Link>
        {tenant && BOOKING_INDUSTRIES.has(tenant.industry) && (
          <Link href={`/dashboard/${tenantId}/calendar`} className="db-nav-item" onClick={onClose}>
            <IconCalendar />
            Calendar
          </Link>
        )}
        <div className="db-nav-label">Account</div>
        <Link href={`/dashboard/${tenantId}/settings`} className="db-nav-item" onClick={onClose}>
          <IconSettings />
          Settings
        </Link>
        <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item" onClick={onClose}>
          <IconSub />
          Subscription
          {planBadge()}
        </Link>
        <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item" onClick={onClose}>
          <IconBilling />
          Billing &amp; Payments
        </Link>
        <div className="db-nav-item active">
          <div className="db-nav-indicator" />
          <IconUsage />
          Usage
        </div>
        {mobile && (
          <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 8 }}>
            <button className="db-nav-item" onClick={handleLogout} style={{ color: '#f87171' }}>
              <IconSignOut />
              Sign out
            </button>
          </div>
        )}
      </div>
      {!isSubscribed && (
        <Link href={`/dashboard/${tenantId}/subscription`} className="db-upgrade-pill" onClick={onClose}>
          <div className="db-upgrade-label">↑ Choose a plan</div>
          <div className="db-upgrade-sub">Start from $99/mo</div>
        </Link>
      )}
      {!mobile && (
        <div className="db-sidebar-footer">
          <button className="db-user-row" onClick={handleLogout} title="Sign out">
            <div className="db-user-av">
              {userName
                ? userName.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
                : (userEmail || '?')[0].toUpperCase()}
            </div>
            <div className="db-user-info">
              <div className="db-user-name">{userName || tenant?.business_name || 'Account'}</div>
              <div className="db-user-email">{userEmail}</div>
            </div>
            <IconSignOut />
          </button>
        </div>
      )}
    </>
  )

  const pct = usage?.usage_pct ?? 0
  const barColor = pct >= 100 ? '#ef4444' : pct >= 80 ? '#d97706' : '#3dba72'

  return (
    <div className="db-root">

      {/* ══ Sidebar ══ */}
      <aside className="db-sidebar">
        <Sidebar />
      </aside>

      {/* ══ Main ══ */}
      <div className="db-main">

        {/* Mobile topbar */}
        <div className="db-mobile-topbar">
          <div className="db-mobile-logo">
            <div className="db-logo-icon"><LogoMark size={22} /></div>
            <span className="db-mobile-logo-name">Open Lines</span>
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
      </div>

      {/* ── Mobile overlay menu ── */}
      <AnimatePresence>
        {menuOpen && (
          <motion.div
            className="db-overlay-menu"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={() => setMenuOpen(false)}
          >
            <motion.div
              className="db-overlay-panel"
              initial={{ x: -260 }} animate={{ x: 0 }} exit={{ x: -260 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              onClick={e => e.stopPropagation()}
            >
              <Sidebar mobile onClose={() => setMenuOpen(false)} />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  )
}
