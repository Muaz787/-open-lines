import Link from 'next/link'

const LogoMark = () => (
  <svg width="24" height="24" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

export default function SiteFooter() {
  return (
    <footer>
      <div className="ft-left">
        <div className="nav-logo">
          <LogoMark />
          <span className="logo-name">Open Lines</span>
        </div>
        <div className="ft-tag">
          AI voice receptionist — answers every call, captures every lead, books every appointment.
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
        <div className="ft-links">
          <Link href="/">Home</Link>
          <Link href="/how-it-works">How it works</Link>
          <Link href="/industries">Industries</Link>
          <Link href="/platform">Platform</Link>
          <Link href="/pricing">Pricing</Link>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/acceptable-use">Acceptable Use</Link>
          <Link href="/dpa">DPA</Link>
          <Link href="/subprocessors">Sub-processors</Link>
        </div>
        <div className="status-bar">
          <div className="st-dot" />
          All systems operational
        </div>
      </div>
    </footer>
  )
}
