'use client'

import { useState, useEffect, useCallback } from 'react'
import { authedFetch } from '@/lib/api'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type Severity = 'positive' | 'opportunity' | 'monitor' | 'action'

interface InsightCard {
  title: string
  body: string
  severity: Severity
  confidence: 'high' | 'medium' | 'low'
  confidence_pct: number
  sample_size: number
}
interface ActionItem extends Omit<InsightCard, 'body'> {
  what_happened: string
  why: string
  recommendation: string
  expected_benefit: string
}
interface KnowledgeItem extends Omit<InsightCard, 'body'> {
  recommendation: string
}
interface Performance {
  calls_answered: number
  sales_opportunities: number
  new_leads: number
  appointments_booked: number
  booking_conversion_rate: number | null
  conversion_note: string | null
  returning_customers: number
  avg_call_duration_secs: number
  hot_leads: number
  follow_up_required: number
  ai_confidence_score: number | null
  knowledge_gaps_detected: number
}
interface Payload {
  has_data: boolean
  generated_at: string | null
  stale: boolean
  window_label?: string
  headline?: string | null
  performance?: Performance
  insights?: InsightCard[]
  action_items?: ActionItem[]
  knowledge_improvements?: KnowledgeItem[]
  ai_performance?: { confidence_pct: number | null; knowledge_gap_calls: number; notes: string[] }
  data_basis?: { total_calls: number; window_days: number }
}

const SEV: Record<Severity, { label: string; color: string; bg: string }> = {
  positive:    { label: 'Positive trend',      color: '#16a34a', bg: 'rgba(22,163,74,0.10)' },
  opportunity: { label: 'Opportunity',         color: '#2563eb', bg: 'rgba(37,99,235,0.10)' },
  monitor:     { label: 'Worth monitoring',    color: '#d97706', bg: 'rgba(217,119,6,0.10)' },
  action:      { label: 'Action recommended',  color: '#dc2626', bg: 'rgba(220,38,38,0.10)' },
}

function fmtDuration(secs: number): string {
  if (!secs) return '0s'
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return m ? `${m}m ${s}s` : `${s}s`
}
function timeAgo(iso: string | null): string {
  if (!iso) return 'recently'
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.round(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

function SeverityDot({ severity }: { severity: Severity }) {
  return <span style={{ width: 9, height: 9, borderRadius: '50%', background: SEV[severity].color, flexShrink: 0, marginTop: 5 }} />
}

function ConfidenceChip({ pct, n, confidence }: { pct: number; n: number; confidence: string }) {
  return (
    <span style={{
      fontSize: 10.5, fontWeight: 600, color: 'var(--db-muted)', whiteSpace: 'nowrap',
      background: 'var(--db-bg)', border: '1px solid var(--db-border)', borderRadius: 20, padding: '2px 9px',
    }}>
      {confidence[0].toUpperCase() + confidence.slice(1)} · {pct}% · {n} {n === 1 ? 'convo' : 'convos'}
    </span>
  )
}

function SeverityTag({ severity }: { severity: Severity }) {
  const s = SEV[severity]
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase',
      color: s.color, background: s.bg, borderRadius: 4, padding: '2px 7px', whiteSpace: 'nowrap',
    }}>{s.label}</span>
  )
}

function Metric({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="ai-metric">
      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--db-text)', letterSpacing: '-0.5px', lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 11.5, color: 'var(--db-muted)', marginTop: 3 }}>{label}</div>
      {sub && <div style={{ fontSize: 10.5, color: 'var(--db-faint)', marginTop: 1 }}>{sub}</div>}
    </div>
  )
}

function SectionTitle({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0 12px' }}>
      <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--db-faint)' }}>{children}</span>
      {count != null && count > 0 && (
        <span style={{ fontSize: 11, color: 'var(--db-faint)', fontWeight: 500 }}>{count}</span>
      )}
    </div>
  )
}

