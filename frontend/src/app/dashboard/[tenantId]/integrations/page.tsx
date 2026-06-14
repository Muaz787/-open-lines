'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { Toast } from '../components/Toast'
import { LoadingState } from '../components/PageStates'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  subscription_plan?: string
  subscription_status?: string
}

interface HubSpotStatus {
  connected: boolean
  portal_id?: string | null
  account_name?: string | null
  connected_at?: string | null
}

function HubSpotIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" fill="#FF7A59"/>
      <path
        d="M20.5 10.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM20.5 10.5v3.08M14.5 13.58A5.5 5.5 0 1 0 20 19m0 0H14.5m5.5 0 2.5 2.5M20 19l2.5-2.5"
        stroke="#fff"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function LockIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
      <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
    </svg>
  )
}

function IntegrationsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [tenant, setTenant]           = useState<Tenant | null>(null)
  const [hsStatus, setHsStatus]       = useState<HubSpotStatus | null>(null)
  const [loading, setLoading]         = useState(true)
  const [disconnecting, setDisconnecting] = useState(false)
  const [toast, setToast]             = useState<string | null>(null)

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  useEffect(() => {
    const init = async () => {
      try {
        const [tRes, hRes] = await Promise.all([
          fetch(`${API}/onboarding/status/${tenantId}`),
          fetch(`${API}/hubspot/status/${tenantId}`),
        ])
        if (tRes.ok) setTenant(await tRes.json())
        if (hRes.ok) setHsStatus(await hRes.json())
      } finally {
        setLoading(false)
      }
    }
    init()

    // Handle OAuth redirect back
    const params = new URLSearchParams(window.location.search)
    const hs = params.get('hubspot')
    if (hs === 'connected') {
      showToast('HubSpot connected!')
      fetch(`${API}/hubspot/status/${tenantId}`).then(r => r.ok && r.json()).then(d => d && setHsStatus(d))
      window.history.replaceState({}, '', window.location.pathname)
    } else if (hs === 'error') {
      showToast('HubSpot connection failed. Please try again.')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [tenantId])

  const disconnectHubSpot = async () => {
    if (!confirm('Disconnect HubSpot? Call summaries will no longer sync to your CRM.')) return
    setDisconnecting(true)
    try {
      const res = await fetch(`${API}/hubspot/disconnect/${tenantId}`, { method: 'POST' })
      if (res.ok) {
        setHsStatus({ connected: false })
        showToast('HubSpot disconnected.')
      } else {
        showToast('Disconnect failed — try again.')
      }
    } catch {
      showToast('Network error — try again.')
    } finally {
      setDisconnecting(false)
    }
  }

  if (loading) return <LoadingState />

  // Plan gating: Pro ($199) and Business ($379) only
  const plan   = tenant?.subscription_plan?.toLowerCase() ?? ''
  const status = tenant?.subscription_status ?? ''
  const isPaidEligible = (
    ['pro', 'business'].includes(plan) &&
    ['active', 'trialing', 'canceling'].includes(status)
  )

  return (
    <>
      <Toast message={toast} />

      <div className="db-topbar">
        <span className="db-topbar-title">Integrations</span>
        {tenant?.twilio_phone_number && (
          <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>
            <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: 'var(--db-accent)', marginRight: 5 }} />
            {tenant.twilio_phone_number}
          </div>
        )}
      </div>

      <div className="db-content">
        <div style={{ maxWidth: 600 }}>

          {/* Header */}
          <div style={{ marginBottom: 24 }}>
            <div className="db-page-heading" style={{ marginBottom: 4 }}>App Integrations</div>
            <div style={{ fontSize: 13, color: 'var(--db-muted)', lineHeight: 1.6 }}>
              Connect your business tools so Open Lines automatically syncs contacts and call summaries after every call.
            </div>
          </div>

          {/* Upgrade gate */}
          {!isPaidEligible && (
            <div className="db-card" style={{
              padding: '18px 20px', marginBottom: 20,
              display: 'flex', alignItems: 'center', gap: 14,
              background: 'var(--db-bg-2)',
            }}>
              <div style={{ color: 'var(--db-muted)', flexShrink: 0 }}>
                <LockIcon />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 3 }}>
                  Integrations require a Pro or Business plan
                </div>
                <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>
                  Upgrade to unlock HubSpot CRM sync and future integrations.
                </div>
              </div>
              <Link
                href={`/dashboard/${tenantId}/subscription`}
                className="db-btn db-btn--accent-ghost"
                style={{ flexShrink: 0, fontSize: 12 }}
              >
                Upgrade
              </Link>
            </div>
          )}

          {/* HubSpot card */}
          <div className="db-card" style={{ overflow: 'hidden' }}>
            {/* Card header */}
            <div style={{
              padding: '18px 20px',
              borderBottom: '1px solid var(--db-border-lt)',
              display: 'flex', alignItems: 'flex-start', gap: 14,
            }}>
              <div style={{ flexShrink: 0, marginTop: 2 }}>
                <HubSpotIcon />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--db-text)', marginBottom: 4 }}>
                  HubSpot CRM
                </div>
                <div style={{ fontSize: 12, color: 'var(--db-muted)', lineHeight: 1.6, marginBottom: 8 }}>
                  After every call, Open Lines automatically creates or updates a contact in HubSpot
                  and adds an AI-generated call summary as a note — including caller details, urgency,
                  and suggested next steps.
                </div>

                {/* Feature bullets */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {[
                    'Auto-create or update contacts from caller phone numbers',
                    'Add structured call summaries as HubSpot notes',
                    'Urgency, intent, and next steps synced automatically',
                    'No full transcripts sent — privacy by default',
                  ].map(f => (
                    <div key={f} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                      <span style={{ color: 'var(--db-accent-text)', fontSize: 11, flexShrink: 0 }}>✓</span>
                      <span style={{ fontSize: 12, color: 'var(--db-text-2)' }}>{f}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Card footer — connection status / actions */}
            <div style={{
              padding: '14px 20px',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              flexWrap: 'wrap', gap: 12,
            }}>
              {hsStatus?.connected ? (
                <>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: 13, color: 'var(--db-accent-text)' }}>✓</span>
                      <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--db-accent-text)' }}>
                        Connected
                      </span>
                    </div>
                    {(hsStatus.account_name || hsStatus.portal_id) && (
                      <div style={{ fontSize: 11, color: 'var(--db-faint)', marginTop: 2 }}>
                        {hsStatus.account_name && <span>{hsStatus.account_name}</span>}
                        {hsStatus.account_name && hsStatus.portal_id && <span> · </span>}
                        {hsStatus.portal_id && <span>Portal {hsStatus.portal_id}</span>}
                      </div>
                    )}
                  </div>
                  <button
                    className="db-btn db-btn--ghost db-btn--sm"
                    onClick={disconnectHubSpot}
                    disabled={disconnecting}
                  >
                    {disconnecting ? 'Disconnecting…' : 'Disconnect'}
                  </button>
                </>
              ) : isPaidEligible ? (
                <a
                  href={`${API}/hubspot/connect?tenant_id=${tenantId}`}
                  className="db-btn db-btn--dark"
                  style={{ fontSize: 13 }}
                >
                  Connect HubSpot
                </a>
              ) : (
                <div style={{ fontSize: 12, color: 'var(--db-faint)' }}>
                  Available on Pro and Business plans
                </div>
              )}
            </div>
          </div>

          {/* More integrations coming soon */}
          <div style={{
            marginTop: 32,
            padding: '16px 20px',
            background: 'var(--db-bg-2)',
            borderRadius: 'var(--db-r-md)',
            border: '1px dashed var(--db-border)',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--db-text-2)', marginBottom: 4 }}>
              More integrations coming soon
            </div>
            <div style={{ fontSize: 12, color: 'var(--db-faint)' }}>
              Google Sheets, Slack, Zapier, and more.
            </div>
          </div>

        </div>
      </div>
    </>
  )
}

export default function IntegrationsPageWrapper() {
  return <IntegrationsPage />
}
