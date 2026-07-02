'use client'

import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'


interface TenantDetail {
  tenant: {
    id: string
    business_name: string
    industry: string
    owner_name: string
    email: string
    agent_name: string
    subscription_plan: string | null
    subscription_status: string | null
    billing_exempt: boolean
    stripe_customer_id: string | null
    stripe_subscription_id: string | null
    twilio_phone_number: string | null
    vapi_assistant_id: string | null
    is_active: boolean
    created_at: string
    has_calendar: boolean
    calendar_timezone: string | null
    appointment_duration_minutes: number | null
    website_url: string | null
    whatsapp_number: string | null
    minutes_used_this_period: number | null
    billing_period_anchor: string | null
    business_hours_start: number | null
    business_hours_end: number | null
  }
  issues: string[]
  recent_calls: { id: string; created_at: string; duration_secs: number | null; vapi_call_id: string | null }[]
  recent_appointments: { id: string; created_at: string; appointment_datetime: string; caller_name: string; caller_phone: string; service: string; status: string }[]
  kb_entries: { id: string; type: string; label: string; added_at: string }[]
  kb_count: number
}

function StatusBadge({ status }: { status: string | null }) {
  const map: Record<string, string> = { active: 'adm-badge-green', trialing: 'adm-badge-blue', past_due: 'adm-badge-red', canceled: 'adm-badge-gray', none: 'adm-badge-gray' }
  return <span className={`adm-badge ${map[status ?? 'none'] ?? 'adm-badge-gray'}`}>{status ?? 'none'}</span>
}

function formatDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-CA', { year: 'numeric', month: 'short', day: 'numeric' })
}

