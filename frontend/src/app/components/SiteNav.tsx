'use client'

import Link from 'next/link'
import { trackEvent } from '@/lib/analytics'

const LogoMark = () => (
  <svg width="24" height="24" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

const LINKS = [
  { href: '/how-it-works', label: 'How it works' },
  { href: '/industries',   label: 'Industries' },
  { href: '/platform',     label: 'Platform' },
  { href: '/pricing',      label: 'Pricing' },
]

// Shared top nav for the marketing sub-pages. Mid links hide on mobile (CSS),
// where the footer provides cross-page navigation.
export default function SiteNav() {
  return (
    <nav>
      <Link href="/" className="nav-logo">
        <LogoMark />
        <span className="logo-name">Open Lines</span>
      </Link>
      <div className="nav-mid">
        {LINKS.map(l => (
          <Link key={l.href} href={l.href} onClick={() => trackEvent('nav_link_clicked', { link: l.label })}>
            {l.label}
          </Link>
        ))}
      </div>
      <div className="nav-right">
        <Link href="/login" onClick={() => trackEvent('login_clicked', { location: 'subpage_nav' })}>
          <button className="btn-nav" style={{ background: 'transparent', color: 'var(--text-2)', border: '1px solid var(--border-2)' }}>
            Sign in
          </button>
        </Link>
        <Link href="/onboarding" onClick={() => trackEvent('get_started_clicked', { location: 'subpage_nav' })}>
          <button className="btn-nav">Get started</button>
        </Link>
      </div>
    </nav>
  )
}
