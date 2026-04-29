'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface Lead {
  id: string
  name?: string
  phone?: string
  summary?: string
  urgency?: string
  status?: string
  created_at: string
}

interface Call {
  id: string
  transcript?: string
  duration_secs?: number
  created_at: string
}

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
}

function timeAgo(iso: string): string {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return 'just now'
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function urgencyClass(u?: string): string {
  switch (u?.toLowerCase()) {
    case 'hot':  return 'hot'
    case 'warm': return 'warm'
    case 'cold': return 'cold'
    default:     return 'new'
  }
}

function initials(name?: string, phone?: string): string {
  if (name) return name.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
  return (phone ?? '??').slice(-2)
}

export default function DashboardPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const [tenant, setTenant]     = useState<Tenant | null>(null)
  const [leads, setLeads]       = useState<Lead[]>([])
  const [loading, setLoading]   = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [callMap, setCallMap]   = useState<Record<string, Call[]>>({})
  const [copied, setCopied]     = useState(false)

  const fetchLeads = useCallback(async () => {
    try {
      const res = await fetch(`${API}/leads/${tenantId}`)
      if (res.ok) setLeads(await res.json())
    } catch {}
  }, [tenantId])

  useEffect(() => {
    const init = async () => {
      try {
        const [tRes, lRes] = await Promise.all([
          fetch(`${API}/onboarding/status/${tenantId}`),
          fetch(`${API}/leads/${tenantId}`),
        ])
        if (tRes.ok) setTenant(await tRes.json())
        if (lRes.ok) setLeads(await lRes.json())
      } finally {
        setLoading(false)
      }
    }
    init()
    const interval = setInterval(fetchLeads, 30_000)
    return () => clearInterval(interval)
  }, [tenantId, fetchLeads])

  const toggleExpand = async (leadId: string) => {
    if (expandedId === leadId) { setExpandedId(null); return }
    setExpandedId(leadId)
    if (!callMap[leadId]) {
      try {
        const res = await fetch(`${API}/leads/${tenantId}/${leadId}`)
        if (res.ok) {
          const data = await res.json()
          setCallMap(prev => ({ ...prev, [leadId]: data.calls ?? [] }))
        }
      } catch {}
    }
  }

  const copyPhone = () => {
    if (tenant?.twilio_phone_number) {
      navigator.clipboard.writeText(tenant.twilio_phone_number)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
        <div style={{ fontSize: 13, color: 'var(--text-3)' }}>Loading…</div>
      </div>
    )
  }

  return (
    <div className="db-page">
      {/* Header */}
      <div className="db-header">
        <div>
          <div className="db-biz" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
            {tenant?.business_name ?? 'Dashboard'}
          </div>
          <div className="db-meta" style={{ marginTop: 6 }}>
            {tenant?.industry && (
              <span className="industry-badge">{tenant.industry}</span>
            )}
            {tenant?.twilio_phone_number && (
              <div className="phone-chip">
                {tenant.twilio_phone_number}
                <button className="copy-btn" onClick={copyPhone}>
                  {copied ? '✓ Copied' : 'Copy'}
                </button>
              </div>
            )}
          </div>
        </div>
        <Link href="/" style={{ fontSize: 12, color: 'var(--text-3)', textDecoration: 'none' }}>
          ← Back
        </Link>
      </div>

      {/* Body */}
      <div className="db-body">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div className="db-section-title">Lead Queue</div>
          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>Auto-refreshes every 30s</div>
        </div>

        {leads.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📞</div>
            <div className="empty-state-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
              No calls yet — share your number to get started
            </div>
            {tenant?.twilio_phone_number && (
              <div className="empty-state-sub" style={{ marginTop: 8 }}>
                Your number: <strong style={{ fontFamily: 'monospace' }}>{tenant.twilio_phone_number}</strong>
              </div>
            )}
          </div>
        ) : (
          <div className="leads-table">
            {leads.map(lead => (
              <div key={lead.id} className="lead-row" onClick={() => toggleExpand(lead.id)}>
                <div className="lead-row-main">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div className="av">{initials(lead.name, lead.phone)}</div>
                    <div>
                      <div className="lead-name">{lead.name ?? 'Unknown'}</div>
                      <div className="lead-phone">{lead.phone ?? '—'}</div>
                    </div>
                  </div>
                  <div>
                    {lead.urgency && (
                      <span className={`pill ${urgencyClass(lead.urgency)}`}>
                        {lead.urgency.charAt(0).toUpperCase() + lead.urgency.slice(1)}
                      </span>
                    )}
                  </div>
                  <div className="lead-summary">{lead.summary ?? '—'}</div>
                  <div className="lead-time">{timeAgo(lead.created_at)}</div>
                </div>

                <AnimatePresence>
                  {expandedId === lead.id && (
                    <motion.div className="lead-transcript"
                      initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }}>
                      {!callMap[lead.id] ? (
                        <div className="transcript-empty">Loading transcript…</div>
                      ) : callMap[lead.id].length === 0 ? (
                        <div className="transcript-empty">No call transcripts yet.</div>
                      ) : (
                        callMap[lead.id].map(call => (
                          <div key={call.id} style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 6 }}>
                              {timeAgo(call.created_at)}{call.duration_secs ? ` · ${call.duration_secs}s` : ''}
                            </div>
                            <div className="transcript-text">
                              {call.transcript ?? 'No transcript available.'}
                            </div>
                          </div>
                        ))
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
