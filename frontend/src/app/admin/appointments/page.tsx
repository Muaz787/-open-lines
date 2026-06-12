'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

interface Appt {
  id: string
  created_at: string
  appointment_datetime: string
  caller_name: string
  caller_phone: string
  service: string
  status: string
  duration_minutes: number | null
  has_calendar_event: boolean
  tenant_id: string
  business_name: string
}

function StatusBadge({ s }: { s: string }) {
  const map: Record<string, string> = { confirmed: 'adm-badge-green', cancelled: 'adm-badge-red', completed: 'adm-badge-blue' }
  return <span className={`adm-badge ${map[s] ?? 'adm-badge-gray'}`}>{s}</span>
}

function formatDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-CA', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function AppointmentsPage() {
  const router = useRouter()
  const [appts, setAppts] = useState<Appt[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState('')
  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

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
      ...(status && { status }),
      ...(dateFrom && { date_from: dateFrom }),
      ...(dateTo && { date_to: dateTo }),
    })
    const res = await fetch(`/api/admin/appointments?${params}`, { headers: { Authorization: `Bearer ${token}` } })
    if (res.ok) { const d = await res.json(); setAppts(d.appointments); setTotal(d.total) }
    setLoading(false)
  }, [token, status, dateFrom, dateTo])

  useEffect(() => { if (token) load(page) }, [token, page, load])

  const perPage = 50
  const totalPages = Math.max(1, Math.ceil(total / perPage))

  return (
    <>
      <h1 className="adm-page-title">Appointments</h1>
      <p className="adm-page-sub">{total} total appointments</p>

      <div className="adm-toolbar">
        <input type="date" className="adm-input" style={{ minWidth: 140 }} value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
        <input type="date" className="adm-input" style={{ minWidth: 140 }} value={dateTo} onChange={e => setDateTo(e.target.value)} />
        <select className="adm-select" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}>
          <option value="">All statuses</option>
          <option value="confirmed">Confirmed</option>
          <option value="cancelled">Cancelled</option>
          <option value="completed">Completed</option>
        </select>
        <button className="adm-btn adm-btn-secondary" onClick={() => { setPage(1); load(1) }}>Filter</button>
      </div>

      <div className="adm-section" style={{ padding: 0 }}>
        {loading ? (
          <div className="adm-loading"><div className="adm-spinner" />Loading…</div>
        ) : appts.length === 0 ? (
          <div className="adm-empty">No appointments found</div>
        ) : (
          <div className="adm-table-wrap">
            <table className="adm-table">
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Appt Date</th>
                  <th>Business</th>
                  <th>Caller</th>
                  <th>Phone</th>
                  <th>Service</th>
                  <th>Duration</th>
                  <th>Status</th>
                  <th>Cal</th>
                </tr>
              </thead>
              <tbody>
                {appts.map(a => (
                  <tr key={a.id} className="no-hover">
                    <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{formatDate(a.created_at)}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{formatDate(a.appointment_datetime)}</td>
                    <td style={{ fontWeight: 500 }}>{a.business_name}</td>
                    <td>{a.caller_name || '—'}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{a.caller_phone}</td>
                    <td className="adm-table-muted">{a.service || '—'}</td>
                    <td className="adm-table-muted">{a.duration_minutes ? `${a.duration_minutes}m` : '—'}</td>
                    <td><StatusBadge s={a.status} /></td>
                    <td style={{ textAlign: 'center', color: a.has_calendar_event ? 'var(--db-accent-text)' : 'var(--db-faint)' }}>
                      {a.has_calendar_event ? '✓' : '—'}
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
        <span>Page {page} of {totalPages} · {total} appointments</span>
        <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next →</button>
      </div>
    </>
  )
}
