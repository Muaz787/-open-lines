'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { PaymentForm } from './PaymentForm'
import { timeAgo, formatCallDate, formatApptDate, formatDuration, initials, capitalize } from './lib/format'
import { urgBadgeClass } from './lib/badges'
import { TranscriptLines } from './components/TranscriptLines'
import { Toast } from './components/Toast'
import { LoadingState, EmptyState } from './components/PageStates'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface Lead {
  id: string
  name?: string
  phone?: string
  summary?: string
  urgency?: string
  status?: string
  created_at: string
  updated_at?: string
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

/* Inline sparkline SVG */
function Sparkline({ value, active }: { value: number; active: boolean }) {
  const pts = value > 0
    ? '0,22 20,22 40,20 60,15 80,10 100,7'
    : '0,22 20,22 40,22 60,22 80,22 100,22'
  return (
    <svg className="db-sparkline" viewBox="0 0 100 28" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={active ? 'var(--db-accent)' : 'var(--db-border)'} strokeWidth="1.5" strokeLinejoin="round"/>
    </svg>
  )
}

/* Logo SVG — exact copy of landing page brand mark, white on green */
function DashboardPage() {
  const { tenantId }  = useParams<{ tenantId: string }>()
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

  const [payingPlan, setPayingPlan]         = useState<{ id: string; label: string; price: string } | null>(null)

  const [calStatus, setCalStatus]           = useState<CalendarStatus | null>(null)
  const [appointments, setAppointments]     = useState<Appointment[]>([])
  const [calToast, setCalToast]             = useState<string | null>(null)
  const [calDisconnecting, setCalDisconnecting] = useState(false)
  const [durSaving, setDurSaving]           = useState(false)
  const [period, setPeriod]                 = useState<'today' | '7d' | '30d'>('7d')

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

  const isSubscribed = tenant?.subscription_status === 'active' || tenant?.subscription_status === 'canceling'

  // ── Loading ───────────────────────────────────────────────
  if (loading) {
    return <LoadingState />
  }

  // ── Render ───────────────────────────────────────────────
  return (
    <>
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
        <Toast message={calToast} />

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
                        {noData ? <span style={{ color: 'var(--db-faint)' }}>—</span> : value.toLocaleString()}
                        {unit && !noData && <span className="db-stat-unit"> {unit}</span>}
                      </div>
                      <Sparkline value={noData ? 0 : value} active={value > 0 && !noData} />
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
                      <div style={{ padding: '11px 14px', borderBottom: '1px solid var(--db-border-lt)', fontSize: 12, color: 'var(--db-muted)' }}>
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
                            className="db-plan-mini"
                            onClick={() => handlePlanClick({ id: plan.id, label: plan.label, price: plan.price })}
                          >
                            <div className="db-plan-mini-name">{plan.label}</div>
                            <div className="db-plan-mini-sub">{plan.price} · {plan.minutes}</div>
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
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)' }}>
                        {tenant?.subscription_plan
                          ? `${capitalize(tenant.subscription_plan)} Plan`
                          : 'Active Plan'}
                      </span>
                      {tenant?.subscription_status === 'active' && (
                        <span className="db-badge db-badge--success">Active</span>
                      )}
                      {tenant?.subscription_status === 'canceling' && (
                        <span className="db-badge db-badge--warn">Canceling</span>
                      )}
                      {tenant?.subscription_status === 'past_due' && (
                        <span className="db-badge db-badge--danger">Past due</span>
                      )}
                    </div>
                    <Link
                      href={`/dashboard/${tenantId}/subscription`}
                      className="db-btn db-btn--accent-ghost db-btn--sm"
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
                <EmptyState
                  icon={
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>
                    </svg>
                  }
                  title="No leads yet."
                  sub={tenant?.twilio_phone_number ? `Share ${tenant.twilio_phone_number} to get your first call.` : undefined}
                />
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
                          {lead.urgency ? capitalize(lead.urgency) : 'New'}
                        </span>
                        <span className="db-lead-time">{timeAgo(lead.updated_at || lead.created_at)}</span>
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
                                  {capitalize(s)}
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
                                <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--db-muted)', marginBottom: 10 }}>
                                  Call History · {validCalls.length} {validCalls.length === 1 ? 'call' : 'calls'}
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                  {validCalls.map(call => (
                                    <div key={call.id} className="db-call-acc">
                                      <button
                                        className={`db-call-acc-btn${expandedCallId === call.id ? ' open' : ''}`}
                                        onClick={(e) => {
                                          e.stopPropagation()
                                          setExpandedCallId(expandedCallId === call.id ? null : call.id)
                                        }}
                                      >
                                        <span className="db-call-acc-caret">
                                          {expandedCallId === call.id ? '▾' : '▸'}
                                        </span>
                                        <span className="db-call-acc-date">
                                          {formatCallDate(call.created_at)}
                                        </span>
                                        {call.duration_secs != null && (
                                          <span className="db-call-acc-dur">
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
                                            <div className="db-call-acc-body">
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
                      <span style={{ fontSize: 11, color: 'var(--db-accent-text)', fontWeight: 500 }}>✓ Connected</span>
                    )}
                  </div>

                  {!calStatus?.connected ? (
                    <div style={{ padding: '14px', textAlign: 'center' }}>
                      <div style={{ fontSize: 12, color: 'var(--db-muted)', marginBottom: 10, lineHeight: 1.5 }}>
                        Connect Google Calendar to book appointments in real time.
                      </div>
                      <a
                        href={`${API}/calendar/connect/${tenantId}`}
                        className="db-btn db-btn--dark"
                      >
                        Connect Calendar
                      </a>
                    </div>
                  ) : appointments.length === 0 ? (
                    <div style={{ padding: '14px', fontSize: 12, color: 'var(--db-faint)', textAlign: 'center' }}>
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
                        <div style={{ padding: '8px 14px', borderTop: '1px solid var(--db-border-lt)', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontSize: 11, color: 'var(--db-muted)' }}>Duration:</span>
                            <select
                              className="db-select"
                              value={calStatus.appointment_duration_minutes}
                              onChange={e => saveDuration(Number(e.target.value))}
                              disabled={durSaving}
                              style={{ fontSize: 11, padding: '3px 6px' }}
                            >
                              {DURATION_OPTIONS.map(d => <option key={d} value={d}>{d} min</option>)}
                            </select>
                          </div>
                          <button
                            onClick={disconnectCalendar}
                            disabled={calDisconnecting}
                            style={{ fontSize: 11, color: 'var(--db-faint)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', marginLeft: 'auto', fontFamily: 'var(--font-dm), sans-serif' }}
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
                      className="db-btn db-btn--ghost db-btn--sm"
                      onClick={fetchInsights}
                      disabled={insightsLoading}
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
                      className="db-btn db-btn--dark"
                      onClick={fetchInsights}
                    >
                      ✦ Generate insights
                    </button>
                  </div>
                ) : insightsLoading && !insights?.insights.length ? (
                  <div style={{ padding: '18px 14px', fontSize: 12, color: 'var(--db-muted)', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>◌</span>
                    Analyzing calls and leads…
                  </div>
                ) : insights?.insights.length === 0 ? (
                  <div style={{ padding: '14px', fontSize: 12, color: 'var(--db-faint)' }}>
                    Not enough data yet — insights appear after a few calls.
                  </div>
                ) : (
                  <div>
                    {(insights?.insights ?? []).map((ins, i) => {
                      const typeColors: Record<string, { bg: string; dot: string }> = {
                        opportunity: { bg: 'var(--db-accent-bg)', dot: 'var(--db-accent-text)' },
                        success:     { bg: 'var(--db-accent-bg)', dot: 'var(--db-accent-text)' },
                        warning:     { bg: 'var(--db-warn-bg)', dot: 'var(--db-warn-text)' },
                        trend:       { bg: 'var(--db-info-bg)', dot: 'var(--db-info)' },
                      }
                      const colors = typeColors[ins.type] ?? typeColors.trend
                      return (
                        <div key={i} style={{ display: 'grid', gridTemplateColumns: '8px 1fr', gap: 12, padding: '12px 14px', borderTop: i > 0 ? '1px solid var(--db-border-lt)' : 'none', alignItems: 'start' }}>
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: colors.dot, marginTop: 4 }} />
                          <div>
                            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text)', marginBottom: 3 }}>
                              {ins.title}
                              <span style={{ marginLeft: 7, fontSize: 9, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', background: colors.bg, color: colors.dot, padding: '1px 6px', borderRadius: 4 }}>
                                {ins.type}
                              </span>
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--db-text-2)', lineHeight: 1.6 }}>{ins.body}</div>
                          </div>
                        </div>
                      )
                    })}
                    {insights?.generated_at && (
                      <div style={{ padding: '8px 14px', fontSize: 11, color: 'var(--db-faint)', borderTop: '1px solid var(--db-border-lt)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                        <span>Generated {timeAgo(insights.generated_at)}</span>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button onClick={copyInsights} style={{ fontSize: 10, color: insightsCopied ? 'var(--db-accent-text)' : 'var(--db-faint)', background: 'none', border: '1px solid var(--db-border)', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontFamily: 'var(--font-dm), sans-serif', transition: 'color 0.2s' }}>
                            {insightsCopied ? '✓ Copied' : 'Copy'}
                          </button>
                          <button onClick={downloadInsightsPDF} style={{ fontSize: 10, color: 'var(--db-faint)', background: 'none', border: '1px solid var(--db-border)', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontFamily: 'var(--font-dm), sans-serif' }}>
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
    </>
  )
}

export default function DashboardPageWrapper() {
  return (
    <Suspense fallback={<LoadingState />}>
      <DashboardPage />
    </Suspense>
  )
}
