'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

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

export default function CallsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [calls, setCalls]             = useState<CallRow[]>([])
  const [analytics, setAnalytics]     = useState<Analytics | null>(null)
  const [loading, setLoading]         = useState(true)
  const [period, setPeriod]           = useState<Period>('30')
  const [urgFilter, setUrgFilter]     = useState<UrgencyFilter>('all')
  const [expandedId, setExpandedId]   = useState<string | null>(null)
  const [detailMap, setDetailMap]     = useState<Record<string, CallDetail>>({})
  const [detailLoading, setDetailLoading] = useState<string | null>(null)

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

  const filtered = urgFilter === 'all'
    ? calls
    : calls.filter(c => (c.leads?.urgency ?? 'unknown').toLowerCase() === urgFilter)

  const hotPct = analytics && analytics.total_calls > 0
    ? Math.round((analytics.urgency_breakdown.hot / analytics.total_calls) * 100)
    : 0

  return (
    <>

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
    </>
  )
}
