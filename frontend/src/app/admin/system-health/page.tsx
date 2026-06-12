'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

interface HealthCheck { name: string; status: 'ok' | 'warning' | 'error'; message: string }
interface HealthData {
  checks: HealthCheck[]
  webhook_failures_24h: number
  recent_failures: { id: string; error: string | null; at: string }[]
  stuck_webhooks: number
}

function StatusIcon({ s }: { s: 'ok' | 'warning' | 'error' }) {
  if (s === 'ok')      return <span style={{ color: 'var(--db-accent-text)' }}>✓</span>
  if (s === 'warning') return <span style={{ color: 'var(--db-warn-text)' }}>⚠</span>
  return <span style={{ color: 'var(--db-danger-text)' }}>✕</span>
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 60) return `${m}m ago`
  return `${Math.floor(m / 60)}h ago`
}

export default function SystemHealthPage() {
  const router = useRouter()
  const [data, setData] = useState<HealthData | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  async function load(token: string) {
    const res = await fetch('/api/admin/health', { headers: { Authorization: `Bearer ${token}` } })
    if (res.ok) setData(await res.json())
    setLoading(false)
    setRefreshing(false)
  }

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace('/login'); return }
      load(session.access_token)
    })
  }, [router])

  async function refresh() {
    setRefreshing(true)
    const { data: { session } } = await supabase.auth.getSession()
    if (session) await load(session.access_token)
  }

  if (loading) return <div className="adm-loading"><div className="adm-spinner" />Running health checks…</div>
  if (!data) return null

  const failCount = data.checks.filter(c => c.status === 'error').length
  const warnCount = data.checks.filter(c => c.status === 'warning').length

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 4 }}>
        <h1 className="adm-page-title" style={{ marginBottom: 0 }}>System Health</h1>
        <button className="adm-btn adm-btn-secondary" onClick={refresh} disabled={refreshing} style={{ height: 30, fontSize: 12 }}>
          {refreshing ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>
      <p className="adm-page-sub">
        {failCount === 0 && warnCount === 0
          ? 'All checks passing'
          : `${failCount} error${failCount !== 1 ? 's' : ''}, ${warnCount} warning${warnCount !== 1 ? 's' : ''}`
        }
      </p>

      <div className="adm-section">
        <div className="adm-section-title">Configuration Checks</div>
        {data.checks.map(c => (
          <div key={c.name} className="adm-health-row">
            <div className={`adm-health-dot ${c.status}`} />
            <div className="adm-health-name">{c.name}</div>
            <div className="adm-health-msg">{c.message}</div>
            <div className="adm-health-status">
              <StatusIcon s={c.status} />
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        <div className="adm-card">
          <div className="adm-card-label">Webhook Failures (24h)</div>
          <div className={`adm-card-value ${data.webhook_failures_24h > 0 ? 'red' : 'green'}`}>
            {data.webhook_failures_24h}
          </div>
          <div className="adm-card-sub">failed webhook_events</div>
        </div>
        <div className="adm-card">
          <div className="adm-card-label">Stuck Webhooks</div>
          <div className={`adm-card-value ${data.stuck_webhooks > 0 ? 'red' : 'green'}`}>
            {data.stuck_webhooks}
          </div>
          <div className="adm-card-sub">pending past retry time</div>
        </div>
      </div>

      {data.recent_failures.length > 0 && (
        <div className="adm-section">
          <div className="adm-section-title">Recent Webhook Failures</div>
          <div className="adm-table-wrap">
            <table className="adm-table">
              <thead><tr><th>Time</th><th>Error</th></tr></thead>
              <tbody>
                {data.recent_failures.map(f => (
                  <tr key={f.id} className="no-hover">
                    <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{timeAgo(f.at)}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--db-danger-text)' }}>
                      {f.error ?? '(no error message)'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data.webhook_failures_24h === 0 && data.stuck_webhooks === 0 && (
        <div className="adm-section">
          <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--db-accent-text)' }}>
            ✓ No webhook failures in the last 24 hours
          </div>
        </div>
      )}
    </>
  )
}
