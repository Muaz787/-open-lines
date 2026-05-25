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

interface Lead {
  id: string
  name?: string
  phone?: string
  summary?: string
  urgency?: string
  status?: string
  created_at: string
  metadata?: {
    key_details?: Record<string, string>
    suggested_next_step?: string
  }
}

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  subscription_plan?: string
  subscription_status?: string
}

type StatusFilter = 'all' | 'new' | 'contacted' | 'converted'

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return 'just now'
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function urgencyColor(u?: string) {
  if (u === 'high') return '#ef4444'
  if (u === 'medium') return '#f59e0b'
  return '#6b7280'
}

function LeadsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const router = useRouter()

  const [tenant, setTenant]               = useState<Tenant | null>(null)
  const [leads, setLeads]                 = useState<Lead[]>([])
  const [appointments, setAppointments]   = useState<{ id: string }[]>([])
  const [userEmail, setUserEmail]         = useState('')
  const [userName, setUserName]           = useState('')
  const [loading, setLoading]             = useState(true)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [toast, setToast]                 = useState<string | null>(null)
  const [filter, setFilter]               = useState<StatusFilter>('all')
  const [expanded, setExpanded]           = useState<string | null>(null)
  const [updating, setUpdating]           = useState<string | null>(null)

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) router.replace('/login')
      else {
        setUserEmail(data.user.email ?? '')
        setUserName(data.user.user_metadata?.full_name ?? '')
      }
    })
  }, [router])

  const loadLeads = useCallback(async () => {
    const res = await fetch(`${API}/leads/${tenantId}?limit=200`)
    if (res.ok) setLeads(await res.json())
  }, [tenantId])

  useEffect(() => {
    const init = async () => {
      try {
        const [tRes, lRes] = await Promise.all([
          fetch(`${API}/onboarding/status/${tenantId}`),
          fetch(`${API}/leads/${tenantId}?limit=200`),
        ])
        if (tRes.ok) setTenant(await tRes.json())
        if (lRes.ok) setLeads(await lRes.json())
        fetch(`${API}/calendar/appointments/${tenantId}`)
          .then(r => r.ok ? r.json() : [])
          .then(d => setAppointments(Array.isArray(d) ? d : []))
          .catch(() => {})
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [tenantId])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  const handleLogout = async () => {
    await supabase.auth.signOut()
    router.replace('/login')
  }

  const updateStatus = async (leadId: string, status: string) => {
    setUpdating(leadId)
    try {
      const res = await fetch(`${API}/leads/${tenantId}/${leadId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      if (res.ok) {
        setLeads(prev => prev.map(l => l.id === leadId ? { ...l, status } : l))
        showToast('Status updated')
      }
    } catch {
      showToast('Update failed')
    } finally {
      setUpdating(null)
    }
  }

  const isSubscribed = tenant?.subscription_status === 'active' || tenant?.subscription_status === 'canceling'

  const filtered = leads.filter(l => {
    if (filter === 'all') return true
    return (l.status ?? 'new') === filter
  })

  // ── Icons ────────────────────────────────────────────────
  const LogoMark = ({ size = 22 }: { size?: number }) => (
    <svg viewBox="0 0 28 28" fill="none" width={size} height={size}>
      <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    </svg>
  )
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
  const IconBilling = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <path d="M1.5 7.5L7.5 2l6 5.5" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M3 7v5.5a.5.5 0 00.5.5H6V9.5h3v3.5h2.5a.5.5 0 00.5-.5V7" strokeLinejoin="round"/>
    </svg>
  )
  const IconSub = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <rect x="1.5" y="3.5" width="12" height="9" rx="1.5"/>
      <path d="M1.5 6.5h12"/>
      <path strokeLinecap="round" d="M5 10h2M8.5 10h1.5"/>
    </svg>
  )
  const IconSignOut = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <path d="M6 2H3a1 1 0 00-1 1v9a1 1 0 001 1h3"/>
      <path strokeLinecap="round" d="M10 10l3-3-3-3M13 7H6"/>
    </svg>
  )
  const IconChevron = ({ open }: { open: boolean }) => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="12" height="12"
      style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
      <path d="M3 5.5l4.5 4 4.5-4" strokeLinecap="round" strokeLinejoin="round"/>
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

  const Sidebar = ({ mobile = false }: { mobile?: boolean }) => (
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
        <Link href={`/dashboard/${tenantId}`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <IconDashboard />
          Dashboard
        </Link>
        <Link href={`/dashboard/${tenantId}/knowledge-base`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <IconKB />
          Knowledge Base
        </Link>
        <Link href={`/dashboard/${tenantId}/leads`} className="db-nav-item active" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <div className="db-nav-indicator" />
          <IconLeads />
          Leads
          {leads.length > 0 && <span className="db-nav-badge db-badge-red">{leads.length}</span>}
        </Link>
        {tenant && BOOKING_INDUSTRIES.has(tenant.industry) && (
          <Link href={`/dashboard/${tenantId}/calendar`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
            <IconCalendar />
            Calendar
            {appointments.length > 0 && <span className="db-nav-badge db-badge-green">{appointments.length}</span>}
          </Link>
        )}
        <div className="db-nav-label">Account</div>
        <Link href={`/dashboard/${tenantId}/settings`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <IconSettings />
          Settings
        </Link>
        <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <IconSub />
          Subscription
          {planBadge()}
        </Link>
        <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <IconBilling />
          Billing &amp; Payments
        </Link>
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
        <Link href={`/dashboard/${tenantId}/subscription`} className="db-upgrade-pill" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
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
      {mobile && (
        <div className="db-sidebar-footer">
          <div className="db-user-row" style={{ cursor: 'default' }}>
            <div className="db-user-av">
              {userName
                ? userName.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
                : (userEmail || '?')[0].toUpperCase()}
            </div>
            <div className="db-user-info">
              <div className="db-user-name">{userName || tenant?.business_name || 'Account'}</div>
              <div className="db-user-email">{userEmail}</div>
            </div>
          </div>
        </div>
      )}
    </>
  )

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f4f3f0' }}>
        <div style={{ fontSize: 13, color: '#888' }}>Loading…</div>
      </div>
    )
  }

  const statusCounts = {
    all: leads.length,
    new: leads.filter(l => !l.status || l.status === 'new').length,
    contacted: leads.filter(l => l.status === 'contacted').length,
    converted: leads.filter(l => l.status === 'converted').length,
  }

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
            <span className="db-mobile-logo-name">Leads</span>
          </div>
          <button className="db-hamburger" onClick={() => setMobileMenuOpen(o => !o)} aria-label="Menu">
            {mobileMenuOpen ? (
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

        {/* Toast */}
        <AnimatePresence>
          {toast && (
            <motion.div
              initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
              style={{
                position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)',
                background: '#16161a', color: '#fff', padding: '10px 20px',
                borderRadius: 8, fontSize: 13, fontWeight: 500, zIndex: 300,
                boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
              }}
            >
              {toast}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Mobile menu overlay */}
        <AnimatePresence>
          {mobileMenuOpen && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="db-mobile-overlay" onClick={() => setMobileMenuOpen(false)}
            >
              <motion.div
                initial={{ x: -260 }} animate={{ x: 0 }} exit={{ x: -260 }}
                transition={{ type: 'tween', duration: 0.22 }}
                className="db-mobile-sidebar" onClick={e => e.stopPropagation()}
              >
                <Sidebar mobile />
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Desktop topbar */}
        <div className="db-topbar">
          <span className="db-topbar-title">Leads</span>
        </div>

        {/* Content */}
        <div className="db-content">

          {/* Filter tabs */}
          <div className="leads-filter-bar">
            {(['all', 'new', 'contacted', 'converted'] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  padding: '5px 12px', borderRadius: 6, fontSize: 12, fontWeight: 500,
                  border: '1px solid',
                  borderColor: filter === f ? '#3dba72' : '#e8e6e0',
                  background: filter === f ? '#eafaf2' : '#fff',
                  color: filter === f ? '#1a7a45' : '#666',
                  cursor: 'pointer',
                  fontFamily: 'var(--font-dm), sans-serif',
                }}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
                <span style={{ marginLeft: 5, opacity: 0.7 }}>{statusCounts[f]}</span>
              </button>
            ))}
            <button
              onClick={loadLeads}
              style={{
                marginLeft: 'auto', padding: '5px 12px', borderRadius: 6, fontSize: 12,
                border: '1px solid #e8e6e0', background: '#fff', color: '#666',
                cursor: 'pointer', fontFamily: 'var(--font-dm), sans-serif',
              }}
            >
              Refresh
            </button>
          </div>

          {/* Lead list */}
          {filtered.length === 0 ? (
            <div style={{
              background: '#fff', border: '1px solid #e8e6e0', borderRadius: 10,
              padding: '40px 20px', textAlign: 'center', color: '#aaa', fontSize: 13,
            }}>
              {filter === 'all' ? 'No leads yet — they appear here after calls.' : `No ${filter} leads.`}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {filtered.map(lead => {
                const isOpen = expanded === lead.id
                const status = lead.status ?? 'new'
                return (
                  <div
                    key={lead.id}
                    style={{
                      background: '#fff', border: '1px solid #e8e6e0',
                      borderRadius: 10, overflow: 'hidden',
                    }}
                  >
                    {/* Row */}
                    <div
                      style={{
                        display: 'flex', alignItems: 'center', gap: 12,
                        padding: '12px 14px', cursor: 'pointer',
                      }}
                      onClick={() => setExpanded(isOpen ? null : lead.id)}
                    >
                      {/* Urgency dot */}
                      <div style={{
                        width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                        background: urgencyColor(lead.urgency),
                      }} />

                      {/* Name / phone */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#16161a' }}>
                          {lead.name || 'Unknown'}
                        </div>
                        {lead.phone && (
                          <div style={{ fontSize: 11, color: '#888', marginTop: 1 }}>{lead.phone}</div>
                        )}
                      </div>

                      {/* Summary — hidden on small screens */}
                      {lead.summary && (
                        <div className="leads-row-summary">
                          {lead.summary}
                        </div>
                      )}

                      {/* Status badge */}
                      <span style={{
                        fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 4,
                        textTransform: 'uppercase', letterSpacing: '0.04em',
                        background: status === 'converted' ? '#eafaf2' : status === 'contacted' ? '#eff6ff' : '#fef3c7',
                        color: status === 'converted' ? '#1a7a45' : status === 'contacted' ? '#1d4ed8' : '#92400e',
                      }}>
                        {status}
                      </span>

                      {/* Time */}
                      <div style={{ fontSize: 11, color: '#aaa', whiteSpace: 'nowrap', flexShrink: 0 }}>
                        {timeAgo(lead.created_at)}
                      </div>

                      <IconChevron open={isOpen} />
                    </div>

                    {/* Expanded details */}
                    <AnimatePresence>
                      {isOpen && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          style={{ overflow: 'hidden' }}
                        >
                          <div style={{
                            borderTop: '1px solid #f0ede8', padding: '12px 14px',
                            display: 'flex', flexDirection: 'column', gap: 10,
                          }}>
                            {/* Key details */}
                            {lead.metadata?.key_details && Object.keys(lead.metadata.key_details).length > 0 && (
                              <div>
                                <div style={{ fontSize: 11, fontWeight: 600, color: '#888', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Details</div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                                  {Object.entries(lead.metadata.key_details).map(([k, v]) => (
                                    <div key={k} style={{
                                      fontSize: 12, padding: '3px 8px', borderRadius: 5,
                                      background: '#f4f3f0', color: '#444',
                                    }}>
                                      <span style={{ fontWeight: 600 }}>{k}:</span> {v}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Suggested next step */}
                            {lead.metadata?.suggested_next_step && (
                              <div style={{ fontSize: 12, color: '#555' }}>
                                <span style={{ fontWeight: 600 }}>Next step:</span> {lead.metadata.suggested_next_step}
                              </div>
                            )}

                            {/* Status update */}
                            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 2 }}>
                              <span style={{ fontSize: 11, color: '#888' }}>Mark as:</span>
                              {(['new', 'contacted', 'converted'] as const).map(s => (
                                <button
                                  key={s}
                                  disabled={status === s || updating === lead.id}
                                  onClick={() => updateStatus(lead.id, s)}
                                  style={{
                                    padding: '4px 10px', borderRadius: 5, fontSize: 11, fontWeight: 500,
                                    border: '1px solid',
                                    borderColor: status === s ? '#3dba72' : '#e8e6e0',
                                    background: status === s ? '#eafaf2' : '#fff',
                                    color: status === s ? '#1a7a45' : '#555',
                                    cursor: status === s ? 'default' : 'pointer',
                                    opacity: updating === lead.id ? 0.6 : 1,
                                    fontFamily: 'var(--font-dm), sans-serif',
                                  }}
                                >
                                  {s.charAt(0).toUpperCase() + s.slice(1)}
                                </button>
                              ))}
                            </div>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function LeadsPageWrapper() {
  return <LeadsPage />
}
