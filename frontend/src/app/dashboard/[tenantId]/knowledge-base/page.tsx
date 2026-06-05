'use client'

import { useState, useEffect, useRef, useCallback, Suspense } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { supabase } from '@/lib/supabase'
import MicButton from '@/app/components/MicButton'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

interface KbEntry {
  id: string
  type: 'file' | 'text' | 'website'
  label: string
  preview?: string
  added_at: string
}

interface UploadResult {
  file: string
  status: string
  vectors_stored?: number
  reason?: string
}

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  website_url?: string
  last_crawl_at?: string
  subscription_plan?: string
  subscription_status?: string
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return 'just now'
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function KnowledgeBasePage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [tenant, setTenant]                 = useState<Tenant | null>(null)
  const [loading, setLoading]               = useState(true)
  const [toast, setToast]                   = useState<string | null>(null)

  const [entries, setEntries]             = useState<KbEntry[]>([])
  const [urlInput, setUrlInput]           = useState('')
  const [syncLoading, setSyncLoading]     = useState(false)
  const [dragging, setDragging]           = useState(false)
  const [uploadLoading, setUploadLoading] = useState(false)
  const [uploadResults, setUploadResults] = useState<UploadResult[]>([])
  const fileInputRef                       = useRef<HTMLInputElement>(null)
  const [text, setText]                   = useState('')
  const [textLoading, setTextLoading]     = useState(false)
  const [clearLoading, setClearLoading]   = useState(false)
  const [repairLoading, setRepairLoading] = useState(false)
  const [deletingId, setDeletingId]       = useState<string | null>(null)

  const loadEntries = useCallback(async () => {
    const ah = await authHeaders()
    fetch(`${API}/knowledge/entries/${tenantId}`, { headers: ah })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.entries) setEntries(d.entries) })
      .catch(() => {})
  }, [tenantId])

  useEffect(() => {
    const init = async () => {
      try {
        const tRes = await fetch(`${API}/onboarding/status/${tenantId}`)
        if (tRes.ok) {
          const t = await tRes.json()
          setTenant(t)
          setUrlInput(t.website_url ?? '')
        }
      } finally {
        setLoading(false)
      }
    }
    init()
    loadEntries()
  }, [tenantId, loadEntries])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  const deleteEntry = async (id: string) => {
    setDeletingId(id)
    try {
      const ah = await authHeaders()
      await fetch(`${API}/knowledge/entries/${tenantId}/${id}`, { method: 'DELETE', headers: ah })
      setEntries(prev => prev.filter(e => e.id !== id))
      showToast('Source removed')
    } catch {}
    finally { setDeletingId(null) }
  }

  const repairPrompt = async () => {
    setRepairLoading(true)
    try {
      const ah  = await authHeaders()
      const res = await fetch(`${API}/knowledge/repair-prompt/${tenantId}`, { method: 'POST', headers: ah })
      const data = await res.json()
      showToast(res.ok ? '✓ AI prompt updated' : data.detail || 'Update failed')
    } catch {
      showToast('Network error — try again')
    } finally {
      setRepairLoading(false)
    }
  }

  const syncWebsite = async () => {
    if (!urlInput.trim()) return
    setSyncLoading(true)
    try {
      if (urlInput.trim() !== tenant?.website_url) {
        const ah = await authHeaders()
        await fetch(`${API}/knowledge/website/${tenantId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', ...ah },
          body: JSON.stringify({ website_url: urlInput.trim() }),
        })
      }
      const res  = await fetch(`${API}/webhooks/sync-knowledge`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ tenant_id: tenantId }),
      })
      const data = await res.json()
      if (res.ok) { loadEntries(); showToast(`✓ Synced — ${data.vectors_stored} vectors stored`) }
      else         showToast(data.detail || 'Sync failed')
    } catch {
      showToast('Network error — try again')
    } finally {
      setSyncLoading(false)
    }
  }

  const handleFiles = async (files: FileList | File[]) => {
    const arr = Array.from(files)
    if (!arr.length) return
    setUploadLoading(true)
    setUploadResults([])
    const form = new FormData()
    arr.forEach(f => form.append('files', f))
    try {
      const ah  = await authHeaders()
      const res = await fetch(`${API}/knowledge/upload/${tenantId}`, {
        method: 'POST', headers: { ...ah }, body: form,
      })
      const data = await res.json()
      setUploadResults(data.results ?? [])
      if (data.results?.some((r: UploadResult) => r.status === 'ok')) {
        loadEntries()
        showToast('✓ Files uploaded successfully')
      }
    } catch {
      setUploadResults([{ file: 'Upload', status: 'error', reason: 'Network error' }])
    } finally {
      setUploadLoading(false)
    }
  }

  const addText = async () => {
    if (!text.trim()) return
    setTextLoading(true)
    try {
      const ah  = await authHeaders()
      const res = await fetch(`${API}/knowledge/text/${tenantId}`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...ah },
        body:    JSON.stringify({ text }),
      })
      const data = await res.json()
      if (res.ok) { setText(''); loadEntries(); showToast(`✓ Added — ${data.vectors_stored} vectors stored`) }
      else         showToast(data.detail || 'Failed')
    } catch {
      showToast('Network error — try again')
    } finally {
      setTextLoading(false)
    }
  }

  const clearKnowledge = async () => {
    if (!confirm('Clear all knowledge base content? This cannot be undone.')) return
    setClearLoading(true)
    try {
      const ah  = await authHeaders()
      const res = await fetch(`${API}/knowledge/clear/${tenantId}`, { method: 'POST', headers: { ...ah } })
      if (res.ok) { loadEntries(); showToast('Knowledge base cleared') }
      else         showToast('Clear failed — try again')
    } catch {
      showToast('Network error')
    } finally {
      setClearLoading(false)
    }
  }

  const sourceSubtitle = (e: KbEntry) => {
    if (e.type === 'website') return `Last synced ${timeAgo(e.added_at)}`
    if (e.type === 'file')    return `Uploaded ${timeAgo(e.added_at)}`
    const charCount = e.preview?.length ?? 0
    return `Added manually${charCount ? ` · ${charCount} chars` : ''}`
  }

  const SourceIcon = ({ type }: { type: KbEntry['type'] }) => {
    const c = type === 'website' ? '#3B7EF6' : type === 'file' ? '#d97706' : '#16a34a'
    if (type === 'website') return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke={c} strokeWidth="1.7">
        <circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" />
      </svg>
    )
    if (type === 'file') return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke={c} strokeWidth="1.7" strokeLinejoin="round">
        <path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z" /><path d="M14 3v5h5" />
      </svg>
    )
    return (
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke={c} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z" />
      </svg>
    )
  }

  // ── Section-header icons ────────────────────────────────────
  const IconGlobe = () => (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" />
    </svg>
  )
  const IconUpload = () => (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><path d="M7 9l5-5 5 5M12 4v12" />
    </svg>
  )
  const IconPencil = () => (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z" />
    </svg>
  )

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f4f3f0' }}>
        <div style={{ fontSize: 13, color: '#888' }}>Loading…</div>
      </div>
    )
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
                borderRadius: 8, fontSize: 13, fontWeight: 500, zIndex: 400,
                boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
              }}
            >
              {toast}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Desktop topbar */}
        <div className="db-topbar">
          <span className="db-topbar-title">Knowledge Base</span>
          <div className="db-topbar-right">
            <button className="kb-update-btn" onClick={repairPrompt} disabled={repairLoading}>
              <span style={{ fontSize: 13 }}>✦</span>
              {repairLoading ? 'Updating…' : 'Update AI Prompt'}
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="db-content">
          <div className="kb-content-wrap">

            {/* Intro */}
            <div className="kb-intro">
              <h2 className="kb-intro-title">What your AI knows</h2>
              <p className="kb-intro-sub">
                Everything here trains your AI receptionist for {tenant?.business_name ?? 'your business'}.
                The more accurate it is, the better your calls.
              </p>
            </div>

            {/* Sources */}
            <div className="kb-card">
              <div className="kb-sources-hdr">
                <span className="kb-sources-name">Active sources</span>
                <span className="kb-count-pill">{entries.length} {entries.length === 1 ? 'source' : 'sources'}</span>
              </div>
              {entries.length === 0 ? (
                <div className="kb-empty">
                  <div className="kb-empty-icon">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#bbb" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M4 19.5A2.5 2.5 0 016.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
                    </svg>
                  </div>
                  <div className="kb-empty-title">No sources yet</div>
                  <div className="kb-empty-sub">Add your website, upload files, or paste text below to get started.</div>
                </div>
              ) : (
                entries.map(entry => (
                  <div key={entry.id} className="kb-source-row">
                    <div className={`kb-source-icon kb-icon-${entry.type}`}>
                      <SourceIcon type={entry.type} />
                    </div>
                    <div className="kb-source-info">
                      <div className="kb-source-name">{entry.label}</div>
                      <div className="kb-source-meta">{sourceSubtitle(entry)}</div>
                    </div>
                    <div className="kb-source-actions">
                      <span className="kb-synced"><span className="kb-synced-dot" />Synced</span>
                      {entry.type === 'website' && (
                        <button className="kb-btn-resync" onClick={syncWebsite} disabled={syncLoading}>
                          {syncLoading ? 'Syncing…' : 'Re-sync'}
                        </button>
                      )}
                      <button
                        className="kb-btn-remove"
                        onClick={() => deleteEntry(entry.id)}
                        disabled={deletingId === entry.id}
                        aria-label="Remove source"
                      >
                        {deletingId === entry.id ? '…' : 'Remove'}
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Add knowledge */}
            <div className="kb-section-label">Add to your knowledge base</div>

            {/* Two-column: Sync website + Upload files */}
            <div className="kb-two-col">

              {/* Sync website */}
              <div className="kb-card kb-card-pad">
                <div className="kb-card-title"><span className="kb-title-icon"><IconGlobe /></span> Sync website</div>
                <div className="kb-url-row">
                  <input
                    type="url"
                    className="kb-url-input"
                    value={urlInput}
                    onChange={e => setUrlInput(e.target.value)}
                    placeholder="https://yourbusiness.com"
                    onKeyDown={e => e.key === 'Enter' && syncWebsite()}
                  />
                  <button
                    className="kb-btn-sync"
                    onClick={syncWebsite}
                    disabled={syncLoading || !urlInput.trim()}
                  >
                    {syncLoading ? 'Syncing…' : 'Re-sync'}
                  </button>
                </div>
                <div className="kb-hint">
                  Crawls all public pages automatically. Re-sync after updating your website.
                </div>
              </div>

              {/* Upload files */}
              <div className="kb-card kb-card-pad">
                <div className="kb-card-title"><span className="kb-title-icon"><IconUpload /></span> Upload files</div>
                <div
                  className={`kb-dropzone${dragging ? ' drag-over' : ''}`}
                  onDragOver={e => { e.preventDefault(); setDragging(true) }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={e => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files) }}
                  onClick={() => !uploadLoading && fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef} type="file" multiple
                    accept=".pdf,.docx,.xlsx,.xls,.txt,.md,.csv"
                    style={{ display: 'none' }}
                    onChange={e => e.target.files && handleFiles(e.target.files)}
                  />
                  <svg viewBox="0 0 24 24" fill="none" stroke="#ccc" strokeWidth="1.4"
                    width="28" height="28" style={{ display: 'block', margin: '0 auto 8px' }}>
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
                  </svg>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#16161a' }}>
                    {uploadLoading ? 'Uploading…' : 'Drop files or click to browse'}
                  </div>
                  <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
                    PDF, Word, Excel, TXT, CSV · max 10 MB each
                  </div>
                </div>
                {uploadResults.length > 0 && (
                  <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {uploadResults.map((r, i) => (
                      <div key={i} style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        fontSize: 11, padding: '6px 10px', borderRadius: 6,
                        background: r.status === 'ok' ? '#f0fdf4' : '#fef2f2',
                        color: r.status === 'ok' ? '#16a34a' : '#ef4444',
                      }}>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>
                          {r.file}
                        </span>
                        <span>{r.status === 'ok' ? `✓ ${r.vectors_stored} vectors` : r.reason || r.status}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Add text manually */}
            <div className="kb-card kb-card-pad">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                <div className="kb-card-title"><span className="kb-title-icon"><IconPencil /></span> Add text manually</div>
                <MicButton onResult={t => setText(prev => (prev.trim() ? prev.trim() + ' ' : '') + t)} />
              </div>
              <textarea
                className="kb-textarea"
                value={text}
                onChange={e => setText(e.target.value)}
                placeholder="Paste FAQs, hours, service descriptions, pricing, or anything your AI should know… (or tap the mic to dictate)"
                rows={5}
              />
              <button
                className="kb-btn-add"
                onClick={addText}
                disabled={textLoading || !text.trim()}
              >
                {textLoading ? 'Processing…' : 'Add to Knowledge Base'}
              </button>
            </div>

            {/* Danger zone */}
            <div className="kb-danger-zone">
              <div className="kb-danger-hdr">⚠ Danger zone</div>
              <div className="kb-danger-body">
                <div>
                  <div className="kb-danger-desc">Clear all knowledge base content</div>
                  <div className="kb-danger-sub">
                    Removes all sources, files, and text. The AI will lose all context
                    about {tenant?.business_name ?? 'your business'}. Use before a full re-sync.
                  </div>
                </div>
                <button className="kb-btn-clear" onClick={clearKnowledge} disabled={clearLoading}>
                  {clearLoading ? 'Clearing…' : 'Clear Knowledge Base'}
                </button>
              </div>
            </div>

          </div>
        </div>
    </>
  )
}

export default function KnowledgeBasePageWrapper() {
  return (
    <Suspense fallback={
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f4f3f0' }}>
        <div style={{ fontSize: 13, color: '#888' }}>Loading…</div>
      </div>
    }>
      <KnowledgeBasePage />
    </Suspense>
  )
}
