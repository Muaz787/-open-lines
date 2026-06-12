'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'

interface OverviewData {
  total_tenants: number
  signups_today: number
  signups_week: number
  active_tenants: number
  paid_tenants: number
  trial_tenants: number
  calls_today: number
  calls_week: number
  minutes_month: number
  appointments_month: number
  mrr: number
  failed_payments: number
  signups_30d: { date: string; count: number }[]
  calls_30d: { date: string; count: number }[]
  appointments_30d: { date: string; count: number }[]
  recent_signups: {
    id: string
    business_name: string
    industry: string
    email: string
    owner_name: string
    subscription_status: string
    subscription_plan: string
    created_at: string
  }[]
}

function BarChart({ data, color = '#3dba72' }: { data: { date: string; count: number }[]; color?: string }) {
  const max = Math.max(...data.map(d => d.count), 1)
  return (
    <div className="adm-chart-wrap">
      {data.map(d => (
        <div
          key={d.date}
          className="adm-chart-bar"
          title={`${d.date}: ${d.count}`}
          style={{ height: `${Math.max(2, Math.round((d.count / max) * 52))}px`, background: d.count > 0 ? color + '33' : undefined, borderColor: d.count > 0 ? color + '66' : undefined }}
        />
      ))}
    </div>
  )
}

function StatusBadge({ status }: { status: string | null }) {
  const map: Record<string, string> = {
    active: 'adm-badge-green',
    trialing: 'adm-badge-blue',
    past_due: 'adm-badge-red',
    canceled: 'adm-badge-gray',
    none: 'adm-badge-gray',
  }
  const cls = map[status ?? 'none'] ?? 'adm-badge-gray'
  return <span className={`adm-badge ${cls}`}>{status ?? 'none'}</span>
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export default function AdminOverview() {
  const router = useRouter()
  const [data, setData] = useState<OverviewData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    async function load() {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) { router.replace('/login'); return }

      const res = await fetch('/api/admin/overview', {
        headers: { Authorization: `Bearer ${session.access_token}` },
      })
      if (!res.ok) { setError('Failed to load overview'); setLoading(false); return }
      setData(await res.json())
      setLoading(false)
    }
    load()
  }, [router])

  if (loading) return <div className="adm-loading"><div className="adm-spinner" />Loading…</div>
  if (error) return <div className="adm-empty">{error}</div>
  if (!data) return null

  const cards = [
    { label: 'Total Tenants', value: data.total_tenants, sub: 'all time' },
    { label: 'Signups Today', value: data.signups_today, sub: 'new accounts' },
    { label: 'Signups This Week', value: data.signups_week, sub: 'last 7 days' },
    { label: 'Active Tenants', value: data.active_tenants, sub: 'is_active = true', cls: 'green' },
    { label: 'Paid', value: data.paid_tenants, sub: 'active subscription', cls: 'green' },
    { label: 'Trialing', value: data.trial_tenants, sub: 'trial subscriptions', cls: 'blue' },
    { label: 'Calls Today', value: data.calls_today, sub: 'inbound calls' },
    { label: 'Calls This Week', value: data.calls_week, sub: 'last 7 days' },
    { label: 'Minutes This Month', value: data.minutes_month, sub: 'call minutes used' },
    { label: 'Appointments (Month)', value: data.appointments_month, sub: 'bookings made' },
    { label: 'Estimated MRR', value: `$${data.mrr.toLocaleString()}`, sub: 'active subs only', cls: 'green' },
    { label: 'Failed Payments', value: data.failed_payments, sub: 'past_due status', cls: data.failed_payments > 0 ? 'red' : undefined },
  ]

  return (
    <>
      <h1 className="adm-page-title">Overview</h1>
      <p className="adm-page-sub">Real-time metrics from the Open Lines database</p>

      <div className="adm-grid">
        {cards.map(c => (
          <div key={c.label} className="adm-card">
            <div className="adm-card-label">{c.label}</div>
            <div className={`adm-card-value${c.cls ? ' ' + c.cls : ''}`}>{c.value}</div>
            <div className="adm-card-sub">{c.sub}</div>
          </div>
        ))}
      </div>

      <div className="adm-chart-grid">
        {[
          { label: 'Signups (30d)', data: data.signups_30d, color: '#4f6ef7' },
          { label: 'Calls (30d)', data: data.calls_30d, color: '#3dba72' },
          { label: 'Appointments (30d)', data: data.appointments_30d, color: '#d97706' },
        ].map(c => (
          <div key={c.label} className="adm-section" style={{ marginBottom: 0 }}>
            <div className="adm-section-title">{c.label}</div>
            <BarChart data={c.data} color={c.color} />
          </div>
        ))}
      </div>

      <div className="adm-section">
        <div className="adm-section-title">Recent Signups</div>
        {data.recent_signups.length === 0 ? (
          <div className="adm-empty">No tenants yet</div>
        ) : (
          <div className="adm-table-wrap">
            <table className="adm-table">
              <thead>
                <tr>
                  <th>Business</th>
                  <th>Owner</th>
                  <th>Industry</th>
                  <th>Plan</th>
                  <th>Status</th>
                  <th>Joined</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_signups.map(t => (
                  <tr key={t.id} onClick={() => router.push(`/admin/tenants/${t.id}`)}>
                    <td style={{ fontWeight: 500 }}>{t.business_name}</td>
                    <td className="adm-table-muted">{t.email || t.owner_name || '—'}</td>
                    <td className="adm-table-muted">{t.industry}</td>
                    <td className="adm-table-muted">{t.subscription_plan ?? '—'}</td>
                    <td><StatusBadge status={t.subscription_status} /></td>
                    <td className="adm-table-muted">{timeAgo(t.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ marginTop: 12 }}>
          <Link href="/admin/tenants" style={{ fontSize: 13, color: 'var(--db-accent-text)', textDecoration: 'none' }}>
            View all tenants →
          </Link>
        </div>
      </div>
    </>
  )
}
