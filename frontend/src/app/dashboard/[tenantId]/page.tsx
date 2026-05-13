'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { KnowledgeDrawer } from './KnowledgeDrawer'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface Lead {
  id: string
  name?: string
  phone?: string
  summary?: string
  urgency?: string
  status?: string
  created_at: string
  metadata?: {
    key_details?: Record<string, string>
    suggested_next_step?: string
  }
}

interface Call {
  id: string
  transcript?: string
  duration_secs?: number
  created_at: string
}

interface LeadDetail extends Lead {
  calls: Call[]
}

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  website_url?: string
  last_crawl_at?: string
}

interface CalendarStatus {
  connected: boolean
  appointment_duration_minutes: number
  calendar_timezone: string
}

interface Stats {
  total_calls: number
  total_leads: number
  minutes_handled: number
  appointments_booked: number
}

interface Insight {
  title: string
  body: string
  type: 'opportunity' | 'warning' | 'trend' | 'success'
}

interface InsightsData {
  insights: Insight[]
  generated_at: string | null
}

interface Appointment {
  id: string
  caller_name?: string
  caller_phone?: string
  service?: string
  appointment_datetime: string
  duration_minutes?: number
  status?: string
}

const DURATION_OPTIONS = [30, 45, 60, 90, 120]

const BOOKING_INDUSTRIES = new Set([
  'realtor', 'clinic', 'dental', 'legal', 'plumber',
  'builder', 'restaurant', 'beauty', 'custom',
])

function timeAgo(iso: string): string {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return 'just now'
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function formatCallDate(iso: string): string {
  const d = new Date(iso)
  const date = d.toLocaleDateString('en-CA', { month: 'short', day: 'numeric' })
  const time = d.toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit', hour12: true })
  return `${date} · ${time}`
}

function formatDuration(secs: number): string {
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

function urgencyClass(u?: string): string {
  switch (u?.toLowerCase()) {
    case 'hot':  return 'hot'
    case 'warm': return 'warm'
    case 'cold': return 'cold'
    default:     return 'new'
  }
}

function statusClass(s?: string): string {
  switch (s?.toLowerCase()) {
    case 'booked':    return 'ok'
    case 'contacted': return 'pend'
    default:          return 'new'
  }
}

function initials(name?: string, phone?: string): string {
  if (name) return name.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
  return (phone ?? '??').slice(-2)
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
              color: isAI ? 'var(--accent)' : 'var(--text-3)',
              minWidth: 28, paddingTop: 2, flexShrink: 0,
            }}>
              {speaker ?? ''}
            </span>
            <span style={{ fontSize: 12, color: isAI ? 'var(--text-2)' : 'var(--text)', lineHeight: 1.6 }}>
              {content}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function formatApptDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-CA', {
    weekday: 'short', month: 'short', day: 'numeric',
  }) + ' · ' + d.toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit', hour12: true })
}