export default function AiInsights({ tenantId }: { tenantId: string }) {
  const [data, setData]       = useState<Payload | null>(null)
  const [loading, setLoading] = useState(false)
  const [booted, setBooted]   = useState(false)

  const load = useCallback(async (refresh: boolean) => {
    setLoading(true)
    try {
      const res = await authedFetch(`${API}/leads/${tenantId}/insights${refresh ? '?refresh=1' : ''}`)
      if (res.ok) setData(await res.json())
    } catch { /* keep previous */ }
    finally { setLoading(false); setBooted(true) }
  }, [tenantId])

  // Fetch cached insights on mount (fast — never blocks on generation).
  useEffect(() => { load(false) }, [load])

  const p = data?.performance
  const hasContent = !!data?.has_data

  return (
    <div className="db-section-card" style={{ marginTop: 14 }}>
      <div className="db-section-hdr">
        <div className="db-section-title-row">
          <div className="db-section-icon" style={{ background: '#f5f0fe' }}>✦</div>
          <span className="db-section-name">AI Insights</span>
          {data?.window_label && hasContent && (
            <span style={{ fontSize: 11, color: 'var(--db-faint)', marginLeft: 4 }}>· {data.window_label}</span>
          )}
        </div>
        {hasContent && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {data?.generated_at && (
              <span style={{ fontSize: 11, color: 'var(--db-faint)' }}>Updated {timeAgo(data.generated_at)}</span>
            )}
            <button className="db-btn db-btn--ghost db-btn--sm" onClick={() => load(true)} disabled={loading}>
              {loading ? 'Analyzing…' : 'Refresh'}
            </button>
          </div>
        )}
      </div>

      {/* Stale banner */}
      {hasContent && data?.stale && (
        <div style={{ padding: '10px 16px', background: 'var(--db-warn-bg)', color: 'var(--db-warn-text)', fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
          <span>New calls have come in since this analysis.</span>
          <button className="db-btn db-btn--sm" style={{ background: 'var(--db-warn-text)', color: '#fff' }} onClick={() => load(true)} disabled={loading}>
            {loading ? 'Analyzing…' : 'Re-analyze'}
          </button>
        </div>
      )}

      {/* Teaser / empty state */}
      {booted && !hasContent && !loading && (
        <div className="db-insight-teaser">
          <div className="db-insight-copy">
            Your AI receptionist analyzes every conversation. Generate a consultant-style review
            of performance, patterns, action items, and knowledge gaps.
          </div>
          <button className="db-btn db-btn--dark" onClick={() => load(true)}>✦ Generate insights</button>
        </div>
      )}

      {/* First-time loading */}
      {!booted && (
        <div style={{ padding: '20px 16px', fontSize: 12, color: 'var(--db-muted)', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>◌</span>
          Loading insights…
        </div>
      )}
      {booted && !hasContent && loading && (
        <div style={{ padding: '20px 16px', fontSize: 12, color: 'var(--db-muted)', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>◌</span>
          Analyzing every conversation… this can take a few seconds.
        </div>
      )}

      {hasContent && p && (
        <div style={{ padding: '16px 18px 20px' }}>
          {data?.headline && (
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--db-text)', lineHeight: 1.55, marginBottom: 18 }}>
              {data.headline}
            </div>
          )}

          {/* 1 — Business Performance */}
          <SectionTitle>Business Performance</SectionTitle>
          <div className="ai-metric-grid">
            <Metric label="Calls answered" value={p.calls_answered} />
            <Metric label="Sales opportunities" value={p.sales_opportunities} />
            <Metric label="New leads" value={p.new_leads} />
            <Metric label="Appointments booked" value={p.appointments_booked} />
            <Metric
              label="Booking conversion"
              value={p.booking_conversion_rate != null ? `${p.booking_conversion_rate}%` : '—'}
            />
            <Metric label="Returning customers" value={p.returning_customers} />
            <Metric label="Avg call duration" value={fmtDuration(p.avg_call_duration_secs)} />
            <Metric label="Hot leads" value={p.hot_leads} />
            <Metric label="Follow-up required" value={p.follow_up_required} />
            <Metric label="AI confidence" value={p.ai_confidence_score != null ? `${p.ai_confidence_score}%` : '—'} />
            <Metric label="Knowledge gaps" value={p.knowledge_gaps_detected} />
          </div>
          {p.conversion_note && (
            <div style={{ fontSize: 11.5, color: 'var(--db-faint)', marginTop: 10, lineHeight: 1.5 }}>ⓘ {p.conversion_note}</div>
          )}

          {/* 2 — Insights (observations) */}
          {(data?.insights?.length ?? 0) > 0 && (
            <div style={{ marginTop: 26 }}>
              <SectionTitle count={data!.insights!.length}>Insights</SectionTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {data!.insights!.map((it, i) => (
                  <div key={i} className="ai-card">
                    <div className="ai-card-head">
                      <div style={{ display: 'flex', gap: 9 }}>
                        <SeverityDot severity={it.severity} />
                        <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--db-text)' }}>{it.title}</span>
                      </div>
                      <ConfidenceChip pct={it.confidence_pct} n={it.sample_size} confidence={it.confidence} />
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--db-text-2)', lineHeight: 1.6, paddingLeft: 18 }}>{it.body}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 3 — Action Items */}
          {(data?.action_items?.length ?? 0) > 0 && (
            <div style={{ marginTop: 26 }}>
              <SectionTitle count={data!.action_items!.length}>Action Items</SectionTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {data!.action_items!.map((it, i) => (
                  <div key={i} className="ai-card">
                    <div className="ai-card-head">
                      <div style={{ display: 'flex', gap: 9, alignItems: 'center', flexWrap: 'wrap' }}>
                        <SeverityDot severity={it.severity} />
                        <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--db-text)' }}>{it.title}</span>
                        <SeverityTag severity={it.severity} />
                      </div>
                      <ConfidenceChip pct={it.confidence_pct} n={it.sample_size} confidence={it.confidence} />
                    </div>
                    <div style={{ paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                      {it.what_happened && <ActionRow label="What happened" value={it.what_happened} />}
                      {it.why && <ActionRow label="Why it matters" value={it.why} />}
                      {it.recommendation && <ActionRow label="Recommended" value={it.recommendation} strong />}
                      {it.expected_benefit && <ActionRow label="Expected benefit" value={it.expected_benefit} />}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 4 — Knowledge Improvements */}
          {(data?.knowledge_improvements?.length ?? 0) > 0 && (
            <div style={{ marginTop: 26 }}>
              <SectionTitle count={data!.knowledge_improvements!.length}>Knowledge Improvements</SectionTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {data!.knowledge_improvements!.map((it, i) => (
                  <div key={i} className="ai-card">
                    <div className="ai-card-head">
                      <div style={{ display: 'flex', gap: 9 }}>
                        <SeverityDot severity={it.severity} />
                        <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--db-text)' }}>{it.title}</span>
                      </div>
                      <ConfidenceChip pct={it.confidence_pct} n={it.sample_size} confidence={it.confidence} />
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--db-text-2)', lineHeight: 1.6, paddingLeft: 18 }}>{it.recommendation}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* AI performance footnote */}
          {data?.ai_performance && data.ai_performance.confidence_pct != null && (
            <div style={{ marginTop: 22, paddingTop: 14, borderTop: '1px solid var(--db-border-lt)', fontSize: 12, color: 'var(--db-muted)' }}>
              AI receptionist answered confidently in <strong>{data.ai_performance.confidence_pct}%</strong> of conversations
              {data.ai_performance.knowledge_gap_calls > 0 && <> · {data.ai_performance.knowledge_gap_calls} call{data.ai_performance.knowledge_gap_calls === 1 ? '' : 's'} hit a knowledge gap</>}.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ActionRow({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div style={{ fontSize: 13, lineHeight: 1.55 }}>
      <span style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--db-faint)', marginRight: 7 }}>{label}</span>
      <span style={{ color: strong ? 'var(--db-text)' : 'var(--db-text-2)', fontWeight: strong ? 600 : 400 }}>{value}</span>
    </div>
  )
}
