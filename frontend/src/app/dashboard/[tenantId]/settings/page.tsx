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

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  subscription_plan?: string
  subscription_status?: string
}

function SettingsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const router = useRouter()

  const [tenant, setTenant]               = useState<Tenant | null>(null)
  const [leads, setLeads]                 = useState<{ id: string }[]>([])
  const [appointments, setAppointments]   = useState<{ id: string }[]>([])
  const [userEmail, setUserEmail]         = useState('')
  const [userName, setUserName]           = useState('')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const [whatsapp, setWhatsapp]           = useState('')
  const [whatsappState, setWhatsappState] = useState<SaveState>('idle')
  const [email, setEmail]                 = useState('')
  const [emailState, setEmailState]       = useState<SaveState>('idle')
  const [emailMsg, setEmailMsg]           = useState('')
  const [currentPw, setCurrentPw]         = useState('')
  const [newPw, setNewPw]                 = useState('')
  const [confirmPw, setConfirmPw]         = useState('')
  const [pwState, setPwState]             = useState<SaveState>('idle')
  const [pwMsg, setPwMsg]                 = useState('')

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) { router.replace('/login'); return }
      setEmail(data.user.email ?? '')
      setUserEmail(data.user.email ?? '')
      setUserName(data.user.user_metadata?.full_name ?? '')
    })
    Promise.all([
      fetch(`${API}/onboarding/status/${tenantId}`),
      fetch(`${API}/leads/${tenantId}`),
      fetch(`${API}/calendar/appointments/${tenantId}`),
    ]).then(async ([tRes, lRes, aRes]) => {
      if (tRes.ok) {
        const d = await tRes.json()
        setTenant(d)
        if (d?.whatsapp_number) setWhatsapp(d.whatsapp_number)
      }
      if (lRes.ok) setLeads(await lRes.json())
      if (aRes.ok) { const d = await aRes.json(); setAppointments(Array.isArray(d) ? d : []) }
    })
  }, [tenantId, router])

  const isSubscribed = tenant?.subscription_status === 'active' || tenant?.subscription_status === 'canceling'

  const planBadge = () => {
    if (tenant?.subscription_status === 'active' && tenant?.subscription_plan)
      return <span className="db-nav-badge db-badge-green">{tenant.subscription_plan}</span>
    if (!tenant?.subscription_status || tenant.subscription_status === 'none' || tenant.subscription_status === 'incomplete')
      return <span className="db-nav-badge db-badge-amber">Free</span>
    if (tenant.subscription_status === 'past_due')
      return <span className="db-nav-badge db-badge-red">Past due</span>
    return null
  }

  const handleLogout = async () => {
    await supabase.auth.signOut()
    router.replace('/login')
  }

  const saveWhatsapp = async () => {
    setWhatsappState('saving')
    try {
      const res = await fetch(`${API}/onboarding/settings/${tenantId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ whatsapp_number: whatsapp.trim() }),
      })
      setWhatsappState(res.ok ? 'saved' : 'error')
      setTimeout(() => setWhatsappState('idle'), 3000)
    } catch {
      setWhatsappState('error')
      setTimeout(() => setWhatsappState('idle'), 3000)
    }
  }

  const saveEmail = async () => {
    setEmailState('saving')
    setEmailMsg('')
    const { error } = await supabase.auth.updateUser({ email: email.trim() })
    if (error) {
      setEmailState('error')
      setEmailMsg(error.message)
    } else {
      setEmailState('saved')
      setEmailMsg('Verification link sent — check your new inbox to confirm.')
    }
    setTimeout(() => { setEmailState('idle'); setEmailMsg('') }, 6000)
  }

  const savePassword = async () => {
    if (!currentPw) { setPwState('error'); setPwMsg('Enter your current password.'); setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000); return }
    if (newPw.length < 8) { setPwState('error'); setPwMsg('New password must be at least 8 characters.'); setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000); return }
    if (newPw !== confirmPw) { setPwState('error'); setPwMsg("New passwords don't match."); setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000); return }
    setPwState('saving'); setPwMsg('')
    const { data: userData } = await supabase.auth.getUser()
    const { error: signInError } = await supabase.auth.signInWithPassword({ email: userData.user?.email ?? '', password: currentPw })
    if (signInError) { setPwState('error'); setPwMsg('Current password is incorrect.'); setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000); return }
    const { error } = await supabase.auth.updateUser({ password: newPw })
    if (error) { setPwState('error'); setPwMsg(error.message) }
    else { setPwState('saved'); setPwMsg('Password updated.'); setCurrentPw(''); setNewPw(''); setConfirmPw('') }
    setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000)
  }

  // ── Icons ──────────────────────────────────────────────────────────────────
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
      <rect x="1.5" y="1.5" width="5" height="5" rx="1.2"/><rect x="8.5" y="1.5" width="5" height="5" rx="1.2"/>
      <rect x="1.5" y="8.5" width="5" height="5" rx="1.2"/><rect x="8.5" y="8.5" width="5" height="5" rx="1.2"/>
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
        <Link href={`/dashboard/${tenantId}/calls`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <IconCalls />
          Calls
        </Link>
        {tenant && BOOKING_INDUSTRIES.has(tenant.industry) && (
          <Link href={`/dashboard/${tenantId}/calendar`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
            <IconCalendar />
            Calendar
            {appointments.length > 0 && <span className="db-nav-badge db-badge-green">{appointments.length}</span>}
          </Link>
        )}
        <div className="db-nav-label">Account</div>
        <Link href={`/dashboard/${tenantId}/settings`} className="db-nav-item active" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <div className="db-nav-indicator" />
          <IconSettings />
          Settings
        </Link>
        <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <IconBilling />
          Billing &amp; Payments
          {planBadge()}
        </Link>
        <Link href={`/dashboard/${tenantId}/usage`} className="db-nav-item" onClick={mobile ? () => setMobileMenuOpen(false) : undefined}>
          <IconUsage />
          Usage
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

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '9px 12px', fontSize: 13,
    border: '1px solid #e8e6e0', borderRadius: 7,
    background: '#fff', color: '#16161a',
    outline: 'none', boxSizing: 'border-box',
    fontFamily: 'var(--font-dm), sans-serif',
  }
  const btnStyle = (disabled = false): React.CSSProperties => ({
    fontSize: 12, fontWeight: 600, padding: '7px 18px',
    borderRadius: 7, border: '1px solid #3dba72',
    background: '#eafaf2', color: '#1a7a45',
    cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    transition: 'opacity 0.15s',
    fontFamily: 'var(--font-dm), sans-serif',
  })

  return (
    <div className="db-root">

      {/* ── Sidebar ── */}
      <aside className="db-sidebar">
        <Sidebar />
      </aside>

      {/* ── Main ── */}
      <div className="db-main">

        {/* Mobile topbar */}
        <div className="db-mobile-topbar">
          <div className="db-mobile-logo">
            <div className="db-logo-icon"><LogoMark size={22} /></div>
            <span className="db-mobile-logo-name">Settings</span>
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
          <span className="db-topbar-title">Settings</span>
          {tenant?.twilio_phone_number && (
            <div style={{ fontSize: 12, color: '#888' }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#3dba72', marginRight: 5 }} />
              {tenant.twilio_phone_number}
            </div>
          )}
        </div>

        {/* Content */}
        <div className="db-content">
          <div style={{ maxWidth: 520 }}>

            {/* ── Notifications ── */}
            <div className="db-section-title" style={{ marginBottom: 14 }}>Notifications</div>
            <div style={{ border: '1px solid #e8e6e0', borderRadius: 10, background: '#fff', overflow: 'hidden', marginBottom: 24 }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid #f0ede8' }}>
                <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 4 }}>
                  WhatsApp number
                </label>
                <div style={{ fontSize: 12, color: '#aaa', marginBottom: 12, lineHeight: 1.5 }}>
                  After every call, a summary is sent here. Include country code (e.g. +1 416 555 0123).
                </div>
                <input type="tel" value={whatsapp} onChange={e => setWhatsapp(e.target.value)}
                  placeholder="+1 416 555 0123" style={inputStyle} />
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button onClick={saveWhatsapp} disabled={whatsappState === 'saving'} style={btnStyle(whatsappState === 'saving')}>
                  {whatsappState === 'saving' ? 'Saving…' : 'Save'}
                </button>
                {whatsappState === 'saved' && <span style={{ fontSize: 12, color: '#34C759' }}>✓ Saved</span>}
                {whatsappState === 'error' && <span style={{ fontSize: 12, color: '#FF3B30' }}>Save failed — try again</span>}
              </div>
            </div>

            {/* ── Email address ── */}
            <div className="db-section-title" style={{ marginBottom: 14 }}>Email address</div>
            <div style={{ border: '1px solid #e8e6e0', borderRadius: 10, background: '#fff', overflow: 'hidden', marginBottom: 24 }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid #f0ede8' }}>
                <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 12 }}>
                  New email
                </label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                  placeholder="you@example.com" style={inputStyle} />
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button onClick={saveEmail} disabled={emailState === 'saving'} style={btnStyle(emailState === 'saving')}>
                  {emailState === 'saving' ? 'Sending…' : 'Update email'}
                </button>
                {emailMsg && (
                  <span style={{ fontSize: 12, color: emailState === 'error' ? '#FF3B30' : '#34C759', lineHeight: 1.4, maxWidth: 280 }}>
                    {emailMsg}
                  </span>
                )}
              </div>
            </div>

            {/* ── Password ── */}
            <div className="db-section-title" style={{ marginBottom: 14 }}>Password</div>
            <div style={{ border: '1px solid #e8e6e0', borderRadius: 10, background: '#fff', overflow: 'hidden', marginBottom: 24 }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid #f0ede8', display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 6 }}>Current password</label>
                  <input type="password" value={currentPw} onChange={e => setCurrentPw(e.target.value)}
                    placeholder="Your current password" style={inputStyle} />
                </div>
                <div style={{ height: 1, background: '#f0ede8' }} />
                <div>
                  <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 6 }}>New password</label>
                  <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)}
                    placeholder="Min. 8 characters" style={inputStyle} />
                </div>
                <div>
                  <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 6 }}>Confirm new password</label>
                  <input type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)}
                    placeholder="Repeat new password" style={inputStyle} />
                </div>
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button onClick={savePassword} disabled={pwState === 'saving' || !currentPw || !newPw}
                  style={btnStyle(pwState === 'saving' || !currentPw || !newPw)}>
                  {pwState === 'saving' ? 'Updating…' : 'Update password'}
                </button>
                {pwMsg && <span style={{ fontSize: 12, color: pwState === 'error' ? '#FF3B30' : '#34C759' }}>{pwMsg}</span>}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}

export default function SettingsPageWrapper() {
  return <SettingsPage />
}
