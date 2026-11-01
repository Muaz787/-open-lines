'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter, usePathname } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { supabase } from '@/lib/supabase'
import Sidebar, { LogoMark, type SidebarTenant } from './Sidebar'
import { TrialBanner, type TrialInfo } from './TrialBanner'
import { trackEvent, identifyUser, resetAnalytics } from '@/lib/analytics'
import { AccountProvider } from './lib/AccountContext'
import type { ProviderState } from './lib/accountState'
import { resolvePendingTrialConversion } from '@/lib/adsConversion'

import { authedFetch, clearResponseCache } from '@/lib/api'
import { classifyAuth } from '@/lib/authCheck'
import { ErrorState, LoadingState } from './components/PageStates'

const AUTH_SLOW_MS = 1500
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

function mobileTitle(pathname: string, base: string): string {
  const rest = pathname.slice(base.length).replace(/^\//, '')
  const seg = rest.split('/')[0]
  const map: Record<string, string> = {
    '':               'Dashboard',
    'knowledge-base': 'Knowledge Base',
    'leads':          'Leads',
    'calls':          'Calls',
    'calendar':       'Calendar',
    'settings':       'Settings',
    'subscription':   'Billing',
    'usage':          'Usage',
  }
  return map[seg] ?? 'Dashboard'
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { tenantId } = useParams<{ tenantId: string }>()
  const router = useRouter()
  const pathname = usePathname()
  const base = `/dashboard/${tenantId}`

  const [tenant, setTenant]       = useState<SidebarTenant | null>(null)
  const [trial, setTrial]         = useState<TrialInfo | null>(null)
  const [provider, setProvider]   = useState<ProviderState | undefined>(undefined)
  const [tenantFailed, setTenantFailed] = useState(false)
  const [leadsCount, setLeads]    = useState(0)
  const [apptsCount, setAppts]    = useState(0)
  const [userName, setUserName]   = useState('')
  const [userEmail, setUserEmail] = useState('')
  const [mobileOpen, setMobileOpen] = useState(false)
  // null = the session check hasn't resolved yet. Rendering children before it
  // does painted the whole dashboard — including "Choose a plan" with real
  // pricing — to a signed-out visitor for a moment before the redirect fired.
  const [signedIn, setSignedIn] = useState<boolean | null>(null)
  const [authUnavailable, setAuthUnavailable] = useState(false)
  // Reading the session is instant unless a token needs refreshing while auth is
  // struggling, when Supabase retries for up to 30 seconds or so.
  const [authSlow, setAuthSlow] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setAuthSlow(true), AUTH_SLOW_MS)
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    // getSession reads the stored session: no network round-trip, so the page
    // under this layout starts fetching at once. It is enough for this gate,
    // which only decides what to paint — the backend verifies the token on
    // every request, and a rejected one sends the browser to /login.
    supabase.auth.getSession().then(({ data, error }) => {
      const user = data.session?.user
      const check = classifyAuth(!!user, error)
      if (check === 'unavailable') { setAuthUnavailable(true); return }
      if (!user) { setSignedIn(false); router.replace('/login'); return }
      setSignedIn(true)
      setUserEmail(user.email ?? '')
      setUserName(user.user_metadata?.full_name ?? '')
      // Idempotent re-identify keeps returning sessions tied to the person
      identifyUser(user.id, {
        email: user.email,
        tenant_id: user.app_metadata?.tenant_id ?? user.user_metadata?.tenant_id,
      })
    }).catch(() => setAuthUnavailable(true))
  }, [router])

  useEffect(() => {
    trackEvent('dashboard_viewed', { tenant_id: tenantId })
  }, [tenantId])

  useEffect(() => {
    Promise.all([
      authedFetch(`${API}/onboarding/status/${tenantId}`),
      authedFetch(`${API}/leads/${tenantId}`),
      authedFetch(`${API}/calendar/appointments/${tenantId}`),
    ]).then(async ([tRes, lRes, aRes]) => {
      if (tRes.ok) {
        const t = await tRes.json()
        setTenant(t)
        setTrial(t.trial ?? null)
        // Only a tenant claiming a live subscription needs Stripe's word on it.
        if (t.account?.has_provider_subscription && t.account.subscription !== 'canceled') {
          authedFetch(`${API}/billing/subscription-details/${tenantId}`)
            .then(r => (r.ok ? r.json() : null))
            .then(d => setProvider(d?.provider_state ?? 'unavailable'))
            .catch(() => setProvider('unavailable'))
        }
        resolvePendingTrialConversion(tenantId, t.trial?.card_trial === true)
      }
      else setTenantFailed(true)
      if (lRes.ok) { const d = await lRes.json(); setLeads(Array.isArray(d) ? d.length : 0) }
      if (aRes.ok) { const d = await aRes.json(); setAppts(Array.isArray(d) ? d.length : 0) }
    }).catch(() => setTenantFailed(true))
  }, [tenantId])

  // Close the mobile menu whenever the route changes
  useEffect(() => { setMobileOpen(false) }, [pathname])

  const handleLogout = async () => {
    await supabase.auth.signOut()
    // Cached tab data belongs to this user; the next one on this device starts empty
    clearResponseCache()
    // Reset so the next user on this device gets a fresh analytics identity
    resetAnalytics()
    router.replace('/login')
  }

  const sidebarProps = {
    tenantId, tenant, leadsCount, apptsCount, userName, userEmail, onLogout: handleLogout,
  }

  // Hold everything until we know. A brief blank beats flashing an authenticated
  // page at someone who is not.
  if (authUnavailable) {
    return (
      <div className="db-root">
        <ErrorState title="We couldn’t confirm your sign-in." onRetry={() => window.location.reload()} />
        <div style={{ textAlign: 'center', fontSize: 13 }}><a href="/login">Sign in again</a></div>
      </div>
    )
  }
  if (signedIn !== true) {
    return (
      <div className="db-root" aria-busy="true">
        {authSlow && signedIn === null && (
          <div role="status">
            <LoadingState label="Reconnecting… This can take up to a minute. You don’t need to do anything." />
          </div>
        )}
      </div>
    )
  }

  return (
    <AccountProvider value={{ account: tenant?.account, status: tenant ? 'ready' : tenantFailed ? 'error' : 'loading', provider }}>
    <div className="db-root">
      {/* Persistent desktop sidebar */}
      <aside className="db-sidebar">
        <Sidebar {...sidebarProps} />
      </aside>

      <div className="db-main">
        {/* Mobile topbar */}
        <div className="db-mobile-topbar">
          <div className="db-mobile-logo">
            <div className="db-logo-icon"><LogoMark size={22} /></div>
            <span className="db-mobile-logo-name">{mobileTitle(pathname, base)}</span>
          </div>
          <button className="db-hamburger" onClick={() => setMobileOpen(o => !o)} aria-label="Menu">
            {mobileOpen ? (
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

        {/* Mobile overlay sidebar */}
        <AnimatePresence>
          {mobileOpen && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="db-mobile-overlay" onClick={() => setMobileOpen(false)}
            >
              <motion.div
                initial={{ x: -260 }} animate={{ x: 0 }} exit={{ x: -260 }}
                transition={{ type: 'tween', duration: 0.22 }}
                className="db-mobile-sidebar" onClick={e => e.stopPropagation()}
              >
                <Sidebar {...sidebarProps} mobile onNavigate={() => setMobileOpen(false)} />
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        <TrialBanner trial={trial} tenantId={tenantId} />

        {children}
      </div>
    </div>
    </AccountProvider>
  )
}
