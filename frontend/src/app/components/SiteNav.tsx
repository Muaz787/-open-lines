'use client'

import { useState } from 'react'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'
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

// Shared top nav for the marketing sub-pages. Desktop shows the mid links;
// mobile uses a hamburger menu (matching the landing) so users can move between
// pages without going back to the home page first.
export default function SiteNav() {
  const [menuOpen, setMenuOpen] = useState(false)
  const closeMenu = () => setMenuOpen(false)
  const nav = (label: string) => trackEvent('nav_link_clicked', { link: label })

  return (
    <>
      <nav className="site-nav">
        <Link href="/" className="nav-logo">
          <LogoMark />
          <span className="logo-name">Open Lines</span>
        </Link>
        <div className="nav-mid">
          {LINKS.map(l => (
            <Link key={l.href} href={l.href} onClick={() => nav(l.label)}>{l.label}</Link>
          ))}
        </div>
        <div className="nav-right">
          <Link href="/onboarding" onClick={() => trackEvent('get_started_clicked', { location: 'subpage_nav' })}>
            <button className="btn-nav">Get started</button>
          </Link>
          <Link href="/login" onClick={() => trackEvent('login_clicked', { location: 'subpage_nav' })}>
            <button className="btn-nav" style={{ background: 'transparent', color: 'var(--text-2)', border: '1px solid var(--border-2)' }}>
              Sign in
            </button>
          </Link>
          {/* Hamburger — mobile only */}
          <button
            className="hamburger"
            onClick={() => setMenuOpen(o => !o)}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          >
            {menuOpen ? (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <line x1="4" y1="4" x2="16" y2="16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                <line x1="16" y1="4" x2="4" y2="16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <line x1="2" y1="5"  x2="18" y2="5"  stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                <line x1="2" y1="10" x2="18" y2="10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                <line x1="2" y1="15" x2="18" y2="15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
              </svg>
            )}
          </button>
        </div>
      </nav>

      {/* Mobile menu */}
      <AnimatePresence>
        {menuOpen && (
          <motion.div
            className="mobile-menu"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            {LINKS.map(l => (
              <Link key={l.href} href={l.href} className="mobile-menu-link"
                onClick={() => { nav(l.label); closeMenu() }}>
                {l.label}
              </Link>
            ))}
            <Link href="/login" className="mobile-menu-link"
              onClick={() => { trackEvent('login_clicked', { location: 'subpage_menu' }); closeMenu() }}>
              Sign in
            </Link>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
