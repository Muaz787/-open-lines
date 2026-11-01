'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { formatCallDate, formatDuration, initials, capitalize } from '../lib/format'
import { urgBadgeClass, dispositionBadgeClass, dispositionLabel } from '../lib/badges'
import { TranscriptLines } from '../components/TranscriptLines'
import { LoadingState, EmptyState, ErrorState } from '../components/PageStates'
import { emptyCallsCopy, type CallPeriod, type CallQuality } from '../lib/emptyStates'
import { useQueryParam } from '../lib/useQueryParam'
import { disclosureProps } from '../lib/disclosure'
import { usePathname, useRouter } from 'next/navigation'

import { authedFetch, peekJson } from '@/lib/api'
import { Phone } from 'lucide-react'
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
  disposition?: string
  transferred?: boolean
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

type UrgencyFilter = CallQuality
type Period = CallPeriod

const CALL_PERIODS = ['7', '30', '0'] as const
const CALL_QUALITIES = ['all', 'hot', 'warm', 'cold'] as const

export default function CallsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const router   = useRouter()
  const pathname = usePathname()
  const [period, setPeriod]       = useQueryParam<Period>('period', CALL_PERIODS, '30')
  const [urgFilter, setUrgFilter] = useQueryParam<UrgencyFilter>('quality', CALL_QUALITIES, 'all')
  const callsUrl     = `${API}/calls/${tenantId}?days=${period}`
  const analyticsUrl = `${API}/calls/${tenantId}/analytics?days=${period}`
  // A tab shown before paints its last data at once; fetchData then refreshes it.
  const [calls, setCalls]             = useState<CallRow[]>(() => peekJson<CallRow[]>(callsUrl) ?? [])
  const [analytics, setAnalytics]     = useState<Analytics | null>(() => peekJson<Analytics>(analyticsUrl) ?? null)
  const [loading, setLoading]         = useState(() => peekJson(callsUrl) === undefined)
  const [failed, setFailed]           = useState(false)
  const [expandedId, setExpandedId]   = useState<string | null>(null)
  const [detailMap, setDetailMap]     = useState<Record<string, CallDetail>>({})
  const [detailLoading, setDetailLoading] = useState<string | null>(null)

  const latestRequest = useRef(0)

  const fetchData = useCallback(async () => {
    // Switching to a period already seen shows its last data, not a spinner.
    const cachedCalls = peekJson<CallRow[]>(callsUrl)
    const cachedAnalytics = peekJson<Analytics>(analyticsUrl)
    if (cachedCalls && cachedAnalytics) { setCalls(cachedCalls); setAnalytics(cachedAnalytics) }
    else setLoading(true)
    const request = ++latestRequest.current
    try {
      const [callsRes, analyticsRes] = await Promise.all([
        authedFetch(callsUrl),
        authedFetch(analyticsUrl),
      ])
      if (!callsRes.ok || !analyticsRes.ok) throw new Error('calls request failed')
      const [nextCalls, nextAnalytics] = await Promise.all([callsRes.json(), analyticsRes.json()])
      // Only the newest request may paint, so a slow answer for the previous
      // period can't replace the one on screen.
      if (request !== latestRequest.current) return
      setCalls(nextCalls)
      setAnalytics(nextAnalytics)
      setFailed(false)
    } catch {
      if (request === latestRequest.current) setFailed(true)
    } finally {
      if (request === latestRequest.current) setLoading(false)
    }
  }, [callsUrl, analyticsUrl])

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
        const res = await authedFetch(`${API}/calls/${tenantId}/${callId}`)
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

  const empty = emptyCallsCopy(urgFilter, period, calls.length)

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
                  aria-pressed={period === v}
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
          <div className="leads-filter-bar">
            {(['all', 'hot', 'warm', 'cold'] as const).map(u => (
              <button
                key={u}
                className={`db-pill db-pill--mono${urgFilter === u ? ' active' : ''}`}
                onClick={() => setUrgFilter(u)}
              >
                {u === 'all' ? 'All' : capitalize(u)}
                {u !== 'all' && analytics && (
                  <span style={{ opacity: 0.7 }}>
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
                <div className="db-section-icon" style={{ background: '#f0fdf4' }}><Phone size={14} aria-hidden /></div>
                <span className="db-section-name">Call History</span>
                <span className="db-section-hint">{filtered.length} calls</span>
              </div>
            </div>

            {loading ? (
              <LoadingState />
            ) : failed && calls.length === 0 ? (
              <ErrorState title="We couldn’t load your calls." onRetry={fetchData} />
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>
                  </svg>
                }
                title={empty.title}
                sub={empty.sub}
                action={empty.canClear ? (
                  <button className="db-btn db-btn--ghost db-btn--sm" onClick={() => router.push(`${pathname}?period=0`, { scroll: false })}>
                    Clear filters
                  </button>
                ) : undefined}
              />
            ) : (
              filtered.map(call => {
                const lead = call.leads
                const isExpanded = expandedId === call.id
                const detail = detailMap[call.id]
                const isLoadingDetail = detailLoading === call.id

                return (
                  <div key={call.id} className="db-lead-row">
                    <div className="db-lead-main" {...disclosureProps(isExpanded, () => toggleExpand(call.id), `call-${call.id}`)}>
                      <div className="db-lead-av">{initials(lead?.name, lead?.phone)}</div>
                      <div className="db-lead-info">
                        <div className="db-lead-name">
                          {lead?.name ?? 'Unknown caller'}
                          {lead?.phone && <span className="db-lead-phone-inline"> · {lead.phone}</span>}
                        </div>
                        <div className="db-lead-sum">{lead?.summary ?? 'No summary'}</div>
                      </div>
                      {call.disposition && (
                        <span className={dispositionBadgeClass(call.disposition)}>
                          {dispositionLabel(call.disposition)}
                        </span>
                      )}
                      <span className={urgBadgeClass(lead?.urgency)}>
                        {lead?.urgency ? capitalize(lead.urgency) : 'Unrated'}
                      </span>
                      <span className="db-lead-time" style={{ minWidth: 64, textAlign: 'right' }}>
                        {formatDuration(call.duration_secs)}
                      </span>
                      <span className="db-lead-time">{formatCallDate(call.created_at)}</span>
                    </div>

                    <AnimatePresence>
                      {isExpanded && (
                        <motion.div id={`call-${call.id}`}
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          style={{ overflow: 'hidden' }}
                        >
                          <div className="db-lead-expanded">
                            {isLoadingDetail ? (
                              <div style={{ fontSize: 12, color: 'var(--db-muted)', padding: '8px 0' }}>Loading transcript…</div>
                            ) : detail?.transcript ? (
                              <>
                                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--db-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
                                  Transcript
                                </div>
                                <TranscriptLines text={detail.transcript} />
                              </>
                            ) : (
                              <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>No transcript available.</div>
                            )}

                            {lead?.metadata?.key_details && Object.keys(lead.metadata.key_details).length > 0 && (
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 14 }}>
                                {Object.entries(lead.metadata.key_details).map(([k, v]) => (
                                  <div key={k} className="db-chip">
                                    <b>{k.replace(/_/g, ' ')}:</b> {String(v)}
                                  </div>
                                ))}
                              </div>
                            )}

                            {lead?.metadata?.suggested_next_step && (
                              <div style={{ marginTop: 12, fontSize: 12, color: 'var(--db-text-2)' }}>
                                <span style={{ fontWeight: 600, color: 'var(--db-text)' }}>Next step: </span>
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
