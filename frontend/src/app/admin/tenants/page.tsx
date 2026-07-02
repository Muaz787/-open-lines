'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

interface Tenant {
  id: string
  business_name: string
  email: string
  owner_name: string
  industry: string
  subscription_plan: string | null
  subscription_status: string | null
  billing_exempt: boolean
  twilio_phone_number: string | null
  has_calendar: boolean
  has_kb: boolean
  is_active: boolean
  created_at: string
  call_count: number
}

const TRIAL_DAYS = 7
function withinTrial(created: string) {
  return Date.now() - new Date(created).getTime() < TRIAL_DAYS * 86_400_000
}
// Comp and free-trial aren't "subscriptions", so derive them for display.
function billingStatus(t: Tenant): string {
  if (t.billing_exempt) return 'comped'
  if (t.subscription_status && t.subscription_status !== 'none') return t.subscription_status
  return withinTrial(t.created_at) ? 'trial' : 'expired'
}
function planLabel(t: Tenant): string {
  if (t.billing_exempt) return 'comp'
  if (t.subscription_plan) return t.subscription_plan
  return withinTrial(t.created_at) ? 'trial' : '—'
}

function StatusBadge({ status }: { status: string | null }) {
  const map: Record<string, string> = {
    active: 'adm-badge-green', comped: 'adm-badge-green',
    trialing: 'adm-badge-blue', trial: 'adm-badge-blue',
    past_due: 'adm-badge-red', expired: 'adm-badge-gray',
    canceled: 'adm-badge-gray', none: 'adm-badge-gray',
  }
  return <span className={`adm-badge ${map[status ?? 'none'] ?? 'adm-badge-gray'}`}>{status ?? 'none'}</span>
}

function BoolDot({ yes }: { yes: boolean }) {
  return <span style={{ color: yes ? 'var(--db-accent-text)' : 'var(--db-faint)' }}>{yes ? '✓' : '—'}</span>
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-CA')
}

export default function TenantsPage() {
  const router = useRouter()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [hasCalendar, setHasCalendar] = useState('')
  const [hasKb, setHasKb] = useState('')
  const [token, setToken] = useState('')

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
      ...(search && { search }),
      ...(status && { status }),
      ...(hasCalendar && { has_calendar: hasCalendar }),
      ...(hasKb && { has_kb: hasKb }),
    })
    const res = await fetch(`/api/admin/tenants?${params}`, { headers: { Authorization: `Bearer ${token}` } })
    if (res.ok) {
      const d = await res.json()
      setTenants(d.tenants)
      setTotal(d.total)
    }
    setLoading(false)
  }, [token, search, status, hasCalendar, hasKb])

  useEffect(() => { if (token) load(page) }, [token, page, load])

  function handleSearch() { setPage(1); load(1) }

  const perPage = 50
  const totalPages = Math.max(1, Math.ceil(total / perPage))

  return (
    <>
      <h1 className="adm-page-title">Tenants</h1>
      <p className="adm-page-sub">{total} total accounts</p>

      <div className="adm-toolbar">
        <input
          className="adm-input"
          placeholder="Search by name, email…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
        />
        <select className="adm-select" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="trialing">Trialing</option>
          <option value="past_due">Past due</option>
          <option value="canceled">Canceled</option>
          <option value="none">None</option>
        </select>
        <select className="adm-select" value={hasCalendar} onChange={e => { setHasCalendar(e.target.value); setPage(1) }}>
          <option value="">Calendar: any</option>
          <option value="yes">Connected</option>
          <option value="no">Not connected</option>
        </select>
        <select className="adm-select" value={hasKb} onChange={e => { setHasKb(e.target.value); setPage(1) }}>
          <option value="">KB: any</option>
          <option value="yes">Has KB</option>
          <option value="no">No KB</option>
        </select>
        <button className="adm-btn adm-btn-secondary" onClick={handleSearch}>Search</button>
      </div>

      <div className="adm-section" style={{ padding: 0 }}>
        {loading ? (
          <div className="adm-loading"><div className="adm-spinner" />Loading tenants…</div>
        ) : tenants.length === 0 ? (
          <div className="adm-empty">No tenants found</div>
        ) : (
          <div className="adm-table-wrap">
            <table className="adm-table">
              <thead>
                <tr>
                  <th>Business</th>
                  <th>Email</th>
                  <th>Industry</th>
                  <th>Plan</th>
                  <th>Status</th>
                  <th>Phone</th>
                  <th>Cal</th>
                  <th>KB</th>
                  <th>Calls</th>
                  <th>Active</th>
                  <th>Joined</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map(t => (
                  <tr key={t.id} onClick={() => router.push(`/admin/tenants/${t.id}`)}>
                    <td style={{ fontWeight: 500 }}>{t.business_name}</td>
                    <td className="adm-table-muted" style={{ fontSize: 12 }}>{t.email || '—'}</td>
                    <td className="adm-table-muted">{t.industry}</td>
                    <td className="adm-table-muted">{planLabel(t)}</td>
                    <td><StatusBadge status={billingStatus(t)} /></td>
                    <td className="adm-table-muted" style={{ fontSize: 12, fontFamily: 'monospace' }}>{t.twilio_phone_number ?? '—'}</td>
                    <td style={{ textAlign: 'center' }}><BoolDot yes={t.has_calendar} /></td>
                    <td style={{ textAlign: 'center' }}><BoolDot yes={t.has_kb} /></td>
                    <td className="adm-table-muted">{t.call_count}</td>
                    <td><BoolDot yes={t.is_active} /></td>
                    <td className="adm-table-muted">{formatDate(t.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="adm-pagination">
        <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
        <span>Page {page} of {totalPages} · {total} tenants</span>
        <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next →</button>
      </div>
    </>
  )
}
