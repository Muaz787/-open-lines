'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { resetAnalytics } from '@/lib/analytics'
import './admin.css'

const NAV = [
  { href: '/admin', label: 'Overview', icon: '▦' },
  { href: '/admin/tenants', label: 'Tenants', icon: '⊞' },
  { href: '/admin/calls', label: 'Calls', icon: '◎' },
  { href: '/admin/appointments', label: 'Appointments', icon: '◈' },
  { href: '/admin/revenue', label: 'Revenue', icon: '◇' },
  { href: '/admin/system-health', label: 'System Health', icon: '◉' },
]

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [verified, setVerified] = useState(false)
  const [adminEmail, setAdminEmail] = useState('')

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
        <div className="adm-loading">
          <div className="adm-spinner" />
          Verifying admin access…
        </div>
      </div>
    )
  }

  return (
    <div className="db-root adm-shell">
      <aside className="adm-sidebar">
        <div className="adm-sidebar-header">
          <div className="adm-logo">Open Lines</div>
          <div className="adm-logo-sub">Internal Admin</div>
        </div>

        <nav className="adm-nav">
          {NAV.map(n => (
            <Link
              key={n.href}
              href={n.href}
              className={`adm-nav-link${isActive(n.href) ? ' active' : ''}`}
            >
              <span className="adm-nav-icon">{n.icon}</span>
              {n.label}
            </Link>
          ))}
        </nav>

        <div className="adm-sidebar-footer">
          <div style={{ marginBottom: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {adminEmail}
          </div>
          <button onClick={handleLogout}>Sign out</button>
        </div>
      </aside>

      <main className="adm-main">
        {children}
      </main>
    </div>
  )
}
