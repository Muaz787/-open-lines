'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter, usePathname } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { supabase } from '@/lib/supabase'
import Sidebar, { LogoMark, type SidebarTenant } from './Sidebar'
import { trackEvent, identifyUser, resetAnalytics } from '@/lib/analytics'

import { authedFetch } from '@/lib/api'
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
  const [leadsCount, setLeads]    = useState(0)
  const [apptsCount, setAppts]    = useState(0)
  const [userName, setUserName]   = useState('')
  const [userEmail, setUserEmail] = useState('')
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) { router.replace('/login'); return }
      setUserEmail(data.user.email ?? '')
      setUserName(data.user.user_metadata?.full_name ?? '')
      // Idempotent re-identify keeps returning sessions tied to the person
      identifyUser(data.user.id, {
        email: data.user.email,
        tenant_id: data.user.user_metadata?.tenant_id,
      })
    })
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
      if (tRes.ok) setTenant(await tRes.json())
      if (lRes.ok) { const d = await lRes.json(); setLeads(Array.isArray(d) ? d.length : 0) }
      if (aRes.ok) { const d = await aRes.json(); setAppts(Array.isArray(d) ? d.length : 0) }
    }).catch(() => {})
  }, [tenantId])

  // Close the mobile menu whenever the route changes
  useEffect(() => { setMobileOpen(false) }, [pathname])

  const handleLogout = async () => {
    await supabase.auth.signOut()
    // Reset so the next user on this device gets a fresh analytics identity
    resetAnalytics()
    router.replace('/login')
  }

  const sidebarProps = {
    tenantId, tenant, leadsCount, apptsCount, userName, userEmail, onLogout: handleLogout,
  }

  return (
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

        {children}
      </div>
    </div>
  )
}
