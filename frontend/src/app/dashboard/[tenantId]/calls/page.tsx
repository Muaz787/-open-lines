'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'
import { supabase } from '@/lib/supabase'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const BOOKING_INDUSTRIES = new Set([
  'realtor', 'clinic', 'dental', 'legal', 'plumber',
  'builder', 'restaurant', 'beauty', 'custom',
])

interface CallLead {
  name?: string
  phone?: string
  urgency?: string
  summary?: string
  metadata?: { key_details?: Record<string, string>; suggested_next_step?: string }
}

interface CallRow {
  id: string
  vapi_call_id?: string
  duration_secs?: number
  created_at: string
  lead_id?: string
  leads?: CallLead
}

interface CallDetail extends CallRow {
  transcript?: string
}

interface Analytics {
  total_calls: number
  avg_duration_secs: number
  urgency_breakdown: { hot: number; warm: number; cold: number; unknown: number }
  calls_by_day: Record<string, number>
}

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  subscription_plan?: string
  subscription_status?: string
}

type UrgencyFilter = 'all' | 'hot' | 'warm' | 'cold'
type Period = '7' | '30' | '0'

function formatDuration(secs?: number): string {
  if (!secs) return '—'
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

function formatCallDate(iso: string): string {
  const d = new Date(iso)
  const date = d.toLocaleDateString('en-CA', { month: 'short', day: 'numeric' })
  const time = d.toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit', hour12: true })
  return `${date} · ${time}`
}

function initials(name?: string, phone?: string): string {
  if (name) return name.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
  return (phone ?? '??').slice(-2)
}

function urgBadgeClass(u?: string): string {
  switch (u?.toLowerCase()) {
    case 'hot':  return 'db-urg-hot'
    case 'warm': return 'db-urg-warm'
    case 'cold': return 'db-urg-cold'
    default:     return 'db-urg-none'
  }
}

function TranscriptLines({ text }: { text: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {text.split('\n').filter(l => l.trim()).map((line, i) => {
        const isAI   = line.startsWith('AI:')
        const isUser = line.startsWith('User:')
        const speaker = isAI ? 'AI' : isUser ? 'You' : null
        const content = isAI ? line.slice(3).trim() : isUser ? line.slice(5).trim() : line
        return (
          <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
            <span style={{
              fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
              color: isAI ? '#3dba72' : '#888',
              minWidth: 28, paddingTop: 2, flexShrink: 0,
            }}>
              {speaker ?? ''}
            </span>
            <span style={{ fontSize: 12, color: isAI ? '#333' : '#555', lineHeight: 1.6 }}>
              {content}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 28 28" fill="none" width={size} height={size}>
      <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    </svg>
  )
}

export default function CallsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const router = useRouter()

  const [tenant, setTenant]           = useState<Tenant | null>(null)
  const [calls, setCalls]             = useState<CallRow[]>([])
  const [analytics, setAnalytics]     = useState<Analytics | null>(null)
  const [loading, setLoading]         = useState(true)
  const [period, setPeriod]           = useState<Period>('30')
  const [urgFilter, setUrgFilter]     = useState<UrgencyFilter>('all')
  const [expandedId, setExpandedId]   = useState<string | null>(null)
  const [detailMap, setDetailMap]     = useState<Record<string, CallDetail>>({})
  const [detailLoading, setDetailLoading] = useState<string | null>(null)
  const [menuOpen, setMenuOpen]       = useState(false)
  const [userEmail, setUserEmail]     = useState('')
  const [userName, setUserName]       = useState('')

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) router.replace('/login')
      else {
        setUserEmail(data.user.email ?? '')
        setUserName(data.user.user_metadata?.full_name ?? '')
      }
    })
  }, [router])

  const fetchTenant = useCallback(async () => {
    try {
      const { data } = await supabase.from('tenants').select('*').eq('id', tenantId).single()
      if (data) setTenant(data)
    } catch {}
  }, [tenantId])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [callsRes, analyticsRes] = await Promise.all([
        fetch(`${API}/calls/${tenantId}?days=${period}`),
        fetch(`${API}/calls/${tenantId}/analytics?days=${period}`),
      ])
      if (callsRes.ok) setCalls(await callsRes.json())
      if (analyticsRes.ok) setAnalytics(await analyticsRes.json())
    } catch {}
    finally { setLoading(false) }
  }, [tenantId, period])

  useEffect(() => { fetchTenant() }, [fetchTenant])
  useEffect(() => { fetchData() }, [fetchData])

  const toggleExpand = async (callId: string) => {
    if (expandedId === callId) {
      setExpandedId(null)
      return
    }
    setExpandedId(callId)
    if (!detailMap[callId]) {
      setDetailLoading(callId)
      try {
        const res = await fetch(`${API}/calls/${tenantId}/${callId}`)
        if (res.ok) {
          const detail: CallDetail = await res.json()
          setDetailMap(m => ({ ...m, [callId]: detail }))
        }
      } catch {}
      finally { setDetailLoading(null) }
    }
  }

  const handleLogout = async () => {
    await supabase.auth.signOut()
    router.replace('/login')
  }

  const filtered = urgFilter === 'all'
    ? calls
    : calls.filter(c => (c.leads?.urgency ?? 'unknown').toLowerCase() === urgFilter)

  const hotPct = analytics && analytics.total_calls > 0
    ? Math.round((analytics.urgency_breakdown.hot / analytics.total_calls) * 100)
    : 0

  // ── Icons ──────────────────────────────────────────────────
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
  const IconSub = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <rect x="1.5" y="3.5" width="12" height="9" rx="1.5"/>
      <path d="M1.5 6.5h12"/>
      <path strokeLinecap="round" d="M5 10h2M8.5 10h1.5"/>
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

  const planBadge = () => {
    if (tenant?.subscription_status === 'active' && tenant?.subscription_plan)
      return <span className="db-nav-badge db-badge-green">{tenant.subscription_plan}</span>
    if (!tenant?.subscription_status || tenant.subscription_status === 'none' || tenant.subscription_status === 'incomplete')
      return <span className="db-nav-badge db-badge-amber">Free</span>
    if (tenant.subscription_status === 'past_due')
      return <span className="db-nav-badge db-badge-red">Past due</span>
    return null
  }

  const Sidebar = ({ mobile = false, onClose }: { mobile?: boolean; onClose?: () => void }) => (
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
        <Link href={`/dashboard/${tenantId}`} className="db-nav-item" onClick={onClose}>
          <IconDashboard />
          Dashboard
        </Link>
        <Link href={`/dashboard/${tenantId}/knowledge-base`} className="db-nav-item" onClick={onClose}>
          <IconKB />
          Knowledge Base
        </Link>
        <Link href={`/dashboard/${tenantId}/leads`} className="db-nav-item" onClick={onClose}>
          <IconLeads />
          Leads
        </Link>
        <div className="db-nav-item active">
          <div className="db-nav-indicator" />
          <IconCalls />
          Calls
        </div>
        {tenant && BOOKING_INDUSTRIES.has(tenant.industry) && (
          <Link href={`/dashboard/${tenantId}/calendar`} className="db-nav-item" onClick={onClose}>
            <IconCalendar />
            Calendar
          </Link>
        )}
        <div className="db-nav-label">Account</div>
        <Link href={`/dashboard/${tenantId}/settings`} className="db-nav-item" onClick={onClose}>
          <IconSettings />
          Settings
        </Link>
        <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item" onClick={onClose}>
          <IconBilling />
          Billing &amp; Payments
          {planBadge()}
        </Link>
        <Link href={`/dashboard/${tenantId}/usage`} className="db-nav-item" onClick={onClose}>
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
    </>
  )

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
            <span className="db-mobile-logo-name">Open Lines</span>
          </div>
          <button
            className="db-hamburger"
            onClick={() => setMenuOpen(o => !o)}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          >
            {menuOpen ? (
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

        {/* Desktop topbar */}
        <div className="db-topbar">
          <span className="db-topbar-title">Calls</span>
          <div className="db-topbar-right">
            <div className="db-period-tabs">
              {([['7', '7d'], ['30', '30d'], ['0', 'All']] as const).map(([v, label]) => (
                <button
                  key={v}
                  className={`db-period-tab${period === v ? ' active' : ''}`}
                  onClick={() => setPeriod(v)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="db-content">

          {/* Analytics stat cards */}
          {analytics && (
            <div className="db-stats-wrap">
              <div className="db-stats-topbar">
                <span className="db-stats-title">Call Performance</span>
              </div>
              <div className="db-stats-v2">
                {[
                  { label: 'Total Calls',    value: analytics.total_calls,      suffix: '' },
                  { label: 'Avg Duration',   value: analytics.avg_duration_secs ? `${Math.floor(analytics.avg_duration_secs / 60)}m ${analytics.avg_duration_secs % 60}s` : '—', suffix: null },
                  { label: 'Hot Leads',      value: analytics.urgency_breakdown.hot, suffix: '' },
                  { label: 'Hot Lead %',     value: `${hotPct}%`, suffix: null },
                ].map(({ label, value, suffix }) => (
                  <div key={label} className="db-stat-card">
                    <div className="db-stat-meta">
                      <span className="db-stat-label">{label}</span>
                    </div>
                    <div className="db-stat-num">
                      {typeof value === 'number' ? value.toLocaleString() : value}
                      {suffix !== null && suffix && <span className="db-stat-unit"> {suffix}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Urgency filter tabs */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
            {(['all', 'hot', 'warm', 'cold'] as const).map(u => (
              <button
                key={u}
                onClick={() => setUrgFilter(u)}
                style={{
                  padding: '4px 12px', borderRadius: 6, border: '1px solid',
                  fontSize: 11, fontWeight: 600, cursor: 'pointer', transition: 'all 0.12s',
                  borderColor: urgFilter === u ? '#3dba72' : '#e8e6e0',
                  background: urgFilter === u ? '#f0fdf4' : '#fff',
                  color: urgFilter === u ? '#16a34a' : '#888',
                  fontFamily: 'var(--font-mono), monospace',
                  textTransform: 'uppercase', letterSpacing: '0.05em',
                }}
              >
                {u === 'all' ? 'All' : u.charAt(0).toUpperCase() + u.slice(1)}
                {u !== 'all' && analytics && (
                  <span style={{ marginLeft: 5, opacity: 0.7 }}>
                    {analytics.urgency_breakdown[u]}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Call list */}
          <div className="db-section-card">
            <div className="db-section-hdr">
              <div className="db-section-title-row">
                <div className="db-section-icon" style={{ background: '#f0fdf4' }}>📞</div>
                <span className="db-section-name">Call History</span>
                <span className="db-section-hint">{filtered.length} calls</span>
              </div>
            </div>

            {loading ? (
              <div className="db-empty-v2">
                <div className="db-empty-v2-title">Loading…</div>
              </div>
            ) : filtered.length === 0 ? (
              <div className="db-empty-v2">
                <div className="db-empty-v2-title">No calls yet.</div>
                <div className="db-empty-v2-sub">Calls will appear here after your first inbound call.</div>
              </div>
            ) : (
              filtered.map(call => {
                const lead = call.leads
                const isExpanded = expandedId === call.id
                const detail = detailMap[call.id]
                const isLoadingDetail = detailLoading === call.id

                return (
                  <div key={call.id} className="db-lead-row" onClick={() => toggleExpand(call.id)}>
                    <div className="db-lead-main">
                      <div className="db-lead-av">{initials(lead?.name, lead?.phone)}</div>
                      <div className="db-lead-info">
                        <div className="db-lead-name">
                          {lead?.name ?? 'Unknown'}
                          {lead?.phone && <span className="db-lead-phone-inline"> · {lead.phone}</span>}
                        </div>
                        <div className="db-lead-sum">{lead?.summary ?? 'No summary'}</div>
                      </div>
                      <span className={urgBadgeClass(lead?.urgency)}>
                        {lead?.urgency
                          ? lead.urgency.charAt(0).toUpperCase() + lead.urgency.slice(1)
                          : 'New'}
                      </span>
                      <span className="db-lead-time" style={{ minWidth: 64, textAlign: 'right' }}>
                        {formatDuration(call.duration_secs)}
                      </span>
                      <span className="db-lead-time">{formatCallDate(call.created_at)}</span>
                    </div>

                    <AnimatePresence>
                      {isExpanded && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          style={{ overflow: 'hidden' }}
                        >
                          <div className="db-lead-expanded">
                            {isLoadingDetail ? (
                              <div style={{ fontSize: 12, color: '#888', padding: '8px 0' }}>Loading transcript…</div>
                            ) : detail?.transcript ? (
                              <>
                                <div style={{ fontSize: 11, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
                                  Transcript
                                </div>
                                <TranscriptLines text={detail.transcript} />
                              </>
                            ) : (
                              <div style={{ fontSize: 12, color: '#888' }}>No transcript available.</div>
                            )}

                            {lead?.metadata?.key_details && Object.keys(lead.metadata.key_details).length > 0 && (
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 14 }}>
                                {Object.entries(lead.metadata.key_details).map(([k, v]) => (
                                  <div key={k} style={{
                                    fontSize: 11, padding: '3px 9px', borderRadius: 5,
                                    background: '#f4f3f0', color: '#555', border: '1px solid #e8e6e0',
                                  }}>
                                    <span style={{ fontWeight: 600, color: '#16161a' }}>
                                      {k.replace(/_/g, ' ')}:
                                    </span>{' '}
                                    {String(v)}
                                  </div>
                                ))}
                              </div>
                            )}

                            {lead?.metadata?.suggested_next_step && (
                              <div style={{ marginTop: 12, fontSize: 12, color: '#555' }}>
                                <span style={{ fontWeight: 600, color: '#16161a' }}>Next step: </span>
                                {lead.metadata.suggested_next_step}
                              </div>
                            )}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )
              })
            )}
          </div>
        </div>
      </div>

      {/* ── Mobile overlay menu ── */}
      <AnimatePresence>
        {menuOpen && (
          <motion.div
            className="db-overlay-menu"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={() => setMenuOpen(false)}
          >
            <motion.div
              className="db-overlay-panel"
              initial={{ x: -260 }} animate={{ x: 0 }} exit={{ x: -260 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              onClick={e => e.stopPropagation()}
            >
              <Sidebar mobile onClose={() => setMenuOpen(false)} />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  )
}
