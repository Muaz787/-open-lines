'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface Lead {
  id: string
  name?: string
  phone?: string
  summary?: string
  urgency?: string
  status?: string
  created_at: string
  updated_at?: string
  metadata?: {
    key_details?: Record<string, string>
    suggested_next_step?: string
  }
}

type StatusFilter = 'all' | 'new' | 'contacted' | 'converted'

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return 'just now'
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function urgencyColor(u?: string) {
  if (u === 'high') return '#ef4444'
  if (u === 'medium') return '#f59e0b'
  return '#6b7280'
}

function LeadsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [leads, setLeads]                 = useState<Lead[]>([])
  const [loading, setLoading]             = useState(true)
  const [toast, setToast]                 = useState<string | null>(null)
  const [filter, setFilter]               = useState<StatusFilter>('all')
  const [expanded, setExpanded]           = useState<string | null>(null)
  const [updating, setUpdating]           = useState<string | null>(null)

  const loadLeads = useCallback(async () => {
    const res = await fetch(`${API}/leads/${tenantId}?limit=200`)
    if (res.ok) setLeads(await res.json())
  }, [tenantId])

  useEffect(() => {
    const init = async () => {
      try { await loadLeads() } finally { setLoading(false) }
    }
    init()
  }, [loadLeads])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  const updateStatus = async (leadId: string, status: string) => {
    setUpdating(leadId)
    try {
      const res = await fetch(`${API}/leads/${tenantId}/${leadId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      if (res.ok) {
        setLeads(prev => prev.map(l => l.id === leadId ? { ...l, status } : l))
        showToast('Status updated')
      }
    } catch {
      showToast('Update failed')
    } finally {
      setUpdating(null)
    }
  }

  const filtered = leads.filter(l => {
    if (filter === 'all') return true
    return (l.status ?? 'new') === filter
  })

  const IconChevron = ({ open }: { open: boolean }) => (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" width="12" height="12"
      style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
      <path d="M3 5.5l4.5 4 4.5-4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f4f3f0' }}>
        <div style={{ fontSize: 13, color: '#888' }}>Loading…</div>
      </div>
    )
  }

  const statusCounts = {
    all: leads.length,
    new: leads.filter(l => !l.status || l.status === 'new').length,
    contacted: leads.filter(l => l.status === 'contacted').length,
    converted: leads.filter(l => l.status === 'converted').length,
  }

  return (
    <>

        {/* Toast */}
        <AnimatePresence>
          {toast && (
            <motion.div
              initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
              style={{
                position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)',
                background: '#16161a', color: '#fff', padding: '10px 20px',
                borderRadius: 8, fontSize: 13, fontWeight: 500, zIndex: 300,
                boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
              }}
            >
              {toast}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Desktop topbar */}
        <div className="db-topbar">
          <span className="db-topbar-title">Leads</span>
        </div>

        {/* Content */}
        <div className="db-content">

          {/* Filter tabs */}
          <div className="leads-filter-bar">
            {(['all', 'new', 'contacted', 'converted'] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  padding: '5px 12px', borderRadius: 6, fontSize: 12, fontWeight: 500,
                  border: '1px solid',
                  borderColor: filter === f ? '#3dba72' : '#e8e6e0',
                  background: filter === f ? '#eafaf2' : '#fff',
                  color: filter === f ? '#1a7a45' : '#666',
                  cursor: 'pointer',
                  fontFamily: 'var(--font-dm), sans-serif',
                }}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
                <span style={{ marginLeft: 5, opacity: 0.7 }}>{statusCounts[f]}</span>
              </button>
            ))}
            <button
              onClick={loadLeads}
              style={{
                marginLeft: 'auto', padding: '5px 12px', borderRadius: 6, fontSize: 12,
                border: '1px solid #e8e6e0', background: '#fff', color: '#666',
                cursor: 'pointer', fontFamily: 'var(--font-dm), sans-serif',
              }}
            >
              Refresh
            </button>
          </div>

          {/* Lead list */}
          {filtered.length === 0 ? (
            <div style={{
              background: '#fff', border: '1px solid #e8e6e0', borderRadius: 10,
              padding: '40px 20px', textAlign: 'center', color: '#aaa', fontSize: 13,
            }}>
              {filter === 'all' ? 'No leads yet — they appear here after calls.' : `No ${filter} leads.`}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {filtered.map(lead => {
                const isOpen = expanded === lead.id
                const status = lead.status ?? 'new'
                return (
                  <div
                    key={lead.id}
                    style={{
                      background: '#fff', border: '1px solid #e8e6e0',
                      borderRadius: 10, overflow: 'hidden',
                    }}
                  >
                    {/* Row */}
                    <div
                      style={{
                        display: 'flex', alignItems: 'center', gap: 12,
                        padding: '12px 14px', cursor: 'pointer',
                      }}
                      onClick={() => setExpanded(isOpen ? null : lead.id)}
                    >
                      {/* Urgency dot */}
                      <div style={{
                        width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                        background: urgencyColor(lead.urgency),
                      }} />

                      {/* Name / phone */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#16161a' }}>
                          {lead.name || 'Unknown'}
                        </div>
                        {lead.phone && (
                          <div style={{ fontSize: 11, color: '#888', marginTop: 1 }}>{lead.phone}</div>
                        )}
                      </div>

                      {/* Summary — hidden on small screens */}
                      {lead.summary && (
                        <div className="leads-row-summary">
                          {lead.summary}
                        </div>
                      )}

                      {/* Status badge */}
                      <span style={{
                        fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 4,
                        textTransform: 'uppercase', letterSpacing: '0.04em',
                        background: status === 'converted' ? '#eafaf2' : status === 'contacted' ? '#eff6ff' : '#fef3c7',
                        color: status === 'converted' ? '#1a7a45' : status === 'contacted' ? '#1d4ed8' : '#92400e',
                      }}>
                        {status}
                      </span>

                      {/* Time — last activity (falls back to creation) */}
                      <div style={{ fontSize: 11, color: '#aaa', whiteSpace: 'nowrap', flexShrink: 0 }}>
                        {timeAgo(lead.updated_at || lead.created_at)}
                      </div>

                      <IconChevron open={isOpen} />
                    </div>

                    {/* Expanded details */}
                    <AnimatePresence>
                      {isOpen && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          style={{ overflow: 'hidden' }}
                        >
                          <div style={{
                            borderTop: '1px solid #f0ede8', padding: '12px 14px',
                            display: 'flex', flexDirection: 'column', gap: 10,
                          }}>
                            {/* Key details */}
                            {lead.metadata?.key_details && Object.keys(lead.metadata.key_details).length > 0 && (
                              <div>
                                <div style={{ fontSize: 11, fontWeight: 600, color: '#888', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Details</div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                                  {Object.entries(lead.metadata.key_details).map(([k, v]) => (
                                    <div key={k} style={{
                                      fontSize: 12, padding: '3px 8px', borderRadius: 5,
                                      background: '#f4f3f0', color: '#444',
                                    }}>
                                      <span style={{ fontWeight: 600 }}>{k}:</span> {v}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Suggested next step */}
                            {lead.metadata?.suggested_next_step && (
                              <div style={{ fontSize: 12, color: '#555' }}>
                                <span style={{ fontWeight: 600 }}>Next step:</span> {lead.metadata.suggested_next_step}
                              </div>
                            )}

                            {/* Status update */}
                            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 2 }}>
                              <span style={{ fontSize: 11, color: '#888' }}>Mark as:</span>
                              {(['new', 'contacted', 'converted'] as const).map(s => (
                                <button
                                  key={s}
                                  disabled={status === s || updating === lead.id}
                                  onClick={() => updateStatus(lead.id, s)}
                                  style={{
                                    padding: '4px 10px', borderRadius: 5, fontSize: 11, fontWeight: 500,
                                    border: '1px solid',
                                    borderColor: status === s ? '#3dba72' : '#e8e6e0',
                                    background: status === s ? '#eafaf2' : '#fff',
                                    color: status === s ? '#1a7a45' : '#555',
                                    cursor: status === s ? 'default' : 'pointer',
                                    opacity: updating === lead.id ? 0.6 : 1,
                                    fontFamily: 'var(--font-dm), sans-serif',
                                  }}
                                >
                                  {s.charAt(0).toUpperCase() + s.slice(1)}
                                </button>
                              ))}
                            </div>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )
              })}
            </div>
          )}
        </div>
    </>
  )
}

export default function LeadsPageWrapper() {
  return <LeadsPage />
}
