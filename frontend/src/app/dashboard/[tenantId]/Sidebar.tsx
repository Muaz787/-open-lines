'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

export const BOOKING_INDUSTRIES = new Set([
  'realtor', 'clinic', 'dental', 'legal', 'plumber',
  'builder', 'restaurant', 'beauty', 'custom',
])

export interface SidebarTenant {
  id: string
  business_name: string
  industry: string
  subscription_plan?: string
  subscription_status?: string
}

interface SidebarProps {
  tenantId: string
  tenant: SidebarTenant | null
  leadsCount: number
  apptsCount: number
  userName: string
  userEmail: string
  onNavigate?: () => void
  onLogout: () => void
  mobile?: boolean
}

// ── Icons ──────────────────────────────────────────────────────────────────
export const LogoMark = ({ size = 22 }: { size?: number }) => (
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
    <rect x="1.5" y="2.5" width="12" height="11" rx="1.5"/><path d="M1.5 6.5h12M5 1.5v2M10 1.5v2"/>
  </svg>
)
const IconSettings = () => (
  <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
    <circle cx="7.5" cy="4.8" r="2.3"/><path d="M2 13.5c0-3.04 2.46-5.5 5.5-5.5s5.5 2.46 5.5 5.5" strokeLinecap="round"/>
  </svg>
)
const IconIntegrations = () => (
  <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
    <rect x="1.5" y="1.5" width="5" height="5" rx="1.2"/>
    <rect x="8.5" y="1.5" width="5" height="5" rx="1.2"/>
    <path d="M4 6.5v2M4 8.5h7M11 6.5v2" strokeLinecap="round"/>
    <rect x="8.5" y="8.5" width="5" height="5" rx="1.2"/>
  </svg>
)
const IconBilling = () => (
  <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
    <path d="M1.5 7.5L7.5 2l6 5.5" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M3 7v5.5a.5.5 0 00.5.5H6V9.5h3v3.5h2.5a.5.5 0 00.5-.5V7" strokeLinejoin="round"/>
  </svg>
)
const IconPayments = () => (
  <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
    <rect x="1.5" y="3.5" width="12" height="8" rx="1.2"/>
    <path d="M1.5 6.5h12" strokeLinecap="round"/>
    <path d="M4 9.5h2" strokeLinecap="round"/>
  </svg>
)
const IconUsage = () => (
  <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
    <rect x="1.5" y="9.5" width="2.5" height="4" rx="0.5"/><rect x="6.25" y="6" width="2.5" height="7.5" rx="0.5"/>
    <rect x="11" y="2.5" width="2.5" height="11" rx="0.5"/>
  </svg>
)
const IconSignOut = () => (
  <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
    <path d="M6 2H3a1 1 0 00-1 1v9a1 1 0 001 1h3"/><path strokeLinecap="round" d="M10 10l3-3-3-3M13 7H6"/>
  </svg>
)

export default function Sidebar({
  tenantId, tenant, leadsCount, apptsCount, userName, userEmail, onNavigate, onLogout, mobile = false,
}: SidebarProps) {
  const pathname = usePathname()
  const base = `/dashboard/${tenantId}`
  // Active when the path equals the item's href. Dashboard is the exact base.
  const isActive = (href: string) => href === base ? pathname === base : pathname.startsWith(href)

  const planBadge = () => {
    if (tenant?.subscription_status === 'active' && tenant?.subscription_plan)
      return <span className="db-nav-badge db-badge-green">{tenant.subscription_plan}</span>
    if (!tenant?.subscription_status || tenant.subscription_status === 'none' || tenant.subscription_status === 'incomplete')
      return <span className="db-nav-badge db-badge-amber">Free</span>
    if (tenant?.subscription_status === 'past_due')
      return <span className="db-nav-badge db-badge-red">Past due</span>
    return null
  }

  const isSubscribed = tenant?.subscription_status === 'active' || tenant?.subscription_status === 'canceling'
  const click = onNavigate

  const navItem = (href: string, icon: React.ReactNode, label: React.ReactNode, badge?: React.ReactNode) => {
    const active = isActive(href)
    return (
      <Link href={href} className={`db-nav-item${active ? ' active' : ''}`} onClick={click}>
        {active && <div className="db-nav-indicator" />}
        {icon}
        {label}
        {badge}
      </Link>
    )
  }

  return (
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
        {navItem(base, <IconDashboard />, 'Dashboard')}
        {navItem(`${base}/knowledge-base`, <IconKB />, 'Knowledge Base')}
        {navItem(`${base}/leads`, <IconLeads />, 'Leads', leadsCount > 0 ? <span className="db-nav-badge db-badge-red">{leadsCount}</span> : undefined)}
        {navItem(`${base}/calls`, <IconCalls />, 'Calls')}
        {tenant && BOOKING_INDUSTRIES.has(tenant.industry) &&
          navItem(`${base}/calendar`, <IconCalendar />, 'Calendar', apptsCount > 0 ? <span className="db-nav-badge db-badge-green">{apptsCount}</span> : undefined)}
        <div className="db-nav-label">Account</div>
        {navItem(`${base}/integrations`, <IconIntegrations />, 'Integrations')}
        {navItem(`${base}/payments`, <IconPayments />, 'Deposit Collection')}
        {navItem(`${base}/settings`, <IconSettings />, 'Settings')}
        {navItem(`${base}/subscription`, <IconBilling />, <>Billing &amp; Payments</>, planBadge())}
        {navItem(`${base}/usage`, <IconUsage />, 'Usage')}
        {mobile && (
          <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 8 }}>
            <button className="db-nav-item" onClick={onLogout} style={{ color: '#f87171' }}>
              <IconSignOut />
              Sign out
            </button>
          </div>
        )}
      </div>
      {!isSubscribed && (
        <Link href={`${base}/subscription`} className="db-upgrade-pill" onClick={click}>
          <div className="db-upgrade-label">↑ Choose a plan</div>
          <div className="db-upgrade-sub">Start from $99/mo</div>
        </Link>
      )}
      <div className="db-sidebar-footer">
        <button className="db-user-row" onClick={onLogout} title="Sign out" style={mobile ? { cursor: 'pointer' } : undefined}>
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
    </>
  )
}
