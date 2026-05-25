'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'
import { supabase } from '@/lib/supabase'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const BOOKING_INDUSTRIES = new Set([
  'realtor', 'clinic', 'dental', 'legal', 'plumber',
  'builder', 'restaurant', 'beauty', 'custom',
])

interface Appointment {
  id: string
  caller_name?: string
  caller_phone?: string
  service?: string
  appointment_datetime: string
  duration_minutes?: number
  status?: string
}

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  subscription_plan?: string
  subscription_status?: string
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
}

function isUpcoming(iso: string): boolean {
  return new Date(iso) > new Date()
}

function CalendarPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const router = useRouter()

  const [tenant, setTenant]               = useState<Tenant | null>(null)
  const [leads, setLeads]                 = useState<{ id: string }[]>([])
  const [appointments, setAppointments]   = useState<Appointment[]>([])
  const [userEmail, setUserEmail]         = useState('')
  const [userName, setUserName]           = useState('')
  const [loading, setLoading]             = useState(true)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [toast, setToast]                 = useState<string | null>(null)
  const [showPast, setShowPast]           = useState(false)

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) router.replace('/login')
      else {
        setUserEmail(data.user.email ?? '')
        setUserName(data.user.user_metadata?.full_name ?? '')
      }
    })
  }, [router])

  useEffect(() => {
    const init = async () => {
      try {
        const [tRes, lRes, aRes] = await Promise.all([
          fetch(`${API}/onboarding/status/${tenantId}`),
          fetch(`${API}/leads/${tenantId}`),
          fetch(`${API}/calendar/appointments/${tenantId}`),
        ])
        if (tRes.ok) setTenant(await tRes.json())
        if (lRes.ok) setLeads(await lRes.json())
        if (aRes.ok) {
          const data = await aRes.json()
          setAppointments(Array.isArray(data) ? data : [])
        }
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

  const isSubscribed = tenant?.subscription_status === 'active' || tenant?.subscription_status === 'canceling'

  const upcoming = appointments.filter(a => a.status !== 'cancelled' && isUpcoming(a.appointment_datetime))
  const past     = appointments.filter(a => a.status === 'cancelled' || !isUpcoming(a.appointment_datetime))

  const displayed = showPast ? past : upcoming

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
        <Link href={`/dashboard/${tenantId}/leads`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <IconLeads />
          Leads
          {leads.length > 0 && <span className="db-nav-badge db-badge-red">{leads.length}</span>}
        </Link>
        {tenant && BOOKING_INDUSTRIES.has(tenant.industry) && (
          <Link href={`/dashboard/${tenantId}/calendar`} className="db-nav-item active" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
            <div className="db-nav-indicator" />
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
            <span className="db-mobile-logo-name">Calendar</span>
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
          <span className="db-topbar-title">Calendar</span>
          {tenant?.twilio_phone_number && (
            <div style={{ fontSize: 12, color: '#888' }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#3dba72', marginRight: 5 }} />
              {tenant.twilio_phone_number}
            </div>
          )}
        </div>

        {/* Content */}
        <div className="db-content">

          {/* Toggle upcoming / past */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
            <button
              onClick={() => setShowPast(false)}
              style={{
                padding: '5px 14px', borderRadius: 6, fontSize: 12, fontWeight: 500,
                border: '1px solid',
                borderColor: !showPast ? '#3dba72' : '#e8e6e0',
                background: !showPast ? '#eafaf2' : '#fff',
                color: !showPast ? '#1a7a45' : '#666',
                cursor: 'pointer',
                fontFamily: 'var(--font-dm), sans-serif',
              }}
            >
              Upcoming ({upcoming.length})
            </button>
            <button
              onClick={() => setShowPast(true)}
              style={{
                padding: '5px 14px', borderRadius: 6, fontSize: 12, fontWeight: 500,
                border: '1px solid',
                borderColor: showPast ? '#3dba72' : '#e8e6e0',
                background: showPast ? '#eafaf2' : '#fff',
                color: showPast ? '#1a7a45' : '#666',
                cursor: 'pointer',
                fontFamily: 'var(--font-dm), sans-serif',
              }}
            >
              Past &amp; Cancelled ({past.length})
            </button>
          </div>

          {/* Appointment list */}
          {displayed.length === 0 ? (
            <div style={{
              background: '#fff', border: '1px solid #e8e6e0', borderRadius: 10,
              padding: '40px 20px', textAlign: 'center', color: '#aaa', fontSize: 13,
            }}>
              {showPast
                ? 'No past appointments.'
                : 'No upcoming appointments — they appear here when callers book via the AI.'}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {displayed
                .slice()
                .sort((a, b) => new Date(a.appointment_datetime).getTime() - new Date(b.appointment_datetime).getTime())
                .map(appt => {
                  const upcoming = isUpcoming(appt.appointment_datetime)
                  const cancelled = appt.status === 'cancelled'
                  return (
                    <div
                      key={appt.id}
                      style={{
                        background: '#fff', border: '1px solid',
                        borderColor: cancelled ? '#fee2e2' : upcoming ? '#d1fae5' : '#e8e6e0',
                        borderRadius: 10, padding: '14px 16px',
                        display: 'flex', alignItems: 'flex-start', gap: 16,
                        opacity: cancelled ? 0.7 : 1,
                      }}
                    >
                      {/* Date block */}
                      <div style={{
                        flexShrink: 0, textAlign: 'center', width: 48,
                        background: cancelled ? '#fef2f2' : upcoming ? '#eafaf2' : '#f4f3f0',
                        borderRadius: 8, padding: '8px 4px',
                      }}>
                        <div style={{ fontSize: 18, fontWeight: 700, color: '#16161a', lineHeight: 1 }}>
                          {new Date(appt.appointment_datetime).getDate()}
                        </div>
                        <div style={{ fontSize: 10, color: '#888', textTransform: 'uppercase', letterSpacing: '0.05em', marginTop: 2 }}>
                          {new Date(appt.appointment_datetime).toLocaleDateString('en-US', { month: 'short' })}
                        </div>
                      </div>

                      {/* Info */}
                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                          <span style={{ fontSize: 14, fontWeight: 600, color: '#16161a' }}>
                            {appt.caller_name || 'Unknown caller'}
                          </span>
                          {appt.service && (
                            <span style={{ fontSize: 11, color: '#666', background: '#f4f3f0', padding: '2px 7px', borderRadius: 4 }}>
                              {appt.service}
                            </span>
                          )}
                          <span style={{
                            fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 4,
                            textTransform: 'uppercase', letterSpacing: '0.04em', marginLeft: 'auto',
                            background: cancelled ? '#fee2e2' : upcoming ? '#d1fae5' : '#f4f3f0',
                            color: cancelled ? '#dc2626' : upcoming ? '#16a34a' : '#666',
                          }}>
                            {cancelled ? 'Cancelled' : upcoming ? 'Confirmed' : 'Completed'}
                          </span>
                        </div>
                        <div style={{ marginTop: 4, fontSize: 12, color: '#555' }}>
                          {fmtDate(appt.appointment_datetime)} · {fmtTime(appt.appointment_datetime)}
                          {appt.duration_minutes && ` · ${appt.duration_minutes} min`}
                        </div>
                        {appt.caller_phone && (
                          <div style={{ marginTop: 2, fontSize: 11, color: '#aaa' }}>{appt.caller_phone}</div>
                        )}
                      </div>
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

export default function CalendarPageWrapper() {
  return <CalendarPage />
}
