'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { timeAgo, capitalize } from '../lib/format'
import { urgBadgeClass, statusBadgeClass } from '../lib/badges'
import { Toast } from '../components/Toast'
import { LoadingState, EmptyState } from '../components/PageStates'

import { authedFetch } from '@/lib/api'
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

function LeadsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [leads, setLeads]                 = useState<Lead[]>([])
  const [loading, setLoading]             = useState(true)
  const [toast, setToast]                 = useState<string | null>(null)
  const [filter, setFilter]               = useState<StatusFilter>('all')
  const [expanded, setExpanded]           = useState<string | null>(null)
  const [updating, setUpdating]           = useState<string | null>(null)

  const loadLeads = useCallback(async () => {
    const res = await authedFetch(`${API}/leads/${tenantId}?limit=200`)
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
      const res = await authedFetch(`${API}/leads/${tenantId}/${leadId}`, {
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
    return <LoadingState />
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
        <Toast message={toast} />

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
                className={`db-pill${filter === f ? ' active' : ''}`}
                onClick={() => setFilter(f)}
              >
                {capitalize(f)}
                <span style={{ opacity: 0.7 }}>{statusCounts[f]}</span>
              </button>
            ))}
            <button
              className="db-btn db-btn--ghost db-btn--sm"
              onClick={loadLeads}
              style={{ marginLeft: 'auto' }}
            >
              Refresh
            </button>
          </div>

          {/* Lead list */}
          {filtered.length === 0 ? (
            <div className="db-card">
              <EmptyState
                icon={
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                  </svg>
                }
                title={filter === 'all' ? 'No leads yet.' : `No ${filter} leads.`}
                sub={filter === 'all' ? 'They appear here after calls.' : undefined}
              />
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {filtered.map(lead => {
                const isOpen = expanded === lead.id
                const status = lead.status ?? 'new'
                return (
                  <div
                    key={lead.id}
                    className="db-card"
                    style={{ overflow: 'hidden' }}
                  >
                    {/* Row */}
                    <div
                      style={{
                        display: 'flex', alignItems: 'center', gap: 12,
                        padding: '12px 14px', cursor: 'pointer',
                      }}
                      onClick={() => setExpanded(isOpen ? null : lead.id)}
                    >
                      {/* Name / phone */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)' }}>
                          {lead.name || 'Unknown'}
                        </div>
                        {lead.phone && (
                          <div style={{ fontSize: 11, color: 'var(--db-muted)', marginTop: 1 }}>{lead.phone}</div>
                        )}
                      </div>

                      {/* Summary — hidden on small screens */}
                      {lead.summary && (
                        <div className="leads-row-summary">
                          {lead.summary}
                        </div>
                      )}

                      {/* Urgency */}
                      {lead.urgency && (
                        <span className={urgBadgeClass(lead.urgency)}>
                          {capitalize(lead.urgency)}
                        </span>
                      )}

                      {/* Status badge */}
                      <span className={statusBadgeClass(status)}>
                        {status}
                      </span>

                      {/* Time — last activity (falls back to creation) */}
                      <div style={{ fontSize: 11, color: 'var(--db-faint)', whiteSpace: 'nowrap', flexShrink: 0 }}>
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
                            borderTop: '1px solid var(--db-border-lt)', padding: '12px 14px',
                            display: 'flex', flexDirection: 'column', gap: 10,
                          }}>
                            {/* Key details */}
                            {lead.metadata?.key_details && Object.keys(lead.metadata.key_details).length > 0 && (
                              <div>
                                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--db-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Details</div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                                  {Object.entries(lead.metadata.key_details).map(([k, v]) => (
                                    <div key={k} className="db-chip">
                                      <b>{k}:</b> {v}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Suggested next step */}
                            {lead.metadata?.suggested_next_step && (
                              <div style={{ fontSize: 12, color: 'var(--db-text-2)' }}>
                                <span style={{ fontWeight: 600 }}>Next step:</span> {lead.metadata.suggested_next_step}
                              </div>
                            )}

                            {/* Status update */}
                            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 2, flexWrap: 'wrap' }}>
                              <span style={{ fontSize: 11, color: 'var(--db-muted)' }}>Mark as:</span>
                              {(['new', 'contacted', 'converted'] as const).map(s => (
                                <button
                                  key={s}
                                  className={`db-pill db-pill--sm${status === s ? ' active' : ''}`}
                                  disabled={status === s || updating === lead.id}
                                  onClick={() => updateStatus(lead.id, s)}
                                >
                                  {capitalize(s)}
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