function formatDuration(secs: number | null) {
  if (!secs) return '—'
  const m = Math.floor(secs / 60), s = secs % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function TenantDetailPage() {
  const router = useRouter()
  const { id } = useParams<{ id: string }>()
  const [data, setData] = useState<TenantDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState('')
  const [actionMsg, setActionMsg] = useState('')
  const [actionLoading, setActionLoading] = useState(false)

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (!session) { router.replace('/login'); return }
      setToken(session.access_token)
      const res = await fetch(`/api/admin/tenants/${id}`, { headers: { Authorization: `Bearer ${session.access_token}` } })
      if (!res.ok) { router.replace('/admin/tenants'); return }
      setData(await res.json())
      setLoading(false)
    })
  }, [id, router])

  async function toggleActive() {
    if (!data || actionLoading) return
    setActionLoading(true)
    setActionMsg('')
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const res = await fetch(`/api/admin/tenants/${id}`, {
        method: 'PATCH',
        headers: { Authorization: `Bearer ${session?.access_token}` },
      })
      const json = await res.json()
      if (res.ok) {
        setData(d => d ? { ...d, tenant: { ...d.tenant, is_active: json.is_active } } : d)
        setActionMsg(`Tenant ${json.is_active ? 'activated' : 'deactivated'}`)
      } else {
        setActionMsg(`Failed: ${json.error ?? res.statusText}`)
      }
    } catch {
      setActionMsg('Network error — check backend is reachable')
    }
    setActionLoading(false)
    setTimeout(() => setActionMsg(''), 4000)
  }

  async function enableSmartRouting() {
    if (actionLoading) return
    setActionLoading(true)
    setActionMsg('')
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const res = await fetch(`/api/admin/tenants/${id}`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${session?.access_token}` },
      })
      const json = await res.json()
      setActionMsg(res.ok ? 'Smart routing enabled — calls now route through backend' : `Failed: ${json.error ?? res.statusText}`)
    } catch {
      setActionMsg('Network error — check backend is reachable')
    }
    setActionLoading(false)
    setTimeout(() => setActionMsg(''), 5000)
  }

  async function reprompt() {
    if (actionLoading) return
    setActionLoading(true)
    setActionMsg('')
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const res = await fetch(`/api/admin/tenants/${id}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${session?.access_token}` },
      })
      const json = await res.json()
      setActionMsg(res.ok ? 'System prompt rebuilt and pushed to Vapi' : `Failed: ${json.error ?? res.statusText}`)
    } catch {
      setActionMsg('Network error — check backend is reachable')
    }
    setActionLoading(false)
    setTimeout(() => setActionMsg(''), 5000)
  }

  async function setComp(exempt: boolean) {
    if (actionLoading) return
    setActionLoading(true); setActionMsg('')
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const res = await fetch(`/api/admin/tenants/${id}/comp`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${session?.access_token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ exempt }),
      })
      const json = await res.json()
      if (res.ok) {
        setData(d => d ? { ...d, tenant: { ...d.tenant, billing_exempt: json.billing_exempt } } : d)
        setActionMsg(json.billing_exempt ? 'Tenant comped — line stays live, no subscription needed' : 'Comp removed')
      } else setActionMsg(`Failed: ${json.error ?? res.statusText}`)
    } catch { setActionMsg('Network error — check backend is reachable') }
    setActionLoading(false)
    setTimeout(() => setActionMsg(''), 5000)
  }

  async function setPlan(plan: string | null) {
    if (actionLoading) return
    setActionLoading(true); setActionMsg('')
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const res = await fetch(`/api/admin/tenants/${id}/plan`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${session?.access_token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan }),
      })
      const json = await res.json()
      if (res.ok) {
        setData(d => d ? { ...d, tenant: { ...d.tenant, subscription_plan: json.subscription_plan, subscription_status: json.subscription_status } } : d)
        setActionMsg(plan ? `Plan set to ${plan} (comp)` : 'Plan cleared')
      } else setActionMsg(`Failed: ${json.error ?? res.statusText}`)
    } catch { setActionMsg('Network error — check backend is reachable') }
    setActionLoading(false)
    setTimeout(() => setActionMsg(''), 5000)
  }

  if (loading) return <div className="adm-loading"><div className="adm-spinner" />Loading tenant…</div>
  if (!data) return null

  const { tenant, issues, recent_calls, recent_appointments, kb_entries } = data

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
        <Link href="/admin/tenants" style={{ fontSize: 13, color: 'var(--db-muted)', textDecoration: 'none' }}>← Tenants</Link>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <h1 className="adm-page-title" style={{ marginBottom: 0 }}>{tenant.business_name}</h1>
        <StatusBadge status={tenant.subscription_status} />
        {!tenant.is_active && <span className="adm-badge adm-badge-red">Inactive</span>}
      </div>

      {issues.length > 0 && (
        <div className="adm-issues">
          {issues.map(issue => (
            <div key={issue} className="adm-issue-item">
              <span>⚠</span> {issue}
            </div>
          ))}
        </div>
      )}

      <div className="adm-detail-grid">
        {/* Business Profile */}
        <div className="adm-section" style={{ marginBottom: 0 }}>
          <div className="adm-section-title">Business Profile</div>
          <div className="adm-kv-list">
            <div className="adm-kv"><span className="adm-kv-key">Business name</span><span className="adm-kv-value">{tenant.business_name}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Industry</span><span className="adm-kv-value">{tenant.industry}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Owner</span><span className="adm-kv-value">{tenant.owner_name || '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Email</span><span className="adm-kv-value">{tenant.email || '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">AI agent name</span><span className="adm-kv-value">{tenant.agent_name || '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">WhatsApp</span><span className="adm-kv-value">{tenant.whatsapp_number || '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Website</span><span className="adm-kv-value">{tenant.website_url || '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Joined</span><span className="adm-kv-value">{formatDate(tenant.created_at)}</span></div>
          </div>
        </div>

        {/* Subscription */}
        <div className="adm-section" style={{ marginBottom: 0 }}>
          <div className="adm-section-title">Subscription</div>
          <div className="adm-kv-list">
            <div className="adm-kv"><span className="adm-kv-key">Plan</span><span className="adm-kv-value">{tenant.subscription_plan ?? '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Status</span><StatusBadge status={tenant.subscription_status} /></div>
            <div className="adm-kv"><span className="adm-kv-key">Phone</span><span className="adm-kv-value" style={{ fontFamily: 'monospace' }}>{tenant.twilio_phone_number ?? '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Vapi assistant</span><span className="adm-kv-value" style={{ fontFamily: 'monospace', fontSize: 11 }}>{tenant.vapi_assistant_id ? tenant.vapi_assistant_id.slice(0, 16) + '…' : '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Stripe customer</span><span className="adm-kv-value" style={{ fontFamily: 'monospace', fontSize: 11 }}>{tenant.stripe_customer_id ?? '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Active</span><span className="adm-kv-value">{tenant.is_active ? 'Yes' : 'No'}</span></div>
          </div>
        </div>

        {/* Usage */}
        <div className="adm-section" style={{ marginBottom: 0 }}>
          <div className="adm-section-title">Usage</div>
          <div className="adm-kv-list">
            <div className="adm-kv"><span className="adm-kv-key">Minutes used</span><span className="adm-kv-value">{tenant.minutes_used_this_period ?? 0} min</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Billing anchor</span><span className="adm-kv-value">{formatDate(tenant.billing_period_anchor)}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Business hours</span><span className="adm-kv-value">{tenant.business_hours_start ?? 9}:00 – {tenant.business_hours_end ?? 17}:00</span></div>
          </div>
        </div>

        {/* Calendar + KB */}
        <div className="adm-section" style={{ marginBottom: 0 }}>
          <div className="adm-section-title">Calendar & Knowledge Base</div>
          <div className="adm-kv-list">
            <div className="adm-kv"><span className="adm-kv-key">Calendar</span><span className="adm-kv-value" style={{ color: tenant.has_calendar ? 'var(--db-accent-text)' : 'var(--db-danger-text)' }}>{tenant.has_calendar ? 'Connected' : 'Not connected'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Timezone</span><span className="adm-kv-value">{tenant.calendar_timezone ?? '—'}</span></div>
            <div className="adm-kv"><span className="adm-kv-key">Appt duration</span><span className="adm-kv-value">{tenant.appointment_duration_minutes ?? 60} min</span></div>
            <div className="adm-kv"><span className="adm-kv-key">KB entries</span><span className="adm-kv-value">{data.kb_count}</span></div>
          </div>
        </div>
      </div>

      {/* Admin actions */}
      <div className="adm-section">
        <div className="adm-section-title">Admin Actions</div>
        <div className="adm-btn-group">
          <button
            className={`adm-btn ${tenant.is_active ? 'adm-btn-danger' : 'adm-btn-primary'}`}
            onClick={toggleActive}
            disabled={actionLoading}
          >
            {tenant.is_active ? 'Deactivate Tenant' : 'Activate Tenant'}
          </button>
          <button className="adm-btn adm-btn-secondary" onClick={reprompt} disabled={actionLoading}>
            Rebuild System Prompt
          </button>
          <button className="adm-btn adm-btn-secondary" onClick={enableSmartRouting} disabled={actionLoading}>
            Enable Smart Routing
          </button>
        </div>

        {/* Billing & comp */}
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--db-border)' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text-2)', marginBottom: 8 }}>
            Billing &amp; comp
            {tenant.billing_exempt && <span className="adm-badge adm-badge-green" style={{ marginLeft: 8 }}>Comped</span>}
          </div>
          <div className="adm-btn-group">
            {tenant.billing_exempt ? (
              <button className="adm-btn adm-btn-danger" onClick={() => setComp(false)} disabled={actionLoading}>Remove comp</button>
            ) : (
              <button className="adm-btn adm-btn-primary" onClick={() => setComp(true)} disabled={actionLoading}>Comp this tenant</button>
            )}
          </div>
          <div style={{ fontSize: 11, color: 'var(--db-muted)', margin: '6px 0 14px' }}>
            Comp keeps the line live with no trial expiry or subscription — and is excluded from revenue metrics.
          </div>

          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text-2)', marginBottom: 8 }}>
            Set plan (comp grant · current: {tenant.subscription_plan ?? 'none'})
          </div>
          {tenant.stripe_subscription_id ? (
            <div style={{ fontSize: 11, color: 'var(--db-muted)' }}>Has a Stripe subscription — change the plan in Stripe, not here.</div>
          ) : (
            <div className="adm-btn-group">
              {(['starter', 'pro', 'business'] as const).map(p => (
                <button key={p}
                  className={`adm-btn ${tenant.subscription_plan === p ? 'adm-btn-primary' : 'adm-btn-secondary'}`}
                  onClick={() => setPlan(p)} disabled={actionLoading} style={{ textTransform: 'capitalize' }}>
                  {p}
                </button>
              ))}
              <button className="adm-btn adm-btn-secondary" onClick={() => setPlan(null)} disabled={actionLoading}>None</button>
            </div>
          )}
        </div>

        {actionMsg && <p style={{ margin: '10px 0 0', fontSize: 13, color: actionMsg.startsWith('Failed') || actionMsg.startsWith('Network') ? 'var(--db-danger-text)' : 'var(--db-accent-text)' }}>{actionMsg}</p>}
      </div>

      {/* Recent calls */}
      <div className="adm-section">
        <div className="adm-section-title">Recent Calls ({recent_calls.length})</div>
        {recent_calls.length === 0 ? (
          <div className="adm-empty">No calls yet</div>
        ) : (
          <div className="adm-table-wrap">
            <table className="adm-table">
              <thead><tr><th>Date</th><th>Duration</th><th>Vapi Call ID</th></tr></thead>
              <tbody>
                {recent_calls.map(c => (
                  <tr key={c.id} className="no-hover">
                    <td>{formatDate(c.created_at)}</td>
                    <td>{formatDuration(c.duration_secs)}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--db-muted)' }}>{c.vapi_call_id ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent appointments */}
      <div className="adm-section">
        <div className="adm-section-title">Recent Appointments ({recent_appointments.length})</div>
        {recent_appointments.length === 0 ? (
          <div className="adm-empty">No appointments yet</div>
        ) : (
          <div className="adm-table-wrap">
            <table className="adm-table">
              <thead><tr><th>Appt Date</th><th>Caller</th><th>Phone</th><th>Service</th><th>Status</th></tr></thead>
              <tbody>
                {recent_appointments.map(a => (
                  <tr key={a.id} className="no-hover">
                    <td>{formatDate(a.appointment_datetime)}</td>
                    <td>{a.caller_name || '—'}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{a.caller_phone}</td>
                    <td>{a.service || '—'}</td>
                    <td><span className={`adm-badge ${a.status === 'confirmed' ? 'adm-badge-green' : a.status === 'cancelled' ? 'adm-badge-red' : 'adm-badge-gray'}`}>{a.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* KB entries */}
      {kb_entries.length > 0 && (
        <div className="adm-section">
          <div className="adm-section-title">Knowledge Base ({data.kb_count} entries)</div>
          <div className="adm-table-wrap">
            <table className="adm-table">
              <thead><tr><th>Type</th><th>Label</th><th>Added</th></tr></thead>
              <tbody>
                {kb_entries.map(e => (
                  <tr key={e.id} className="no-hover">
                    <td><span className="adm-badge adm-badge-gray">{e.type}</span></td>
                    <td>{e.label}</td>
                    <td className="adm-table-muted">{formatDate(e.added_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}
