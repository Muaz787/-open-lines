'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

interface RevenueData {
  mrr: number
  active_count: number
  trial_count: number
  comped_count: number
  past_due_count: number
  cancelled_count: number
  none_count: number
  total: number
  plan_distribution: Record<string, { count: number; revenue: number }>
}

const PLAN_PRICE: Record<string, number> = { starter: 99, pro: 199, business: 379 }

export default function RevenuePage() {
  const router = useRouter()
  const [data, setData] = useState<RevenueData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (!session) { router.replace('/login'); return }
      const res = await fetch('/api/admin/revenue', { headers: { Authorization: `Bearer ${session.access_token}` } })
      if (res.ok) setData(await res.json())
      setLoading(false)
    })
  }, [router])

  if (loading) return <div className="adm-loading"><div className="adm-spinner" />Loading…</div>
  if (!data) return null

  const cards = [
    { label: 'Estimated MRR', value: `$${data.mrr.toLocaleString()}`, sub: 'active subscriptions only', cls: 'green' },
    { label: 'Active Subscriptions', value: data.active_count, sub: 'paying customers', cls: 'green' },
    { label: 'Trialing', value: data.trial_count, sub: 'free trial', cls: 'blue' },
    { label: 'Comped', value: data.comped_count, sub: 'free (billing-exempt)', cls: 'green' },
    { label: 'Past Due', value: data.past_due_count, sub: 'payment failed', cls: data.past_due_count > 0 ? 'red' : undefined },
    { label: 'Cancelled', value: data.cancelled_count, sub: 'churned' },
    { label: 'No Subscription', value: data.none_count, sub: 'trial ended / not activated' },
  ]

  return (
    <>
      <h1 className="adm-page-title">Revenue</h1>
      <p className="adm-page-sub">Calculated from subscription records · {data.total} total tenants</p>

      <div className="adm-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        {cards.map(c => (
          <div key={c.label} className="adm-card">
            <div className="adm-card-label">{c.label}</div>
            <div className={`adm-card-value${c.cls ? ' ' + c.cls : ''}`}>{c.value}</div>
            <div className="adm-card-sub">{c.sub}</div>
          </div>
        ))}
      </div>

      <div className="adm-section">
        <div className="adm-section-title">Plan Distribution</div>
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th>Plan</th>
                <th>Price/mo</th>
                <th>Active Subscribers</th>
                <th>Plan MRR</th>
              </tr>
            </thead>
            <tbody>
              {['starter', 'pro', 'business'].map(plan => {
                const dist = data.plan_distribution[plan] ?? { count: 0, revenue: 0 }
                return (
                  <tr key={plan} className="no-hover">
                    <td style={{ fontWeight: 500, textTransform: 'capitalize' }}>{plan}</td>
                    <td>${PLAN_PRICE[plan]}</td>
                    <td>{dist.count}</td>
                    <td style={{ fontWeight: 500, color: dist.revenue > 0 ? 'var(--db-accent-text)' : 'var(--db-muted)' }}>
                      ${dist.revenue.toLocaleString()}
                    </td>
                  </tr>
                )
              })}
              <tr className="no-hover" style={{ borderTop: '2px solid var(--db-border)' }}>
                <td colSpan={2} style={{ fontWeight: 600 }}>Total MRR</td>
                <td style={{ fontWeight: 600 }}>{data.active_count}</td>
                <td style={{ fontWeight: 700, color: 'var(--db-accent-text)' }}>${data.mrr.toLocaleString()}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--db-muted)' }}>
          Revenue is estimated from subscription records. Overage billing and Stripe proration adjustments are not included.
        </p>
      </div>

      <div className="adm-section">
        <div className="adm-section-title">Subscription Status Breakdown</div>
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead><tr><th>Status</th><th>Count</th><th>Share</th></tr></thead>
            <tbody>
              {[
                { status: 'active', count: data.active_count, cls: 'adm-badge-green' },
                { status: 'trialing', count: data.trial_count, cls: 'adm-badge-blue' },
                { status: 'past_due', count: data.past_due_count, cls: 'adm-badge-red' },
                { status: 'canceled', count: data.cancelled_count, cls: 'adm-badge-gray' },
                { status: 'none', count: data.none_count, cls: 'adm-badge-gray' },
              ].map(row => (
                <tr key={row.status} className="no-hover">
                  <td><span className={`adm-badge ${row.cls}`}>{row.status}</span></td>
                  <td>{row.count}</td>
                  <td className="adm-table-muted">{data.total > 0 ? Math.round((row.count / data.total) * 100) : 0}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