function DashboardPage() {
  const { tenantId }  = useParams<{ tenantId: string }>()
  const router        = useRouter()
  const searchParams  = useSearchParams()

  const [tenant, setTenant]           = useState<Tenant | null>(null)
  const [leads, setLeads]             = useState<Lead[]>([])
  const [loading, setLoading]         = useState(true)
  const [expandedId, setExpandedId]   = useState<string | null>(null)
  const [detailMap, setDetailMap]     = useState<Record<string, LeadDetail>>({})
  const [statusMap, setStatusMap]     = useState<Record<string, string>>({})
  const [expandedCallId, setExpandedCallId] = useState<string | null>(null)
  const [copied, setCopied]           = useState(false)
  const [copiedPhone, setCopiedPhone] = useState<string | null>(null)

  const [stats, setStats] = useState<Stats | null>(null)
  const [insights, setInsights]         = useState<InsightsData | null>(null)
  const [insightsLoading, setInsightsLoading] = useState(false)

  // Calendar state
  const [kbOpen, setKbOpen]                 = useState(false)

  const [calStatus, setCalStatus]           = useState<CalendarStatus | null>(null)
  const [appointments, setAppointments]     = useState<Appointment[]>([])
  const [calToast, setCalToast]             = useState<string | null>(null)
  const [calDisconnecting, setCalDisconnecting] = useState(false)
  const [durSaving, setDurSaving]           = useState(false)

  // Auth guard
  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) router.replace('/login')
    })
  }, [router])

  const handleLogout = async () => {
    await supabase.auth.signOut()
    router.replace('/login')
  }

  const fetchInsights = useCallback(async () => {
    setInsightsLoading(true)
    try {
      const res = await fetch(`${API}/leads/${tenantId}/insights`)
      if (res.ok) setInsights(await res.json())
    } catch {}
    finally { setInsightsLoading(false) }
  }, [tenantId])

  const fetchLeads = useCallback(async () => {
    try {
      const res = await fetch(`${API}/leads/${tenantId}`)
      if (res.ok) setLeads(await res.json())
    } catch {}
  }, [tenantId])

  const fetchCalendar = useCallback(async () => {
    try {
      const [sRes, aRes] = await Promise.all([
        fetch(`${API}/calendar/status/${tenantId}`),
        fetch(`${API}/calendar/appointments/${tenantId}`),
      ])
      if (sRes.ok) setCalStatus(await sRes.json())
      if (aRes.ok) setAppointments(await aRes.json())
    } catch {}
  }, [tenantId])

  useEffect(() => {
    const init = async () => {
      try {
        const [tRes, lRes, sRes] = await Promise.all([
          fetch(`${API}/onboarding/status/${tenantId}`),
          fetch(`${API}/leads/${tenantId}`),
          fetch(`${API}/leads/${tenantId}/stats`),
        ])
        if (tRes.ok) setTenant(await tRes.json())
        if (lRes.ok) setLeads(await lRes.json())
        if (sRes.ok) setStats(await sRes.json())
      } finally {
        setLoading(false)
      }
    }
    init()
    fetchCalendar()
    fetchInsights()
    const interval = setInterval(() => {
      fetchLeads()
      fetch(`${API}/leads/${tenantId}/stats`).then(r => r.ok ? r.json() : null).then(d => d && setStats(d))
    }, 30_000)
    return () => clearInterval(interval)
  }, [tenantId, fetchLeads, fetchCalendar, fetchInsights])

  // Show toast if redirected back from OAuth
  useEffect(() => {
    const calParam = searchParams.get('calendar')
    if (calParam === 'connected') {
      setCalToast('Google Calendar connected!')
      fetchCalendar()
      setTimeout(() => setCalToast(null), 4000)
    } else if (calParam === 'error') {
      setCalToast('Calendar connection failed. Please try again.')
      setTimeout(() => setCalToast(null), 5000)
    }
  }, [searchParams, fetchCalendar])

  const disconnectCalendar = async () => {
    if (!confirm('Disconnect Google Calendar? The AI will no longer be able to book appointments in real time.')) return
    setCalDisconnecting(true)
    try {
      await fetch(`${API}/calendar/disconnect/${tenantId}`, { method: 'POST' })
      await fetchCalendar()
    } finally {
      setCalDisconnecting(false)
    }
  }

  const saveDuration = async (minutes: number) => {
    setDurSaving(true)
    try {
      await fetch(`${API}/calendar/settings/${tenantId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ appointment_duration_minutes: minutes }),
      })
      setCalStatus(prev => prev ? { ...prev, appointment_duration_minutes: minutes } : prev)
    } finally {
      setDurSaving(false)
    }
  }

  const getValidCalls = (calls: Call[]) =>
    calls
      .filter(c => c.transcript && c.transcript.trim().length > 30)
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  const toggleExpand = async (leadId: string) => {
    if (expandedId === leadId) {
      setExpandedId(null)
      setExpandedCallId(null)
      return
    }
    setExpandedId(leadId)
    setExpandedCallId(null)
    if (!detailMap[leadId]) {
      try {
        const res = await fetch(`${API}/leads/${tenantId}/${leadId}`)
        if (res.ok) {
          const data: LeadDetail = await res.json()
          setDetailMap(prev => ({ ...prev, [leadId]: data }))
          const first = getValidCalls(data.calls ?? [])[0]
          if (first) setExpandedCallId(first.id)
        }
      } catch {}
    } else {
      const first = getValidCalls(detailMap[leadId].calls ?? [])[0]
      if (first) setExpandedCallId(first.id)
    }
  }

  const updateStatus = async (leadId: string, status: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setStatusMap(prev => ({ ...prev, [leadId]: status }))
    setLeads(prev => prev.map(l => l.id === leadId ? { ...l, status } : l))
    try {
      await fetch(`${API}/leads/${tenantId}/${leadId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
    } catch {}
  }

  const copyPhone = () => {
    if (tenant?.twilio_phone_number) {
      navigator.clipboard.writeText(tenant.twilio_phone_number)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const copyLeadPhone = (e: React.MouseEvent, phone: string, leadId: string) => {
    e.stopPropagation()
    navigator.clipboard.writeText(phone)
    setCopiedPhone(leadId)
    setTimeout(() => setCopiedPhone(null), 2000)
  }

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
        <div style={{ fontSize: 13, color: 'var(--text-3)' }}>Loading…</div>
      </div>
    )
  }

  return (
    <div className="db-page">
      {/* ── Platform nav bar ── */}
      <div className="db-nav">
        <div className="nav-logo">
          <svg width="26" height="26" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
            <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
          </svg>
          <span className="logo-name" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Open Lines</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => setKbOpen(true)}
            style={{
              fontSize: 12, color: 'var(--text-2)', background: 'none',
              border: '1px solid var(--border-2)', borderRadius: 6,
              padding: '6px 12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--text-3)'; (e.currentTarget as HTMLElement).style.color = 'var(--text)' }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-2)'; (e.currentTarget as HTMLElement).style.color = 'var(--text-2)' }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
            </svg>
            Knowledge Base
          </button>
          <button
            onClick={handleLogout}
            style={{
              fontSize: 12, color: 'var(--text-3)', background: 'none',
              border: '1px solid var(--border-2)', borderRadius: 6,
              padding: '6px 12px', cursor: 'pointer',
            }}
          >
            Sign out
          </button>
        </div>
      </div>

      {/* ── Business identity strip ── */}
      <div className="db-header">
        <div className="db-biz" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
          {tenant?.business_name ?? 'Dashboard'}
        </div>
        <div className="db-meta" style={{ marginTop: 6 }}>
          {tenant?.industry && (
            <span className="industry-badge">{tenant.industry}</span>
          )}
          {tenant?.twilio_phone_number && (
            <div className="phone-chip">
              {tenant.twilio_phone_number}
              <button className="copy-btn" onClick={copyPhone}>
                {copied ? '✓ Copied' : 'Copy'}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Toast */}
      <AnimatePresence>
        {calToast && (
          <motion.div
            initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
            style={{
              position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)',
              background: 'var(--text)', color: 'var(--bg)', padding: '10px 20px',
              borderRadius: 8, fontSize: 13, fontWeight: 500, zIndex: 100,
              boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
            }}
          >
            {calToast}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="db-body">

        {/* ── Stats strip ── */}
        {stats && (
          <div className="db-stats">
            {[
              { label: 'Calls Handled',       value: stats.total_calls,          unit: '',    raw: stats.total_calls },
              { label: 'Leads Captured',      value: stats.total_leads,          unit: '',    raw: stats.total_leads },
              { label: 'Minutes on the Phone', value: stats.minutes_handled,     unit: 'min', raw: stats.minutes_handled },
              { label: 'Appointments Booked', value: stats.appointments_booked,  unit: '',    raw: stats.appointments_booked },
            ].map(({ label, value, unit, raw }) => {
              const noData = unit === 'min' && raw === 0 && stats.total_calls > 0
              return (
              <div key={label} style={{
                border: '1px solid var(--border)',
                borderRadius: 10,
                padding: '16px 18px',
                background: 'var(--bg-2)',
              }}>
                <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 8 }}>
                  {label}
                </div>
                <div style={{ fontSize: 26, fontWeight: 700, color: noData ? 'var(--text-3)' : 'var(--text)', lineHeight: 1, fontFamily: 'var(--font-syne), sans-serif' }}>
                  {noData
                    ? <span title="Duration data unavailable for historical calls">—</span>
                    : <>{value.toLocaleString()}{unit && <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-3)', marginLeft: 4 }}>{unit}</span>}</>
                  }
                </div>
              </div>
            )})}
          </div>
        )}

        {/* ── AI Insights ── */}
        {(insights || insightsLoading) && (
          <div style={{ marginBottom: 32 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 15, lineHeight: 1 }}>✦</span>
                <div className="db-section-title" style={{ margin: 0 }}>AI Insights</div>
              </div>
              <button
                onClick={fetchInsights}
                disabled={insightsLoading}
                style={{
                  fontSize: 11, color: 'var(--text-3)', background: 'none',
                  border: '1px solid var(--border-2)', borderRadius: 5,
                  padding: '4px 10px', cursor: insightsLoading ? 'default' : 'pointer',
                  opacity: insightsLoading ? 0.5 : 1,
                }}
              >
                {insightsLoading ? 'Thinking…' : 'Refresh'}
              </button>
            </div>

            <div style={{
              border: '1px solid var(--border)',
              borderRadius: 10,
              overflow: 'hidden',
              background: 'var(--bg-2)',
            }}>
              {insightsLoading && !insights?.insights.length ? (
                <div style={{ padding: '24px 20px', display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-3)', fontSize: 13 }}>
                  <span style={{ animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>◌</span>
                  Analyzing your calls and leads…
                </div>
              ) : insights?.insights.length === 0 ? (
                <div style={{ padding: '18px 20px', fontSize: 13, color: 'var(--text-3)' }}>
                  Not enough data yet — insights appear after a few calls.
                </div>
              ) : (
                <div>
                  {(insights?.insights ?? []).map((ins, i) => {
                    const typeColors: Record<string, { bg: string; dot: string }> = {
                      opportunity: { bg: 'var(--accent-dim)',          dot: 'var(--accent)' },
                      success:     { bg: 'rgba(52,199,89,0.12)',        dot: '#34C759' },
                      warning:     { bg: 'rgba(255,149,0,0.12)',        dot: '#FF9500' },
                      trend:       { bg: 'rgba(59,126,246,0.12)',       dot: '#3B7EF6' },
                    }
                    const colors = typeColors[ins.type] ?? typeColors.trend
                    return (
                      <div key={i} style={{
                        display: 'grid', gridTemplateColumns: '8px 1fr', gap: 14,
                        padding: '16px 20px',
                        borderTop: i > 0 ? '1px solid var(--border)' : 'none',
                        alignItems: 'start',
                      }}>
                        <div style={{
                          width: 8, height: 8, borderRadius: '50%',
                          background: colors.dot, marginTop: 5, flexShrink: 0,
                        }} />
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>
                            {ins.title}
                            <span style={{
                              marginLeft: 8, fontSize: 10, fontWeight: 600,
                              letterSpacing: '0.06em', textTransform: 'uppercase',
                              background: colors.bg, color: colors.dot,
                              padding: '2px 7px', borderRadius: 4,
                            }}>
                              {ins.type}
                            </span>
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6 }}>
                            {ins.body}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                  {insights?.generated_at && (
                    <div style={{ padding: '10px 20px', fontSize: 11, color: 'var(--text-3)', borderTop: '1px solid var(--border)' }}>
                      Generated {timeAgo(insights.generated_at)}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Calendar section ── */}
        {tenant && BOOKING_INDUSTRIES.has(tenant.industry) && (
          <div style={{ marginBottom: 32 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div className="db-section-title">Calendar Booking</div>
              {calStatus?.connected && (
                <span style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>
                  ✓ Google Calendar connected
                </span>
              )}
            </div>

            {calStatus && !calStatus.connected && (
              <div style={{
                border: '1px solid var(--border-2)', borderRadius: 14, overflow: 'hidden',
                background: 'var(--bg-2)', boxShadow: 'var(--shadow)',
              }}>
                {/* Accent top bar */}
                <div style={{ height: 3, background: 'linear-gradient(90deg, #4285F4, #34A853, #FBBC05, #EA4335)' }} />

                <div className="db-cal-connect" style={{ padding: '28px 32px', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 20 }}>
                  {/* Google Calendar icon */}
                  <div style={{
                    width: 56, height: 56, borderRadius: 14, background: 'var(--bg)',
                    border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    boxShadow: 'var(--shadow)',
                  }}>
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                      <rect x="3" y="4" width="18" height="18" rx="2" stroke="#4285F4" strokeWidth="1.8"/>
                      <line x1="16" y1="2" x2="16" y2="6" stroke="#4285F4" strokeWidth="1.8" strokeLinecap="round"/>
                      <line x1="8" y1="2" x2="8" y2="6" stroke="#4285F4" strokeWidth="1.8" strokeLinecap="round"/>
                      <line x1="3" y1="10" x2="21" y2="10" stroke="#4285F4" strokeWidth="1.8"/>
                      <circle cx="12" cy="16" r="2.5" fill="#34A853"/>
                    </svg>
                  </div>

                  <div>
                    <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--text)', marginBottom: 8, letterSpacing: '-0.01em', fontFamily: 'var(--font-syne), sans-serif' }}>
                      Book appointments in real time
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--text-3)', lineHeight: 1.65, maxWidth: 380 }}>
                      Connect Google Calendar so your AI can check availability and confirm bookings during the call — no follow-up needed.
                    </div>
                  </div>

                  {/* Feature pills */}
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
                    {['Checks live availability', 'Books instantly', 'Handles reschedules'].map(f => (
                      <span key={f} style={{
                        fontSize: 11, fontWeight: 500, color: 'var(--accent)',
                        background: 'var(--accent-dim)', borderRadius: 20, padding: '4px 12px',
                      }}>
                        ✓ {f}
                      </span>
                    ))}
                  </div>

                  <a
                    href={`${API}/calendar/connect/${tenantId}`}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 10,
                      background: 'var(--text)', color: 'var(--bg)',
                      borderRadius: 10, padding: '14px 28px',
                      fontSize: 14, fontWeight: 600, cursor: 'pointer',
                      textDecoration: 'none', letterSpacing: '-0.01em',
                      boxShadow: '0 4px 16px rgba(0,31,63,0.14)',
                      transition: 'opacity 0.2s, transform 0.2s',
                    }}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.opacity = '0.85'; (e.currentTarget as HTMLElement).style.transform = 'translateY(-1px)' }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.opacity = '1'; (e.currentTarget as HTMLElement).style.transform = 'translateY(0)' }}
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <rect x="3" y="4" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="2"/>
                      <line x1="16" y1="2" x2="16" y2="6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                      <line x1="8" y1="2" x2="8" y2="6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                      <line x1="3" y1="10" x2="21" y2="10" stroke="currentColor" strokeWidth="2"/>
                    </svg>
                    Connect Google Calendar
                  </a>

                  <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
                    You can disconnect at any time from this dashboard
                  </div>
                </div>
              </div>
            )}

            {calStatus?.connected && (
              <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
                {/* Settings row */}
                <div style={{
                  padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 24,
                  background: 'var(--bg-2)', borderBottom: appointments.length > 0 ? '1px solid var(--border)' : 'none',
                  flexWrap: 'wrap',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontSize: 12, color: 'var(--text-3)' }}>Appointment duration:</span>
                    <select
                      value={calStatus.appointment_duration_minutes}
                      onChange={e => saveDuration(Number(e.target.value))}
                      disabled={durSaving}
                      style={{
                        fontSize: 12, background: 'var(--bg)', border: '1px solid var(--border-2)',
                        borderRadius: 5, padding: '4px 8px', color: 'var(--text)', cursor: 'pointer',
                      }}
                    >
                      {DURATION_OPTIONS.map(d => (
                        <option key={d} value={d}>{d} min</option>
                      ))}
                    </select>
                  </div>
                  <button
                    onClick={disconnectCalendar}
                    disabled={calDisconnecting}
                    style={{
                      marginLeft: 'auto', fontSize: 11, color: 'var(--text-3)',
                      background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline',
                    }}
                  >
                    {calDisconnecting ? 'Disconnecting…' : 'Disconnect'}
                  </button>
                </div>

                {/* Appointments list */}
                {appointments.length > 0 ? (
                  <div>
                    <div style={{ padding: '10px 18px 6px', fontSize: 11, fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--text-3)' }}>
                      Upcoming · {appointments.length}
                    </div>
                    {appointments.map(appt => (
                      <div key={appt.id} style={{
                        display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, alignItems: 'center',
                        padding: '11px 18px', borderTop: '1px solid var(--border)',
                      }}>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>
                            {appt.service || 'Appointment'}
                            {appt.caller_name ? ` — ${appt.caller_name}` : ''}
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                            {formatApptDate(appt.appointment_datetime)}
                            {appt.caller_phone ? ` · ${appt.caller_phone}` : ''}
                          </div>
                        </div>
                        <span style={{
                          fontSize: 10, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase',
                          color: 'var(--accent)', background: 'var(--accent-dim)',
                          padding: '3px 8px', borderRadius: 4,
                        }}>
                          {appt.status || 'confirmed'}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ padding: '18px', fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>
                    No upcoming appointments yet. Share your number and let your AI start booking.
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div className="db-section-title">Lead Queue</div>
          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>Auto-refreshes every 30s</div>
        </div>

        {leads.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📞</div>
            <div className="empty-state-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
              No calls yet — share your number to get started
            </div>
            {tenant?.twilio_phone_number && (
              <div className="empty-state-sub" style={{ marginTop: 8 }}>
                Your number: <strong style={{ fontFamily: 'monospace' }}>{tenant.twilio_phone_number}</strong>
              </div>
            )}
          </div>
        ) : (
          <div className="leads-table">
            {leads.map(lead => {
              const detail        = detailMap[lead.id]
              const currentStatus = statusMap[lead.id] ?? lead.status
              const keyDetails    = detail?.metadata?.key_details ?? {}
              const nextStep      = detail?.metadata?.suggested_next_step
              const validCalls    = detail ? getValidCalls(detail.calls) : []

              return (
                <div key={lead.id} className="lead-row" onClick={() => toggleExpand(lead.id)}>
                  <div className="lead-row-main">
                    {/* Col 1: Avatar + Name + Phone */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div className="av">{initials(lead.name, lead.phone)}</div>
                      <div>
                        <div className="lead-name">{lead.name ?? 'Unknown'}</div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span className="lead-phone">{lead.phone ?? '—'}</span>
                          {lead.phone && (
                            <button
                              className="copy-btn"
                              onClick={(e) => copyLeadPhone(e, lead.phone!, lead.id)}
                            >
                              {copiedPhone === lead.id ? '✓' : 'Copy'}
                            </button>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Col 2: Status */}
                    <div>
                      <span className={`pill ${statusClass(currentStatus)}`}>
                        {currentStatus
                          ? currentStatus.charAt(0).toUpperCase() + currentStatus.slice(1)
                          : 'New'}
                      </span>
                    </div>

                    {/* Col 3: Urgency */}
                    <div>
                      {lead.urgency && (
                        <span className={`pill ${urgencyClass(lead.urgency)}`}>
                          {lead.urgency.charAt(0).toUpperCase() + lead.urgency.slice(1)}
                        </span>
                      )}
                    </div>

                    {/* Col 4: Summary */}
                    <div className="lead-summary">{lead.summary ?? '—'}</div>

                    {/* Col 5: Time */}
                    <div className="lead-time">{timeAgo(lead.created_at)}</div>
                  </div>

                  <AnimatePresence>
                    {expandedId === lead.id && (
                      <motion.div className="lead-transcript"
                        initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }}>

                        {/* Key details */}
                        {Object.keys(keyDetails).length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                            {Object.entries(keyDetails).map(([k, v]) => (
                              <div key={k} style={{
                                background: 'var(--bg-3)', border: '1px solid var(--border)',
                                borderRadius: 8, padding: '7px 12px', minWidth: 80,
                              }}>
                                <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 3 }}>
                                  {k.replace(/_/g, ' ')}
                                </div>
                                <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>
                                  {String(v)}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Suggested next step */}
                        {nextStep && (
                          <div style={{
                            fontSize: 12, color: 'var(--text-2)', background: 'var(--accent-dim)',
                            borderLeft: '2px solid var(--accent)', padding: '8px 12px',
                            borderRadius: '0 6px 6px 0', marginBottom: 14, lineHeight: 1.5,
                          }}>
                            <span style={{ color: 'var(--accent)', marginRight: 6 }}>➡</span>
                            {nextStep}
                          </div>
                        )}

                        {/* Status actions */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, paddingBottom: 14, borderBottom: '1px solid var(--border)' }}>
                          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Mark as:</span>
                          {(['contacted', 'booked'] as const).map(s => (
                            <button
                              key={s}
                              onClick={(e) => updateStatus(lead.id, s, e)}
                              style={{
                                padding: '4px 12px',
                                border: `1px solid ${currentStatus === s ? 'var(--accent)' : 'var(--border-2)'}`,
                                borderRadius: 4, fontSize: 11, fontWeight: 500,
                                background: currentStatus === s ? 'var(--accent-dim)' : 'transparent',
                                color: currentStatus === s ? 'var(--accent)' : 'var(--text-2)',
                                cursor: 'pointer', transition: 'all 0.2s',
                              }}
                            >
                              {s.charAt(0).toUpperCase() + s.slice(1)}
                            </button>
                          ))}
                        </div>

                        {/* Call history */}
                        {!detail ? (
                          <div className="transcript-empty">Loading…</div>
                        ) : validCalls.length === 0 ? (
                          <div className="transcript-empty">No call transcripts yet.</div>
                        ) : (
                          <div>
                            <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 10 }}>
                              Call History · {validCalls.length} {validCalls.length === 1 ? 'call' : 'calls'}
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                              {validCalls.map(call => (
                                <div key={call.id} style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                                  {/* Call header row */}
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      setExpandedCallId(expandedCallId === call.id ? null : call.id)
                                    }}
                                    style={{
                                      width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                                      padding: '10px 14px', background: expandedCallId === call.id ? 'var(--bg-3)' : 'var(--bg)',
                                      border: 'none', cursor: 'pointer', textAlign: 'left',
                                      transition: 'background 0.15s',
                                    }}
                                  >
                                    <span style={{ fontSize: 10, color: 'var(--text-3)', flexShrink: 0 }}>
                                      {expandedCallId === call.id ? '▾' : '▸'}
                                    </span>
                                    <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text)', flex: 1 }}>
                                      {formatCallDate(call.created_at)}
                                    </span>
                                    {call.duration_secs != null && (
                                      <span style={{ fontSize: 11, color: 'var(--text-3)', flexShrink: 0 }}>
                                        {formatDuration(call.duration_secs)}
                                      </span>
                                    )}
                                  </button>

                                  {/* Transcript body */}
                                  <AnimatePresence>
                                    {expandedCallId === call.id && (
                                      <motion.div
                                        initial={{ height: 0, opacity: 0 }}
                                        animate={{ height: 'auto', opacity: 1 }}
                                        exit={{ height: 0, opacity: 0 }}
                                        transition={{ duration: 0.18 }}
                                        style={{ overflow: 'hidden' }}
                                      >
                                        <div style={{
                                          padding: '12px 14px', borderTop: '1px solid var(--border)',
                                          background: 'var(--bg-2)', maxHeight: 320, overflowY: 'auto',
                                        }}>
                                          <TranscriptLines text={call.transcript ?? ''} />
                                        </div>
                                      </motion.div>
                                    )}
                                  </AnimatePresence>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Knowledge Base drawer */}
      <AnimatePresence>
        {kbOpen && (
          <KnowledgeDrawer
            tenantId={tenantId}
            websiteUrl={tenant?.website_url}
            lastCrawlAt={tenant?.last_crawl_at}
            onClose={() => setKbOpen(false)}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

export default function DashboardPageWrapper() {
  return (
    <Suspense fallback={
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
        <div style={{ fontSize: 13, color: 'var(--text-3)' }}>Loading…</div>
      </div>
    }>
      <DashboardPage />
    </Suspense>
  )
}
