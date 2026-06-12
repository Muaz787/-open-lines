'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

interface Call {
  id: string
  created_at: string
  duration_secs: number | null
  tenant_id: string
  business_name: string
  caller_phone: string
  urgency: string | null
  lead_status: string | null
  has_appointment: boolean
}

function UrgencyBadge({ u }: { u: string | null }) {
  const map: Record<string, string> = { hot: 'adm-badge-red', warm: 'adm-badge-amber', cold: 'adm-badge-blue' }
  if (!u) return <span className="adm-badge adm-badge-gray">—</span>
  return <span className={`adm-badge ${map[u] ?? 'adm-badge-gray'}`}>{u}</span>
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('en-CA', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatDuration(secs: number | null) {
  if (!secs) return '—'
  const m = Math.floor(secs / 60), s = secs % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function CallsPage() {
  const router = useRouter()
  const [calls, setCalls] = useState<Call[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [tenantId, setTenantId] = useState('')
  const [hasAppt, setHasAppt] = useState('')

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace('/login'); return }
      setToken(session.access_token)
    })
  }, [router])

  const load = useCallback(async (p: number) => {
    if (!token) return
    setLoading(true)
    const params = new URLSearchParams({
      page: String(p),
      ...(dateFrom && { date_from: dateFrom }),
      ...(dateTo && { date_to: dateTo }),
      ...(tenantId && { tenant_id: tenantId }),
      ...(hasAppt && { has_appointment: hasAppt }),
    })
    const res = await fetch(`/api/admin/calls?${params}`, { headers: { Authorization: `Bearer ${token}` } })
    if (res.ok) { const d = await res.json(); setCalls(d.calls); setTotal(d.total) }
    setLoading(false)
  }, [token, dateFrom, dateTo, tenantId, hasAppt])

  useEffect(() => { if (token) load(page) }, [token, page, load])

  const perPage = 50
  const totalPages = Math.max(1, Math.ceil(total / perPage))

  return (
    <>
      <h1 className="adm-page-title">Calls</h1>
      <p className="adm-page-sub">{total} total calls</p>

      <div className="adm-toolbar">
        <input type="date" className="adm-input" style={{ minWidth: 140 }} value={dateFrom} onChange={e => setDateFrom(e.target.value)} placeholder="From" />
        <input type="date" className="adm-input" style={{ minWidth: 140 }} value={dateTo} onChange={e => setDateTo(e.target.value)} placeholder="To" />
        <select className="adm-select" value={hasAppt} onChange={e => { setHasAppt(e.target.value); setPage(1) }}>
          <option value="">Appointments: any</option>
          <option value="yes">Booked</option>
          <option value="no">No appointment</option>
        </select>
        <button className="adm-btn adm-btn-secondary" onClick={() => { setPage(1); load(1) }}>Filter</button>
      </div>

      <div className="adm-section" style={{ padding: 0 }}>
        {loading ? (
          <div className="adm-loading"><div className="adm-spinner" />Loading calls…</div>
        ) : calls.length === 0 ? (
          <div className="adm-empty">No calls found</div>
        ) : (
          <div className="adm-table-wrap">
            <table className="adm-table">
              <thead>
                <tr>
                  <th>Date/Time</th>
                  <th>Business</th>
                  <th>Caller</th>
                  <th>Duration</th>
                  <th>Urgency</th>
                  <th>Lead Status</th>
                  <th>Booked</th>
                </tr>
              </thead>
              <tbody>
                {calls.map(c => (
                  <tr key={c.id} className="no-hover">
                    <td style={{ whiteSpace: 'nowrap' }}>{formatDate(c.created_at)}</td>
                    <td style={{ fontWeight: 500 }}>{c.business_name}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{c.caller_phone}</td>
                    <td>{formatDuration(c.duration_secs)}</td>
                    <td><UrgencyBadge u={c.urgency} /></td>
                    <td className="adm-table-muted">{c.lead_status ?? '—'}</td>
                    <td>
                      <span style={{ color: c.has_appointment ? 'var(--db-accent-text)' : 'var(--db-faint)' }}>
                        {c.has_appointment ? '✓ yes' : '—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="adm-pagination">
        <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
        <span>Page {page} of {totalPages} · {total} calls</span>
        <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next →</button>
      </div>
    </>
  )
}
