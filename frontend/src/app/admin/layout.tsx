'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { resetAnalytics } from '@/lib/analytics'
import './admin.css'

const NAV = [
  { href: '/admin', label: 'Overview' },
  { href: '/admin/tenants', label: 'Tenants' },
  { href: '/admin/calls', label: 'Calls' },
  { href: '/admin/appointments', label: 'Appointments' },
  { href: '/admin/revenue', label: 'Revenue' },
  { href: '/admin/system-health', label: 'System Health' },
]

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [verified, setVerified] = useState(false)
  const [adminEmail, setAdminEmail] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    async function check() {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) { router.replace('/login'); return }
      const res = await fetch('/api/admin/me', {
        headers: { Authorization: `Bearer ${session.access_token}` },
      })
      if (!res.ok) { router.replace('/login'); return }
      const me = await res.json()
      setAdminEmail(me.email ?? '')
      setVerified(true)
    }
    check()
  }, [router])

  // Close sidebar on navigation
  useEffect(() => { setSidebarOpen(false) }, [pathname])

  async function handleLogout() {
    resetAnalytics()
    await supabase.auth.signOut()
    router.push('/')
  }

  function isActive(href: string) {
    if (href === '/admin') return pathname === '/admin'
    return pathname.startsWith(href)
  }

  if (!verified) {
    return (
      <div className="db-root adm-shell" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div className="adm-loading"><div className="adm-spinner" />Verifying admin access…</div>
      </div>
    )
  }

  return (
    <div className="db-root adm-shell">
      {/* Top bar */}
      <header className="adm-topbar">
        <button
          className="adm-hamburger"
          onClick={() => setSidebarOpen(o => !o)}
          aria-label="Toggle menu"
        >
          ☰
        </button>
        <span className="adm-topbar-logo">Open Lines</span>
        <span className="adm-topbar-tag">Admin</span>
        <div className="adm-topbar-right">
          <span className="adm-topbar-email">{adminEmail}</span>
          <button className="adm-topbar-logout" onClick={handleLogout}>Sign out</button>
        </div>
      </header>

      {/* Mobile overlay */}
      <div
        className={`adm-overlay${sidebarOpen ? '' : ' hidden'}`}
        onClick={() => setSidebarOpen(false)}
      />

      {/* Sidebar */}
      <aside className={`adm-sidebar${sidebarOpen ? ' open' : ''}`}>
        {NAV.map(n => (
          <Link
            key={n.href}
            href={n.href}
            className={`adm-nav-link${isActive(n.href) ? ' active' : ''}`}
          >
            <span className="adm-nav-dot" />
            {n.label}
          </Link>
        ))}
      </aside>

      {/* Main content */}
      <main className="adm-main">
        {children}
      </main>
    </div>
  )
}
