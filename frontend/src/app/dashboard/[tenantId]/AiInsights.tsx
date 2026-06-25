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

export default function AiInsights({ tenantId, businessName }: { tenantId: string; businessName?: string }) {
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

  const printReport = () => {
    if (!data?.has_data || !data.performance) return
    const w = window.open('', '_blank')
    if (!w) return
    w.document.write(buildReportHtml(data, businessName))
    w.document.close()
    w.focus()
    setTimeout(() => w.print(), 350)
  }

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
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {data?.generated_at && (
              <span style={{ fontSize: 11, color: 'var(--db-faint)', marginRight: 2 }}>Updated {timeAgo(data.generated_at)}</span>
            )}
            <button className="db-btn db-btn--ghost db-btn--sm" onClick={printReport} title="Download or print this report">
              ↓ PDF / Print
            </button>
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

// --------------------------------------------------------------------------- //
// Printable / downloadable report
// --------------------------------------------------------------------------- //
function esc(s: unknown): string {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))
}

function buildReportHtml(data: Payload, businessName?: string): string {
  const p = data.performance!
  const gen = data.generated_at ? new Date(data.generated_at).toLocaleString() : 'recently'
  const conf = (n: number, pct: number, level: string) =>
    `${level[0].toUpperCase() + level.slice(1)} confidence · ${pct}% · based on ${n} ${n === 1 ? 'conversation' : 'conversations'}`

  const metricsHtml = ([
    ['Calls answered', p.calls_answered],
    ['Sales opportunities', p.sales_opportunities],
    ['New leads', p.new_leads],
    ['Appointments booked', p.appointments_booked],
    ['Booking conversion', p.booking_conversion_rate != null ? `${p.booking_conversion_rate}%` : '—'],
    ['Returning customers', p.returning_customers],
    ['Avg call duration', fmtDuration(p.avg_call_duration_secs)],
    ['Hot leads', p.hot_leads],
    ['Follow-up required', p.follow_up_required],
    ['AI confidence', p.ai_confidence_score != null ? `${p.ai_confidence_score}%` : '—'],
    ['Knowledge gaps', p.knowledge_gaps_detected],
  ] as [string, React.ReactNode][]).map(([label, value]) => `
    <div class="metric"><div class="metric-val">${esc(value)}</div><div class="metric-lbl">${esc(label)}</div></div>`).join('')

  const card = (sev: Severity, head: string, chip: string, bodyHtml: string) => {
    const c = SEV[sev]
    return `<div class="card">
      <div class="card-head">
        <div class="card-title"><span class="dot" style="background:${c.color}"></span>${head}
          <span class="sevtag" style="color:${c.color};background:${c.bg}">${esc(c.label)}</span></div>
        <div class="chip">${esc(chip)}</div>
      </div>${bodyHtml}</div>`
  }

  const insightsHtml = (data.insights || []).map(it =>
    card(it.severity, esc(it.title), conf(it.sample_size, it.confidence_pct, it.confidence),
      `<div class="body">${esc(it.body)}</div>`)).join('')

  const actionsHtml = (data.action_items || []).map(it => {
    const rows = [
      it.what_happened && ['What happened', it.what_happened],
      it.why && ['Why it matters', it.why],
      it.recommendation && ['Recommended', it.recommendation],
      it.expected_benefit && ['Expected benefit', it.expected_benefit],
    ].filter(Boolean) as [string, string][]
    const body = `<div class="rows">${rows.map(([l, v]) =>
      `<div><span class="rlbl">${esc(l)}</span> ${esc(v)}</div>`).join('')}</div>`
    return card(it.severity, esc(it.title), conf(it.sample_size, it.confidence_pct, it.confidence), body)
  }).join('')

  const knowledgeHtml = (data.knowledge_improvements || []).map(it =>
    card(it.severity, esc(it.title), conf(it.sample_size, it.confidence_pct, it.confidence),
      `<div class="body">${esc(it.recommendation)}</div>`)).join('')

  const section = (title: string, html: string) =>
    html ? `<h2>${esc(title)}</h2>${html}` : ''

  return `<!DOCTYPE html><html><head><meta charset="utf-8">
  <title>AI Insights${businessName ? ' — ' + esc(businessName) : ''}</title>
  <style>
    *{box-sizing:border-box}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a;max-width:780px;margin:0 auto;padding:44px 48px;}
    .head{display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid #0B2343;padding-bottom:18px;margin-bottom:24px;}
    .head img{height:34px}
    .head .meta{text-align:right;font-size:12px;color:#64748b;line-height:1.6}
    h1{font-size:22px;margin:0 0 4px}
    .sub{font-size:13px;color:#475569;margin:0 0 26px}
    h2{font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#94a3b8;margin:30px 0 12px;}
    .metrics{display:flex;flex-wrap:wrap;gap:14px}
    .metric{flex:1 1 120px;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px}
    .metric-val{font-size:22px;font-weight:700;letter-spacing:-0.5px}
    .metric-lbl{font-size:11.5px;color:#64748b;margin-top:3px}
    .note{font-size:12px;color:#94a3b8;margin-top:10px}
    .card{border:1px solid #e2e8f0;border-radius:10px;padding:13px 15px;margin-bottom:10px;}
    .card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:6px}
    .card-title{font-size:14px;font-weight:600;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .dot{width:9px;height:9px;border-radius:50%;display:inline-block}
    .sevtag{font-size:9.5px;font-weight:700;letter-spacing:0.05em;text-transform:uppercase;border-radius:4px;padding:2px 7px}
    .chip{font-size:10.5px;font-weight:600;color:#64748b;white-space:nowrap;border:1px solid #e2e8f0;border-radius:20px;padding:2px 9px;}
    .body{font-size:13px;color:#475569;line-height:1.6;padding-left:17px}
    .rows{padding-left:17px;font-size:13px;line-height:1.55;display:flex;flex-direction:column;gap:5px}
    .rlbl{font-size:10px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;color:#94a3b8;margin-right:6px}
    .foot{margin-top:34px;border-top:1px solid #e2e8f0;padding-top:14px;font-size:11px;color:#94a3b8}
    @media print{body{padding:24px}.card,.metric{break-inside:avoid}}
  </style></head><body>
    <div class="head">
      <img src="https://www.openlines.ai/logo.png" alt="Open Lines">
      <div class="meta">AI Insights report<br>Generated ${esc(gen)}</div>
    </div>
    <h1>AI Insights${businessName ? ' — ' + esc(businessName) : ''}</h1>
    <p class="sub">An operations review of your AI receptionist over the ${esc(data.window_label || 'recent period')}.</p>
    ${data.headline ? `<p style="font-size:15px;font-weight:600;line-height:1.55;margin:0 0 8px">${esc(data.headline)}</p>` : ''}

    <h2>Business Performance</h2>
    <div class="metrics">${metricsHtml}</div>
    ${p.conversion_note ? `<div class="note">ⓘ ${esc(p.conversion_note)}</div>` : ''}

    ${section('Insights', insightsHtml)}
    ${section('Action Items', actionsHtml)}
    ${section('Knowledge Improvements', knowledgeHtml)}

    <div class="foot">Generated by Open Lines · AI receptionist analytics${businessName ? ' · ' + esc(businessName) : ''}</div>
  </body></html>`
}
