'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { Toast } from '../components/Toast'
import { LoadingState } from '../components/PageStates'

import { authedFetch } from '@/lib/api'
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// Zapier integration is paused — set to true to bring the API key UI back.
const ZAPIER_ENABLED = false

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

interface ApiKey {
  id: string
  key_prefix: string
  label?: string | null
  last_used_at?: string | null
  revoked_at?: string | null
  created_at: string
}

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

interface SlackStatus {
  connected: boolean
  team_name?: string | null
  channel_name?: string | null
  connected_at?: string | null
}

function HubSpotIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" fill="#FF7A59"/>
      <path
        d="M20.5 10.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM20.5 10.5v3.08M14.5 13.58A5.5 5.5 0 1 0 20 19m0 0H14.5m5.5 0 2.5 2.5M20 19l2.5-2.5"
        stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
      />
    </svg>
  )
}

function SlackIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" fill="#4A154B"/>
      <path d="M11 17.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zm0 0H20" stroke="#E01E5A" strokeWidth="2" strokeLinecap="round"/>
      <path d="M14.5 21a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3zm0 0V12" stroke="#ECB22E" strokeWidth="2" strokeLinecap="round"/>
      <path d="M21 14.5a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0zm0 0H12" stroke="#2EB67D" strokeWidth="2" strokeLinecap="round"/>
      <path d="M17.5 11a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm0 0V20" stroke="#36C5F0" strokeWidth="2" strokeLinecap="round"/>
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

  const [tenant, setTenant]                   = useState<Tenant | null>(null)
  const [hsStatus, setHsStatus]               = useState<HubSpotStatus | null>(null)
  const [slackStatus, setSlackStatus]         = useState<SlackStatus | null>(null)
  const [loading, setLoading]                 = useState(true)
  const [hsDisconnecting, setHsDisconnecting] = useState(false)
  const [slDisconnecting, setSlDisconnecting] = useState(false)
  const [toast, setToast]                     = useState<string | null>(null)

  const [apiKeys, setApiKeys]                 = useState<ApiKey[]>([])
  const [newKey, setNewKey]                   = useState<string | null>(null)
  const [keyLabel, setKeyLabel]               = useState('')
  const [creatingKey, setCreatingKey]         = useState(false)

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  useEffect(() => {
    const init = async () => {
      try {
        const [tRes, hRes, sRes] = await Promise.all([
          authedFetch(`${API}/onboarding/status/${tenantId}`),
          authedFetch(`${API}/hubspot/status/${tenantId}`),
          authedFetch(`${API}/slack/status/${tenantId}`),
        ])
        if (tRes.ok) setTenant(await tRes.json())
        if (hRes.ok) setHsStatus(await hRes.json())
        if (sRes.ok) setSlackStatus(await sRes.json())
        if (ZAPIER_ENABLED) {
          try {
            const kRes = await authedFetch(`${API}/zapier/keys/${tenantId}`, { headers: await authHeaders() })
            if (kRes.ok) setApiKeys((await kRes.json()).keys || [])
          } catch {}
        }
      } finally {
        setLoading(false)
      }
    }
    init()

    // Handle OAuth redirects back
    const params = new URLSearchParams(window.location.search)
    const hs = params.get('hubspot')
    const sl = params.get('slack')

    if (hs === 'connected') {
      showToast('HubSpot connected!')
      authedFetch(`${API}/hubspot/status/${tenantId}`).then(r => r.ok && r.json()).then(d => d && setHsStatus(d))
      window.history.replaceState({}, '', window.location.pathname)
    } else if (hs === 'error') {
      showToast('HubSpot connection failed. Please try again.')
      window.history.replaceState({}, '', window.location.pathname)
    }

    if (sl === 'connected') {
      showToast('Slack connected!')
      authedFetch(`${API}/slack/status/${tenantId}`).then(r => r.ok && r.json()).then(d => d && setSlackStatus(d))
      window.history.replaceState({}, '', window.location.pathname)
    } else if (sl === 'error') {
      showToast('Slack connection failed. Please try again.')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [tenantId])

  // Owner-authenticated connect: mint the OAuth URL via authedFetch, then redirect.
  const startConnect = async (path: string) => {
    try {
      const res = await authedFetch(`${API}${path}`)
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.url) window.location.href = data.url
      // On 401 authedFetch already redirects to /login.
    } catch {}
  }

  const disconnectHubSpot = async () => {
    if (!confirm('Disconnect HubSpot? Call summaries will no longer sync to your CRM.')) return
    setHsDisconnecting(true)
    try {
      const res = await authedFetch(`${API}/hubspot/disconnect/${tenantId}`, { method: 'POST' })
      if (res.ok) { setHsStatus({ connected: false }); showToast('HubSpot disconnected.') }
      else showToast('Disconnect failed — try again.')
    } catch { showToast('Network error — try again.') }
    finally { setHsDisconnecting(false) }
  }

  const disconnectSlack = async () => {
    if (!confirm('Disconnect Slack? Call notifications will stop being sent to your channel.')) return
    setSlDisconnecting(true)
    try {
      const res = await authedFetch(`${API}/slack/disconnect/${tenantId}`, { method: 'POST' })
      if (res.ok) { setSlackStatus({ connected: false }); showToast('Slack disconnected.') }
      else showToast('Disconnect failed — try again.')
    } catch { showToast('Network error — try again.') }
    finally { setSlDisconnecting(false) }
  }

  const createApiKey = async () => {
    setCreatingKey(true)
    setNewKey(null)
    try {
      const res = await authedFetch(`${API}/zapier/keys/${tenantId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
        body: JSON.stringify({ label: keyLabel.trim() || null }),
      })
      if (res.ok) {
        const data = await res.json()
        setNewKey(data.api_key)
        setKeyLabel('')
        const kRes = await authedFetch(`${API}/zapier/keys/${tenantId}`, { headers: await authHeaders() })
        if (kRes.ok) setApiKeys((await kRes.json()).keys || [])
      } else {
        showToast('Could not create API key.')
      }
    } catch { showToast('Network error — try again.') }
    finally { setCreatingKey(false) }
  }

  const revokeApiKey = async (id: string) => {
    if (!confirm('Revoke this API key? Any Zap or app using it will stop working immediately.')) return
    try {
      const res = await authedFetch(`${API}/zapier/keys/${tenantId}/${id}`, { method: 'DELETE', headers: await authHeaders() })
      if (res.ok) {
        setApiKeys(keys => keys.map(k => k.id === id ? { ...k, revoked_at: new Date().toISOString() } : k))
        showToast('API key revoked.')
      } else showToast('Revoke failed — try again.')
    } catch { showToast('Network error — try again.') }
  }

  if (loading) return <LoadingState />

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
        <div className="db-form-grid">

          {/* Header */}
          <div className="db-form-wide">
            <div className="db-page-heading" style={{ marginBottom: 4 }}>App Integrations</div>
            <div style={{ fontSize: 14, color: 'var(--db-muted)', lineHeight: 1.6 }}>
              Connect your business tools so Open Lines automatically syncs contacts and call summaries after every call.
            </div>
          </div>

          {/* Upgrade gate */}
          {!isPaidEligible && (
            <div className="db-card db-form-wide" style={{
              padding: '18px 20px',
              display: 'flex', alignItems: 'center', gap: 14,
              background: 'var(--db-bg-2)',
            }}>
              <div style={{ color: 'var(--db-muted)', flexShrink: 0 }}><LockIcon /></div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 3 }}>
                  Integrations require a Pro or Business plan
                </div>
                <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>
                  Upgrade to unlock HubSpot CRM sync, Slack notifications, and future integrations.
                </div>
              </div>
              <Link href={`/dashboard/${tenantId}/subscription`} className="db-btn db-btn--accent-ghost" style={{ flexShrink: 0, fontSize: 12 }}>
                Upgrade
              </Link>
            </div>
          )}

          {/* HubSpot card */}
          <IntegrationCard
            icon={<HubSpotIcon />}
            title="HubSpot CRM"
            description="After every call, Open Lines automatically creates or updates a contact in HubSpot and adds an AI-generated call summary as a note — including caller details, urgency, and suggested next steps."
            features={[
              'Auto-create or update contacts from caller phone numbers',
              'Add structured call summaries as HubSpot notes',
              'Urgency, intent, and next steps synced automatically',
              'No full transcripts sent — privacy by default',
            ]}
            connected={hsStatus?.connected ?? false}
            connectedLabel={
              hsStatus?.connected
                ? [hsStatus.account_name, hsStatus.portal_id ? `Portal ${hsStatus.portal_id}` : null].filter(Boolean).join(' · ')
                : null
            }
            isPaidEligible={isPaidEligible}
            onConnect={() => startConnect(`/hubspot/connect?tenant_id=${tenantId}`)}
            connectLabel="Connect HubSpot"
            onDisconnect={disconnectHubSpot}
            disconnecting={hsDisconnecting}
          />

          {/* Slack card */}
          <div>
            <IntegrationCard
              icon={<SlackIcon />}
              title="Slack"
              description="Get a Slack message in your chosen channel after every call — caller details, urgency, AI summary, and suggested next step delivered instantly."
              features={[
                'Instant call notifications in any Slack channel',
                'Caller name, phone, and urgency at a glance',
                'AI-generated summary and suggested next step',
                'One message per call — no noise, no transcripts',
              ]}
              connected={slackStatus?.connected ?? false}
              connectedLabel={
                slackStatus?.connected
                  ? [slackStatus.team_name, slackStatus.channel_name].filter(Boolean).join(' · ')
                  : null
              }
              isPaidEligible={isPaidEligible}
              onConnect={() => startConnect(`/slack/connect?tenant_id=${tenantId}`)}
              connectLabel="Connect Slack"
              onDisconnect={disconnectSlack}
              disconnecting={slDisconnecting}
            />
          </div>

          {/* Zapier / API keys — paused (hidden behind ZAPIER_ENABLED) */}
          {ZAPIER_ENABLED && (
          <div className="db-form-wide">
            <div className="db-card" style={{ overflow: 'hidden' }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--db-border-lt)' }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--db-text)', marginBottom: 4 }}>
                  Zapier &amp; API Access
                </div>
                <div style={{ fontSize: 12, color: 'var(--db-muted)', lineHeight: 1.6, marginBottom: 8 }}>
                  Generate an API key to connect Open Lines to 6,000+ apps via Zapier — push new leads,
                  call summaries, bookings, and deposits to your CRM, spreadsheets, and more.
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {[
                    'Trigger Zaps on calls, leads, bookings, and deposits',
                    'Send the API key + base URL below to Zapier',
                    'Revoke a key anytime to instantly disconnect',
                  ].map(f => (
                    <div key={f} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                      <span style={{ color: 'var(--db-accent-text)', fontSize: 11, flexShrink: 0 }}>✓</span>
                      <span style={{ fontSize: 12, color: 'var(--db-text-2)' }}>{f}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ padding: '14px 20px' }}>
                {!isPaidEligible ? (
                  <div style={{ fontSize: 12, color: 'var(--db-faint)' }}>Available on Pro and Business plans</div>
                ) : (
                  <>
                    {/* API base URL */}
                    <div style={{ marginBottom: 14 }}>
                      <div style={{ fontSize: 11, color: 'var(--db-muted)', marginBottom: 4 }}>API base URL</div>
                      <code style={{
                        display: 'block', fontSize: 12, padding: '8px 10px', borderRadius: 6,
                        background: 'var(--db-bg-2)', border: '1px solid var(--db-border)', wordBreak: 'break-all',
                      }}>{API}</code>
                    </div>

                    {/* Newly created key (shown once) */}
                    {newKey && (
                      <div style={{
                        marginBottom: 14, padding: '12px 14px', borderRadius: 8,
                        background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.3)',
                      }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--db-text)', marginBottom: 6 }}>
                          Copy your API key now — it won&rsquo;t be shown again.
                        </div>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          <code style={{
                            flex: 1, fontSize: 12, padding: '8px 10px', borderRadius: 6,
                            background: 'var(--db-bg)', border: '1px solid var(--db-border)', wordBreak: 'break-all',
                          }}>{newKey}</code>
                          <button className="db-btn db-btn--dark db-btn--sm"
                            onClick={() => { navigator.clipboard?.writeText(newKey); showToast('Copied to clipboard.') }}>
                            Copy
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Create form */}
                    <div style={{ display: 'flex', gap: 8, marginBottom: apiKeys.length ? 16 : 0 }}>
                      <input className="db-input" placeholder="Key label (e.g. Zapier)" value={keyLabel}
                        onChange={e => setKeyLabel(e.target.value)} style={{ flex: 1 }} maxLength={40} />
                      <button className="db-btn db-btn--dark db-btn--sm" onClick={createApiKey} disabled={creatingKey}>
                        {creatingKey ? 'Generating…' : 'Generate key'}
                      </button>
                    </div>

                    {/* Existing keys */}
                    {apiKeys.length > 0 && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {apiKeys.map(k => {
                          const revoked = !!k.revoked_at
                          return (
                            <div key={k.id} style={{
                              display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                              padding: '8px 12px', borderRadius: 6, border: '1px solid var(--db-border-lt)',
                              opacity: revoked ? 0.5 : 1,
                            }}>
                              <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--db-text)' }}>
                                  {k.label || 'API key'}{' '}
                                  <code style={{ fontSize: 11, color: 'var(--db-faint)' }}>{k.key_prefix}…</code>
                                </div>
                                <div style={{ fontSize: 11, color: 'var(--db-faint)' }}>
                                  {revoked ? 'Revoked' : (k.last_used_at ? 'Active · in use' : 'Active · never used')}
                                </div>
                              </div>
                              {!revoked && (
                                <button className="db-btn db-btn--ghost db-btn--sm" onClick={() => revokeApiKey(k.id)}>
                                  Revoke
                                </button>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
          )}

          {/* Coming soon */}
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
              Google Sheets, QuickBooks, and more.
            </div>
          </div>

        </div>
      </div>
    </>
  )
}

// ── Shared integration card ────────────────────────────────────────────────

interface IntegrationCardProps {
  icon: React.ReactNode
  title: string
  description: string
  features: string[]
  connected: boolean
  connectedLabel: string | null
  isPaidEligible: boolean
  onConnect: () => void
  connectLabel: string
  onDisconnect: () => void
  disconnecting: boolean
}

function IntegrationCard({
  icon, title, description, features,
  connected, connectedLabel, isPaidEligible,
  onConnect, connectLabel, onDisconnect, disconnecting,
}: IntegrationCardProps) {
  return (
    <div className="db-card" style={{ overflow: 'hidden', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        padding: '20px 22px',
        borderBottom: '1px solid var(--db-border-lt)',
        display: 'flex', alignItems: 'flex-start', gap: 14, flex: 1,
      }}>
        <div style={{ flexShrink: 0, marginTop: 2 }}>{icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--db-text)', marginBottom: 5 }}>{title}</div>
          <div style={{ fontSize: 13, color: 'var(--db-muted)', lineHeight: 1.6, marginBottom: 10 }}>{description}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {features.map(f => (
              <div key={f} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span style={{ color: 'var(--db-accent-text)', fontSize: 12, flexShrink: 0 }}>✓</span>
                <span style={{ fontSize: 13, color: 'var(--db-text-2)' }}>{f}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{
        padding: '14px 22px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexWrap: 'wrap', gap: 12,
      }}>
        {connected ? (
          <>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 13, color: 'var(--db-accent-text)' }}>✓</span>
                <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--db-accent-text)' }}>Connected</span>
              </div>
              {connectedLabel && (
                <div style={{ fontSize: 11, color: 'var(--db-faint)', marginTop: 2 }}>{connectedLabel}</div>
              )}
            </div>
            <button className="db-btn db-btn--ghost db-btn--sm" onClick={onDisconnect} disabled={disconnecting}>
              {disconnecting ? 'Disconnecting…' : 'Disconnect'}
            </button>
          </>
        ) : isPaidEligible ? (
          <button type="button" onClick={onConnect} className="db-btn db-btn--dark" style={{ fontSize: 13 }}>
            {connectLabel}
          </button>
        ) : (
          <div style={{ fontSize: 12, color: 'var(--db-faint)' }}>Available on Pro and Business plans</div>
        )}
      </div>
    </div>
  )
}

export default function IntegrationsPageWrapper() {
  return <IntegrationsPage />
}
