'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { PaymentForm } from './PaymentForm'

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
  subscription_plan?: string
  subscription_status?: string
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

function formatApptDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-CA', {
    weekday: 'short', month: 'short', day: 'numeric',
  }) + ' · ' + d.toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit', hour12: true })
}

/* Inline sparkline SVG */
function Sparkline({ value, color = '#e8e6e0' }: { value: number; color?: string }) {
  const pts = value > 0
    ? '0,22 20,22 40,20 60,15 80,10 100,7'
    : '0,22 20,22 40,22 60,22 80,22 100,22'
  return (
    <svg className="db-sparkline" viewBox="0 0 100 28" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round"/>
    </svg>
  )
}

/* Logo SVG — exact copy of landing page brand mark, white on green */
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
  const [insightsCopied, setInsightsCopied]   = useState(false)

  const [dbMenuOpen, setDbMenuOpen]         = useState(false)
  const [payingPlan, setPayingPlan]         = useState<{ id: string; label: string; price: string } | null>(null)

  const [calStatus, setCalStatus]           = useState<CalendarStatus | null>(null)
  const [appointments, setAppointments]     = useState<Appointment[]>([])
  const [calToast, setCalToast]             = useState<string | null>(null)
  const [calDisconnecting, setCalDisconnecting] = useState(false)
  const [durSaving, setDurSaving]           = useState(false)
  const [userEmail, setUserEmail]           = useState('')
  const [userName, setUserName]             = useState('')
  const [period, setPeriod]                 = useState<'today' | '7d' | '30d'>('7d')

  // Auth guard
  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) router.replace('/login')
      else {
        setUserEmail(data.user.email ?? '')
        setUserName(data.user.user_metadata?.full_name ?? '')
      }
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

  const copyInsights = () => {
    if (!insights) return
    const text = insights.insights
      .map(ins => `${ins.title} [${ins.type.toUpperCase()}]\n${ins.body}`)
      .join('\n\n')
    navigator.clipboard.writeText(text)
    setInsightsCopied(true)
    setTimeout(() => setInsightsCopied(false), 2000)
  }

  const downloadInsightsPDF = () => {
    if (!insights) return
    const typeColors: Record<string, string> = {
      opportunity: '#16a34a', success: '#16a34a', warning: '#d97706', trend: '#3B7EF6',
    }
    const rows = insights.insights.map(ins => `
      <div style="margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid #e5e7eb;">
        <div style="font-size:14px;font-weight:700;color:#111;margin-bottom:6px;">
          ${ins.title}
          <span style="margin-left:8px;font-size:10px;font-weight:700;text-transform:uppercase;
            letter-spacing:0.06em;color:${typeColors[ins.type] ?? '#3B7EF6'};
            background:${typeColors[ins.type] ?? '#3B7EF6'}1a;padding:2px 7px;border-radius:4px;">
            ${ins.type}
          </span>
        </div>
        <div style="font-size:13px;color:#555;line-height:1.65;">${ins.body}</div>
      </div>`).join('')
    const generatedStr = insights.generated_at
      ? new Date(insights.generated_at).toLocaleString()
      : 'recently'
    const html = `<!DOCTYPE html><html><head><title>AI Insights — Open Lines</title>
      <style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        padding:48px 52px;color:#111;max-width:720px;margin:0 auto;}
        @media print{body{padding:32px;}}</style>
      </head><body>
      <div style="font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;
        color:#16a34a;margin-bottom:10px;">✦ AI Insights</div>
      <h1 style="font-size:22px;font-weight:700;margin:0 0 28px;">Call & Lead Analysis</h1>
      ${rows}
      <div style="font-size:11px;color:#999;margin-top:8px;">
        Generated ${generatedStr} · Open Lines AI
      </div></body></html>`
    const w = window.open('', '_blank')
    if (!w) return
    w.document.write(html)
    w.document.close()
    w.focus()
    setTimeout(() => { w.print() }, 250)
  }

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
    const interval = setInterval(() => {
      fetchLeads()
      fetch(`${API}/leads/${tenantId}/stats`).then(r => r.ok ? r.json() : null).then(d => d && setStats(d))
    }, 30_000)
    return () => clearInterval(interval)
  }, [tenantId, fetchLeads, fetchCalendar])

  useEffect(() => {
    const calParam     = searchParams.get('calendar')
    const billingParam = searchParams.get('billing')

    if (calParam === 'connected') {
      setCalToast('Google Calendar connected!')
      fetchCalendar()
      setTimeout(() => setCalToast(null), 4000)
    } else if (calParam === 'error') {
      setCalToast('Calendar connection failed. Please try again.')
      setTimeout(() => setCalToast(null), 5000)
    } else if (billingParam === 'success') {
      setCalToast('🎉 Subscription activated! Welcome to Open Lines.')
      setTimeout(() => setCalToast(null), 6000)
      const pollTenant = (attemptsLeft: number) => {
        fetch(`${API}/onboarding/status/${tenantId}`)
          .then(r => r.ok ? r.json() : null)
          .then(d => {
            if (!d) return
            setTenant(d)
            if (!d.subscription_status || d.subscription_status === 'none' || d.subscription_status === 'incomplete') {
              if (attemptsLeft > 0) setTimeout(() => pollTenant(attemptsLeft - 1), 2000)
            }
          })
      }
      pollTenant(5)
    } else if (billingParam === 'canceled') {
      setCalToast('Checkout canceled — no charge was made.')
      setTimeout(() => setCalToast(null), 4000)
    }
  }, [searchParams, fetchCalendar, tenantId])

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

  const handlePlanClick = (plan: { id: string; label: string; price: string }) => {
    if (tenant?.subscription_plan === plan.id && tenant?.subscription_status === 'active') return
    setPayingPlan(plan)
  }

  const handlePaymentSuccess = async () => {
    setPayingPlan(null)
    setCalToast('🎉 Subscription activated! Welcome to Open Lines.')
    setTimeout(() => setCalToast(null), 6000)
    try {
      const res = await fetch(`${API}/onboarding/status/${tenantId}`)
      if (res.ok) setTenant(await res.json())
    } catch {}
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

  // ── Derived ──────────────────────────────────────────────
  const isSubscribed = tenant?.subscription_status === 'active' || tenant?.subscription_status === 'canceling'


  // ── Loading ───────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f4f3f0' }}>
        <div style={{ fontSize: 13, color: '#888' }}>Loading…</div>
      </div>
    )
  }

  // ── Sidebar nav icons ────────────────────────────────────
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
  const IconSignOut = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <path d="M6 2H3a1 1 0 00-1 1v9a1 1 0 001 1h3"/>
      <path strokeLinecap="round" d="M10 10l3-3-3-3M13 7H6"/>
    </svg>
  )
  const IconLeads = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.35" width="14" height="14">
      <path d="M7.5 1.5l1.47 3.29 3.63.52-2.63 2.47.62 3.61L7.5 9.72 4.41 11.4l.62-3.61L2.4 5.31l3.63-.52z" strokeLinejoin="round"/>
    </svg>
  )
  const IconCalendar = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <rect x="1.5" y="2.5" width="12" height="11" rx="1.5"/>
      <path d="M1.5 6.5h12M5 1.5v2M10 1.5v2"/>
    </svg>
  )
  const IconCalls = () => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="14" height="14">
      <path d="M2 2.5h4l1.5 3.5-2 1.5a9 9 0 003 3l1.5-2 3.5 1.5V13a1 1 0 01-1 1C5.5 14 1 9.5 1 3.5a1 1 0 011-1z" strokeLinejoin="round"/>
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

  const planBadge = () => {
    if (tenant?.subscription_status === 'active' && tenant?.subscription_plan)
      return <span className="db-nav-badge db-badge-green">{tenant.subscription_plan}</span>
    if (!tenant?.subscription_status || tenant.subscription_status === 'none' || tenant.subscription_status === 'incomplete')
      return <span className="db-nav-badge db-badge-amber">Free</span>
    if (tenant.subscription_status === 'past_due')
      return <span className="db-nav-badge db-badge-red">Past due</span>
    return null
  }

  // ── Render ───────────────────────────────────────────────
  return (
    <div className="db-root">

      {/* ══ Sidebar ══ */}
      <aside className="db-sidebar">
        {/* Logo */}
        <div className="db-sidebar-logo">
          <div className="db-logo-icon"><LogoMark size={22} /></div>
          <span className="db-logo-name">open lines</span>
        </div>

        {/* Business switcher */}
        {tenant && (
          <div className="db-clinic-sw">
            <div className="db-clinic-name">{tenant.business_name}</div>
            <div className="db-clinic-tag">{tenant.industry} · Active</div>
          </div>
        )}

        {/* Nav */}
        <div className="db-sidebar-nav">
          <div className="db-nav-label">Main</div>

          <div className="db-nav-item active">
            <div className="db-nav-indicator" />
            <IconDashboard />
            Dashboard
          </div>

          <Link href={`/dashboard/${tenantId}/knowledge-base`} className="db-nav-item">
            <IconKB />
            Knowledge Base
          </Link>

          <Link href={`/dashboard/${tenantId}/leads`} className="db-nav-item">
            <IconLeads />
            Leads
            {leads.length > 0 && <span className="db-nav-badge db-badge-red">{leads.length}</span>}
          </Link>

          <Link href={`/dashboard/${tenantId}/calls`} className="db-nav-item">
            <IconCalls />
            Calls
          </Link>

          {tenant && BOOKING_INDUSTRIES.has(tenant.industry) && (
            <Link href={`/dashboard/${tenantId}/calendar`} className="db-nav-item">
              <IconCalendar />
              Calendar
              {appointments.length > 0 && <span className="db-nav-badge db-badge-green">{appointments.length}</span>}
            </Link>
          )}

          <div className="db-nav-label">Account</div>

          <Link href={`/dashboard/${tenantId}/settings`} className="db-nav-item">
            <IconSettings />
            Settings
          </Link>

          <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item">
            <IconSub />
            Subscription
            {planBadge()}
          </Link>

          <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item">
            <IconBilling />
            Billing &amp; Payments
          </Link>

          <Link href={`/dashboard/${tenantId}/usage`} className="db-nav-item">
            <IconUsage />
            Usage
          </Link>
        </div>

        {/* Upgrade pill */}
        {!isSubscribed && (
          <Link href={`/dashboard/${tenantId}/subscription`} className="db-upgrade-pill">
            <div className="db-upgrade-label">↑ Choose a plan</div>
            <div className="db-upgrade-sub">Start from $99/mo</div>
          </Link>
        )}

        {/* User footer */}
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
      </aside>

      {/* ══ Main ══ */}
      <div className="db-main">

        {/* Mobile topbar */}
        <div className="db-mobile-topbar">
          <div className="db-mobile-logo">
            <div className="db-logo-icon">
              <LogoMark size={22} />
            </div>
            <span className="db-mobile-logo-name">Open Lines</span>
          </div>
          <button
            className="db-hamburger"
            onClick={() => setDbMenuOpen(o => !o)}
            aria-label={dbMenuOpen ? 'Close menu' : 'Open menu'}
          >
            {dbMenuOpen ? (
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
          <span className="db-topbar-title">Dashboard</span>
          <div className="db-topbar-right">
            {tenant?.twilio_phone_number && (
              <button className="db-phone-chip" onClick={copyPhone}>
                <div className="db-live-dot" />
                {copied ? '✓ Copied' : tenant.twilio_phone_number}
              </button>
            )}
            <div className="db-period-tabs">
              {(['today', '7d', '30d'] as const).map(p => (
                <button
                  key={p}
                  className={`db-period-tab${period === p ? ' active' : ''}`}
                  onClick={() => setPeriod(p)}
                >
                  {p === 'today' ? 'Today' : p}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Toast */}
        <AnimatePresence>
          {calToast && (
            <motion.div
              initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
              style={{
                position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)',
                background: '#16161a', color: '#fff', padding: '10px 20px',
                borderRadius: 8, fontSize: 13, fontWeight: 500, zIndex: 300,
                boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
              }}
            >
              {calToast}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Content ── */}
        <div className="db-content">

          {/* Stats row — full width */}
          {stats && (
            <div className="db-stats-wrap">
              <div className="db-stats-topbar">
                <span className="db-stats-title">Performance</span>
              </div>
              <div className="db-stats-v2">
                {[
                  { label: 'Calls handled',       value: stats.total_calls,         unit: '' },
                  { label: 'Leads captured',       value: stats.total_leads,         unit: '' },
                  { label: 'Minutes on phone',     value: stats.minutes_handled,     unit: 'min' },
                  { label: 'Appointments booked',  value: stats.appointments_booked, unit: '' },
                ].map(({ label, value, unit }) => {
                  const noData = unit === 'min' && value === 0 && stats.total_calls > 0
                  const periodLabel = period === 'today' ? 'Today' : period === '7d' ? '7d' : '30d'
                  return (
                    <div key={label} className="db-stat-card">
                      <div className="db-stat-meta">
                        <span className="db-stat-label">{label}</span>
                        <span className={`db-stat-delta ${value > 0 && !noData ? 'db-delta-up' : 'db-delta-neu'}`}>
                          {noData ? '—' : value > 0 ? `↑ ${periodLabel}` : '—'}
                        </span>
                      </div>
                      <div className="db-stat-num">
                        {noData ? <span style={{ color: '#bbb' }}>—</span> : value.toLocaleString()}
                        {unit && !noData && <span className="db-stat-unit"> {unit}</span>}
                      </div>
                      <Sparkline value={noData ? 0 : value} color={value > 0 && !noData ? '#3dba72' : '#e8e6e0'} />
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ── Two-column layout ── */}
          <div className="db-two-col">

            {/* Left column: onboarding + subscription + leads */}
            <div className="db-left-col">


              {/* Subscription (if no active plan) */}
              {!isSubscribed && (
                <div className="db-sub-compact">
                  {payingPlan ? (
                    <PaymentForm
                      tenantId={tenantId}
                      plan={payingPlan.id}
                      planLabel={`${payingPlan.label} · ${payingPlan.price}`}
                      onSuccess={handlePaymentSuccess}
                      onCancel={() => setPayingPlan(null)}
                    />
                  ) : (
                    <>
                      <div style={{ padding: '11px 14px', borderBottom: '1px solid #f0ede8', fontSize: 12, color: '#888' }}>
                        No active plan — choose one to unlock full access.
                      </div>
                      <div style={{ padding: '12px 14px', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {([
                          { id: 'starter',  label: 'Starter',  price: '$99/mo',  minutes: '150 min' },
                          { id: 'pro',      label: 'Pro',       price: '$199/mo', minutes: '400 min' },
                          { id: 'business', label: 'Business',  price: '$379/mo', minutes: '900 min' },
                        ] as const).map(plan => (
                          <button
                            key={plan.id}
                            onClick={() => handlePlanClick({ id: plan.id, label: plan.label, price: plan.price })}
                            style={{
                              flex: 1, minWidth: 80, padding: '10px 12px', textAlign: 'left',
                              border: '1px solid #e8e6e0', borderRadius: 8,
                              background: '#fff', cursor: 'pointer', transition: 'border-color 0.15s',
                              fontFamily: 'var(--font-dm), sans-serif',
                            }}
                            onMouseEnter={e => (e.currentTarget.style.borderColor = '#3dba72')}
                            onMouseLeave={e => (e.currentTarget.style.borderColor = '#e8e6e0')}
                          >
                            <div style={{ fontSize: 12, fontWeight: 700, color: '#16161a', marginBottom: 2 }}>{plan.label}</div>
                            <div style={{ fontSize: 11, color: '#888' }}>{plan.price} · {plan.minutes}</div>
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* Subscription — active plan management link */}
              {(tenant?.subscription_status === 'active' || tenant?.subscription_status === 'canceling' || tenant?.subscription_status === 'past_due') && (
                <div className="db-sub-compact">
                  <div style={{ padding: '11px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#16161a' }}>
                        {tenant?.subscription_plan
                          ? `${tenant.subscription_plan.charAt(0).toUpperCase() + tenant.subscription_plan.slice(1)} Plan`
                          : 'Active Plan'}
                      </span>
                      {tenant?.subscription_status === 'active' && (
                        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: '#f0fdf4', color: '#16a34a', letterSpacing: '0.06em' }}>ACTIVE</span>
                      )}
                      {tenant?.subscription_status === 'canceling' && (
                        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: '#fffbeb', color: '#d97706', letterSpacing: '0.06em' }}>CANCELING</span>
                      )}
                      {tenant?.subscription_status === 'past_due' && (
                        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: '#fef2f2', color: '#ef4444', letterSpacing: '0.06em' }}>PAST DUE</span>
                      )}
                    </div>
                    <Link
                      href={`/dashboard/${tenantId}/subscription`}
                      style={{ fontSize: 12, fontWeight: 600, color: '#3dba72', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4, padding: '6px 12px', border: '1px solid #3dba72', borderRadius: 7, background: '#f0fdf4' }}
                    >
                      Manage →
                    </Link>
                  </div>
                </div>
              )}

              {/* Lead Queue */}
              <div className="db-section-card">
              <div className="db-section-hdr">
                <div className="db-section-title-row">
                  <div className="db-section-icon" style={{ background: '#fff5f0' }}>⚡</div>
                  <span className="db-section-name">Lead Queue</span>
                  <span className="db-section-hint">auto-refreshes 30s</span>
                </div>
              </div>

              {leads.length === 0 ? (
                <div className="db-empty-v2">
                  <div className="db-empty-v2-title">No leads yet.</div>
                  {tenant?.twilio_phone_number && (
                    <div className="db-empty-v2-sub">Share {tenant.twilio_phone_number} to get your first call.</div>
                  )}
                </div>
              ) : (
                leads.map(lead => {
                  const detail        = detailMap[lead.id]
                  const currentStatus = statusMap[lead.id] ?? lead.status
                  const keyDetails    = detail?.metadata?.key_details ?? {}
                  const nextStep      = detail?.metadata?.suggested_next_step
                  const validCalls    = detail ? getValidCalls(detail.calls) : []
                  const isExpanded    = expandedId === lead.id

                  return (
                    <div key={lead.id} className="db-lead-row" onClick={() => toggleExpand(lead.id)}>
                      <div className="db-lead-main">
                        <div className="db-lead-av">{initials(lead.name, lead.phone)}</div>
                        <div className="db-lead-info">
                          <div className="db-lead-name">
                            {lead.name ?? 'Unknown'}
                            {lead.phone && <span className="db-lead-phone-inline"> · {lead.phone}</span>}
                          </div>
                          <div className="db-lead-sum">{lead.summary ?? 'No summary yet'}</div>
                        </div>
                        <span className={urgBadgeClass(lead.urgency)}>
                          {lead.urgency
                            ? lead.urgency.charAt(0).toUpperCase() + lead.urgency.slice(1)
                            : 'New'}
                        </span>
                        <span className="db-lead-time">{timeAgo(lead.created_at)}</span>
                        <div className="db-lead-actions" onClick={e => e.stopPropagation()}>
                          {lead.phone && (
                            <button
                              className="db-lead-btn"
                              onClick={(e) => copyLeadPhone(e, lead.phone!, lead.id)}
                            >
                              {copiedPhone === lead.id ? '✓' : 'Copy #'}
                            </button>
                          )}
                        </div>
                      </div>

                      <AnimatePresence>
                        {isExpanded && (
                          <motion.div
                            className="db-lead-expanded"
                            initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }}
                            style={{ overflow: 'hidden' }}
                          >
                            {/* Status stepper */}
                            <div className="status-stepper" style={{ marginBottom: 14 }}>
                              {(['new', 'contacted', 'booked'] as const).map(s => (
                                <button
                                  key={s}
                                  className={`step-btn${(currentStatus ?? 'new') === s ? ' step-active' : ''}`}
                                  onClick={(e) => updateStatus(lead.id, s, e)}
                                >
                                  {s.charAt(0).toUpperCase() + s.slice(1)}
                                </button>
                              ))}
                            </div>

                            {/* Key details */}
                            {Object.keys(keyDetails).length > 0 && (
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                                {Object.entries(keyDetails).map(([k, v]) => (
                                  <div key={k} className="kd-chip">
                                    <div className="kd-label">{k.replace(/_/g, ' ')}</div>
                                    <div className="kd-value">{String(v)}</div>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* Next step */}
                            {nextStep && (
                              <div className="next-step-box" style={{ marginBottom: 14 }}>
                                <span className="next-step-arrow">➡ </span>{nextStep}
                              </div>
                            )}

                            {/* Call history */}
                            {!detail ? (
                              <div className="transcript-empty">Loading…</div>
                            ) : validCalls.length === 0 ? (
                              <div className="transcript-empty">No call transcripts yet.</div>
                            ) : (
                              <div>
                                <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#888', marginBottom: 10 }}>
                                  Call History · {validCalls.length} {validCalls.length === 1 ? 'call' : 'calls'}
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                  {validCalls.map(call => (
                                    <div key={call.id} style={{ border: '1px solid #e8e6e0', borderRadius: 8, overflow: 'hidden' }}>
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation()
                                          setExpandedCallId(expandedCallId === call.id ? null : call.id)
                                        }}
                                        style={{
                                          width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                                          padding: '10px 14px',
                                          background: expandedCallId === call.id ? '#f8f7f4' : '#fff',
                                          border: 'none', cursor: 'pointer', textAlign: 'left',
                                          fontFamily: 'var(--font-dm), sans-serif',
                                          transition: 'background 0.15s',
                                        }}
                                      >
                                        <span style={{ fontSize: 10, color: '#888', flexShrink: 0 }}>
                                          {expandedCallId === call.id ? '▾' : '▸'}
                                        </span>
                                        <span style={{ fontSize: 12, fontWeight: 500, color: '#16161a', flex: 1 }}>
                                          {formatCallDate(call.created_at)}
                                        </span>
                                        {call.duration_secs != null && (
                                          <span style={{ fontSize: 11, color: '#888', flexShrink: 0 }}>
                                            {formatDuration(call.duration_secs)}
                                          </span>
                                        )}
                                      </button>
                                      <AnimatePresence>
                                        {expandedCallId === call.id && (
                                          <motion.div
                                            initial={{ height: 0, opacity: 0 }}
                                            animate={{ height: 'auto', opacity: 1 }}
                                            exit={{ height: 0, opacity: 0 }}
                                            transition={{ duration: 0.18 }}
                                            style={{ overflow: 'hidden' }}
                                          >
                                            <div style={{ padding: '12px 14px', borderTop: '1px solid #e8e6e0', background: '#fafaf8', maxHeight: 320, overflowY: 'auto' }}>
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
                })
              )}
            </div>

            </div>{/* /db-left-col */}

            {/* ── Right column ── */}
            <div className="db-right-col">

              {/* Calendar */}
              {tenant && BOOKING_INDUSTRIES.has(tenant.industry) && (
                <div className="db-section-card">
                  <div className="db-section-hdr">
                    <div className="db-section-title-row">
                      <div className="db-section-icon" style={{ background: '#f0fdf4' }}>📅</div>
                      <span className="db-section-name">Upcoming</span>
                    </div>
                    {calStatus?.connected && (
                      <span style={{ fontSize: 11, color: '#3dba72', fontWeight: 500 }}>✓ Connected</span>
                    )}
                  </div>

                  {!calStatus?.connected ? (
                    <div style={{ padding: '14px', textAlign: 'center' }}>
                      <div style={{ fontSize: 12, color: '#888', marginBottom: 10, lineHeight: 1.5 }}>
                        Connect Google Calendar to book appointments in real time.
                      </div>
                      <a
                        href={`${API}/calendar/connect/${tenantId}`}
                        style={{
                          display: 'inline-flex', alignItems: 'center', gap: 7,
                          background: '#16161a', color: '#fff',
                          borderRadius: 8, padding: '9px 16px',
                          fontSize: 12, fontWeight: 500, textDecoration: 'none',
                          transition: 'opacity 0.2s',
                        }}
                      >
                        Connect Calendar
                      </a>
                    </div>
                  ) : appointments.length === 0 ? (
                    <div style={{ padding: '14px', fontSize: 12, color: '#bbb', textAlign: 'center' }}>
                      No upcoming appointments.
                    </div>
                  ) : (
                    <>
                      {appointments.slice(0, 3).map(appt => (
                        <div key={appt.id} className="db-cal-event">
                          <div className="db-cal-dot" />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div className="db-cal-name">
                              {appt.service || 'Appointment'}
                              {appt.caller_name ? ` — ${appt.caller_name}` : ''}
                            </div>
                            <div className="db-cal-time">{formatApptDate(appt.appointment_datetime)}</div>
                          </div>
                          <span className="db-cal-badge">{appt.status || 'confirmed'}</span>
                        </div>
                      ))}
                      {calStatus?.connected && (
                        <div style={{ padding: '8px 14px', borderTop: '1px solid #f0ede8', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontSize: 11, color: '#888' }}>Duration:</span>
                            <select
                              value={calStatus.appointment_duration_minutes}
                              onChange={e => saveDuration(Number(e.target.value))}
                              disabled={durSaving}
                              style={{ fontSize: 11, background: '#fff', border: '1px solid #e8e6e0', borderRadius: 5, padding: '3px 6px', color: '#16161a', cursor: 'pointer', fontFamily: 'var(--font-dm), sans-serif' }}
                            >
                              {DURATION_OPTIONS.map(d => <option key={d} value={d}>{d} min</option>)}
                            </select>
                          </div>
                          <button
                            onClick={disconnectCalendar}
                            disabled={calDisconnecting}
                            style={{ fontSize: 11, color: '#bbb', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', marginLeft: 'auto', fontFamily: 'var(--font-dm), sans-serif' }}
                          >
                            {calDisconnecting ? 'Disconnecting…' : 'Disconnect'}
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* AI Insights */}
              <div className="db-section-card">
                <div className="db-section-hdr">
                  <div className="db-section-title-row">
                    <div className="db-section-icon" style={{ background: '#f5f0fe' }}>✦</div>
                    <span className="db-section-name">AI Insights</span>
                  </div>
                  {insights && (
                    <button
                      onClick={fetchInsights}
                      disabled={insightsLoading}
                      style={{ fontSize: 11, color: '#888', background: 'none', border: '1px solid #e8e6e0', borderRadius: 5, padding: '3px 9px', cursor: insightsLoading ? 'default' : 'pointer', opacity: insightsLoading ? 0.5 : 1, fontFamily: 'var(--font-dm), sans-serif' }}
                    >
                      {insightsLoading ? 'Thinking…' : 'Refresh'}
                    </button>
                  )}
                </div>

                {!insights && !insightsLoading ? (
                  <div className="db-insight-teaser">
                    <div className="db-insight-blur">
                      <div className="db-insight-line" style={{ width: '80%' }} />
                      <div className="db-insight-line" style={{ width: '60%' }} />
                      <div className="db-insight-line" style={{ width: '70%' }} />
                    </div>
                    <div className="db-insight-copy">After 5+ calls, your AI surfaces caller intent patterns, opportunities, and peak hours.</div>
                    <button
                      onClick={fetchInsights}
                      style={{ background: '#16161a', color: '#fff', border: 'none', borderRadius: 7, padding: '8px 14px', fontSize: 12, fontWeight: 500, cursor: 'pointer', fontFamily: 'var(--font-dm), sans-serif' }}
                    >
                      ✦ Generate insights
                    </button>
                  </div>
                ) : insightsLoading && !insights?.insights.length ? (
                  <div style={{ padding: '18px 14px', fontSize: 12, color: '#888', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>◌</span>
                    Analyzing calls and leads…
                  </div>
                ) : insights?.insights.length === 0 ? (
                  <div style={{ padding: '14px', fontSize: 12, color: '#bbb' }}>
                    Not enough data yet — insights appear after a few calls.
                  </div>
                ) : (
                  <div>
                    {(insights?.insights ?? []).map((ins, i) => {
                      const typeColors: Record<string, { bg: string; dot: string }> = {
                        opportunity: { bg: '#f0fdf4', dot: '#16a34a' },
                        success:     { bg: '#f0fdf4', dot: '#16a34a' },
                        warning:     { bg: '#fffbeb', dot: '#d97706' },
                        trend:       { bg: '#f0f4ff', dot: '#4f6ef7' },
                      }
                      const colors = typeColors[ins.type] ?? typeColors.trend
                      return (
                        <div key={i} style={{ display: 'grid', gridTemplateColumns: '8px 1fr', gap: 12, padding: '12px 14px', borderTop: i > 0 ? '1px solid #f0ede8' : 'none', alignItems: 'start' }}>
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: colors.dot, marginTop: 4 }} />
                          <div>
                            <div style={{ fontSize: 12, fontWeight: 600, color: '#16161a', marginBottom: 3 }}>
                              {ins.title}
                              <span style={{ marginLeft: 7, fontSize: 9, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', background: colors.bg, color: colors.dot, padding: '1px 6px', borderRadius: 4 }}>
                                {ins.type}
                              </span>
                            </div>
                            <div style={{ fontSize: 11, color: '#555', lineHeight: 1.6 }}>{ins.body}</div>
                          </div>
                        </div>
                      )
                    })}
                    {insights?.generated_at && (
                      <div style={{ padding: '8px 14px', fontSize: 11, color: '#bbb', borderTop: '1px solid #f0ede8', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                        <span>Generated {timeAgo(insights.generated_at)}</span>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button onClick={copyInsights} style={{ fontSize: 10, color: insightsCopied ? '#3dba72' : '#bbb', background: 'none', border: '1px solid #e8e6e0', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontFamily: 'var(--font-dm), sans-serif', transition: 'color 0.2s' }}>
                            {insightsCopied ? '✓ Copied' : 'Copy'}
                          </button>
                          <button onClick={downloadInsightsPDF} style={{ fontSize: 10, color: '#bbb', background: 'none', border: '1px solid #e8e6e0', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontFamily: 'var(--font-dm), sans-serif' }}>
                            PDF
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

            </div>
          </div>
        </div>
      </div>

      {/* ── Mobile overlay menu ── */}
      <AnimatePresence>
        {dbMenuOpen && (
          <motion.div
            className="db-overlay-menu"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={() => setDbMenuOpen(false)}
          >
            <motion.div
              className="db-overlay-panel"
              initial={{ x: -260 }} animate={{ x: 0 }} exit={{ x: -260 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              onClick={e => e.stopPropagation()}
            >
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
                <div className="db-nav-item active" onClick={() => setDbMenuOpen(false)}>
                  <div className="db-nav-indicator" />
                  <IconDashboard />
                  Dashboard
                </div>
                <Link href={`/dashboard/${tenantId}/knowledge-base`} className="db-nav-item" onClick={() => setDbMenuOpen(false)}>
                  <IconKB />
                  Knowledge Base
                </Link>
                <Link href={`/dashboard/${tenantId}/leads`} className="db-nav-item" onClick={() => setDbMenuOpen(false)}>
                  <IconLeads />
                  Leads
                  {leads.length > 0 && <span className="db-nav-badge db-badge-red">{leads.length}</span>}
                </Link>
                <Link href={`/dashboard/${tenantId}/calls`} className="db-nav-item" onClick={() => setDbMenuOpen(false)}>
                  <IconCalls />
                  Calls
                </Link>
                {tenant && BOOKING_INDUSTRIES.has(tenant.industry) && (
                  <Link href={`/dashboard/${tenantId}/calendar`} className="db-nav-item" onClick={() => setDbMenuOpen(false)}>
                    <IconCalendar />
                    Calendar
                    {appointments.length > 0 && <span className="db-nav-badge db-badge-green">{appointments.length}</span>}
                  </Link>
                )}
                <div className="db-nav-label">Account</div>
                <Link href={`/dashboard/${tenantId}/settings`} className="db-nav-item" onClick={() => setDbMenuOpen(false)}>
                  <IconSettings />
                  Settings
                </Link>
                <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item" onClick={() => setDbMenuOpen(false)}>
                  <IconSub />
                  Subscription
                  {planBadge()}
                </Link>
                <Link href={`/dashboard/${tenantId}/subscription`} className="db-nav-item" onClick={() => setDbMenuOpen(false)}>
                  <IconBilling />
                  Billing &amp; Payments
                </Link>
                <Link href={`/dashboard/${tenantId}/usage`} className="db-nav-item" onClick={() => setDbMenuOpen(false)}>
                  <IconUsage />
                  Usage
                </Link>
                <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 8 }}>
                  <button className="db-nav-item" onClick={handleLogout} style={{ color: '#f87171' }}>
                    <IconSignOut />
                    Sign out
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  )
}

export default function DashboardPageWrapper() {
  return (
    <Suspense fallback={
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f4f3f0' }}>
        <div style={{ fontSize: 13, color: '#888' }}>Loading…</div>
      </div>
    }>
      <DashboardPage />
    </Suspense>
  )
}
