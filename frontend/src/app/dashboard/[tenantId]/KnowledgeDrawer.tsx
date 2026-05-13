'use client'

import { useState, useRef } from 'react'
import { motion } from 'framer-motion'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface UploadResult {
  file: string
  status: string
  vectors_stored?: number
  reason?: string
}

interface Props {
  tenantId: string
  websiteUrl?: string
  lastCrawlAt?: string
  onClose: () => void
}

export function KnowledgeDrawer({ tenantId, websiteUrl, lastCrawlAt, onClose }: Props) {
  const [syncLoading, setSyncLoading]     = useState(false)
  const [syncMsg, setSyncMsg]             = useState<string | null>(null)

  const [dragging, setDragging]           = useState(false)
  const [uploadLoading, setUploadLoading] = useState(false)
  const [uploadResults, setUploadResults] = useState<UploadResult[]>([])
  const fileInputRef                      = useRef<HTMLInputElement>(null)

  const [text, setText]                   = useState('')
  const [textLoading, setTextLoading]     = useState(false)
  const [textMsg, setTextMsg]             = useState<string | null>(null)

  const [clearLoading, setClearLoading]   = useState(false)
  const [clearMsg, setClearMsg]           = useState<string | null>(null)

  const syncWebsite = async () => {
    setSyncLoading(true)
    setSyncMsg(null)
    try {
      const res  = await fetch(`${API}/webhooks/sync-knowledge`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ tenant_id: tenantId }),
      })
      const data = await res.json()
      setSyncMsg(res.ok
        ? `Synced — ${data.vectors_stored} vectors stored`
        : data.detail || 'Sync failed')
    } catch {
      setSyncMsg('Network error — try again')
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
      const res  = await fetch(`${API}/knowledge/upload/${tenantId}`, { method: 'POST', body: form })
      const data = await res.json()
      setUploadResults(data.results ?? [])
    } catch {
      setUploadResults([{ file: 'Upload', status: 'error', reason: 'Network error' }])
    } finally {
      setUploadLoading(false)
    }
  }

  const addText = async () => {
    if (!text.trim()) return
    setTextLoading(true)
    setTextMsg(null)
    try {
      const res  = await fetch(`${API}/knowledge/text/${tenantId}`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ text }),
      })
      const data = await res.json()
      if (res.ok) { setTextMsg(`Added — ${data.vectors_stored} vectors stored`); setText('') }
      else          setTextMsg(data.detail || 'Failed')
    } catch {
      setTextMsg('Network error — try again')
    } finally {
      setTextLoading(false)
    }
  }

  const clearKnowledge = async () => {
    if (!confirm('Clear all knowledge base content? This cannot be undone.')) return
    setClearLoading(true)
    setClearMsg(null)
    try {
      const res = await fetch(`${API}/knowledge/clear/${tenantId}`, { method: 'POST' })
      setClearMsg(res.ok ? 'Knowledge base cleared.' : 'Clear failed — try again')
    } catch {
      setClearMsg('Network error')
    } finally {
      setClearLoading(false)
    }
  }

  const labelStyle: React.CSSProperties = {
    fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
    textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 10,
  }

  const okColor  = 'var(--accent)'
  const errColor = '#FF3B30'

  return (
    <>
      {/* Backdrop */}
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.35)',
          zIndex: 190,
        }}
      />

      {/* Panel */}
      <motion.div
        initial={{ x: 440 }} animate={{ x: 0 }} exit={{ x: 440 }}
        transition={{ type: 'spring', damping: 30, stiffness: 300 }}
        style={{
          position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(420px, 100vw)',
          background: 'var(--bg-2)', borderLeft: '1px solid var(--border-2)',
          boxShadow: '-8px 0 40px rgba(0,0,0,0.12)',
          zIndex: 200, overflowY: 'auto', display: 'flex', flexDirection: 'column',
        }}
      >
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '20px 24px', borderBottom: '1px solid var(--border)',
          position: 'sticky', top: 0, background: 'var(--bg-2)', zIndex: 1,
        }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--font-syne), sans-serif' }}>
              Knowledge Base
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
              What your AI knows about your business
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: '1px solid var(--border-2)',
              borderRadius: 6, cursor: 'pointer',
              color: 'var(--text-3)', fontSize: 16, lineHeight: 1,
              width: 30, height: 30, display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            ×
          </button>
        </div>

        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: 28, flex: 1 }}>

          {/* ── Website ── */}
          <div>
            <div style={labelStyle}>Website</div>
            <div style={{
              border: '1px solid var(--border)', borderRadius: 10,
              background: 'var(--bg)', overflow: 'hidden',
            }}>
              <div style={{ padding: '14px 16px' }}>
                <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6, wordBreak: 'break-all', lineHeight: 1.5 }}>
                  {websiteUrl || <span style={{ color: 'var(--text-3)' }}>No website URL on file</span>}
                </div>
                {lastCrawlAt && (
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }}>
                    Last synced {new Date(lastCrawlAt).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' })}
                  </div>
                )}
                <button
                  onClick={syncWebsite}
                  disabled={syncLoading || !websiteUrl}
                  style={{
                    fontSize: 12, fontWeight: 600,
                    color: 'var(--bg)',
                    background: websiteUrl ? 'var(--text)' : 'var(--text-3)',
                    border: 'none', borderRadius: 7, padding: '8px 16px',
                    cursor: websiteUrl ? 'pointer' : 'not-allowed',
                    opacity: syncLoading ? 0.65 : 1, transition: 'opacity 0.2s',
                  }}
                >
                  {syncLoading ? 'Syncing…' : 'Re-sync Website'}
                </button>
                {syncMsg && (
                  <div style={{ fontSize: 11, marginTop: 8, color: syncMsg.startsWith('Synced') ? okColor : errColor }}>
                    {syncMsg}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ── Upload Files ── */}
          <div>
            <div style={labelStyle}>Upload Files</div>
            <div
              onDragOver={e => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={e => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files) }}
              onClick={() => !uploadLoading && fileInputRef.current?.click()}
              style={{
                border: `2px dashed ${dragging ? 'var(--accent)' : 'var(--border-2)'}`,
                borderRadius: 10, padding: '28px 20px', textAlign: 'center',
                cursor: uploadLoading ? 'default' : 'pointer',
                background: dragging ? 'var(--accent-dim)' : 'var(--bg)',
                transition: 'border-color 0.15s, background 0.15s',
              }}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.docx,.xlsx,.xls,.txt,.md,.csv"
                style={{ display: 'none' }}
                onChange={e => e.target.files && handleFiles(e.target.files)}
              />
              <div style={{ fontSize: 24, marginBottom: 8 }}>📎</div>
              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>
                {uploadLoading ? 'Uploading…' : 'Drop files or click to browse'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>
                PDF, Word, Excel, TXT, CSV · max 10 MB each
              </div>
            </div>

            {uploadResults.length > 0 && (
              <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {uploadResults.map((r, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    fontSize: 11, padding: '6px 10px', borderRadius: 6,
                    background: r.status === 'ok' ? 'var(--accent-dim)' : 'rgba(255,59,48,0.08)',
                    color: r.status === 'ok' ? okColor : errColor,
                  }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>{r.file}</span>
                    <span>{r.status === 'ok' ? `✓ ${r.vectors_stored} vectors` : r.reason || r.status}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Add Text ── */}
          <div>
            <div style={labelStyle}>Add Text Manually</div>
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder="Paste FAQs, service descriptions, pricing, hours, or any info your AI should know…"
              rows={6}
              style={{
                width: '100%', boxSizing: 'border-box', resize: 'vertical',
                padding: '12px 14px',
                background: 'var(--bg)', border: '1px solid var(--border-2)',
                borderRadius: 8, fontSize: 12, color: 'var(--text)',
                lineHeight: 1.6, fontFamily: 'var(--font-dm), sans-serif',
                outline: 'none',
              }}
            />
            <button
              onClick={addText}
              disabled={textLoading || !text.trim()}
              style={{
                marginTop: 10, fontSize: 12, fontWeight: 600,
                color: text.trim() ? 'var(--bg)' : 'var(--text-3)',
                background: text.trim() ? 'var(--text)' : 'var(--bg-3)',
                border: 'none', borderRadius: 7, padding: '9px 18px',
                cursor: text.trim() && !textLoading ? 'pointer' : 'not-allowed',
                opacity: textLoading ? 0.65 : 1, transition: 'opacity 0.2s, background 0.2s',
              }}
            >
              {textLoading ? 'Processing…' : 'Add to Knowledge Base'}
            </button>
            {textMsg && (
              <div style={{ fontSize: 11, marginTop: 8, color: textMsg.startsWith('Added') ? okColor : errColor }}>
                {textMsg}
              </div>
            )}
          </div>

          {/* ── Danger Zone ── */}
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 24 }}>
            <div style={labelStyle}>Danger Zone</div>
            <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 12, lineHeight: 1.5 }}>
              Remove all stored content. Use this before a full re-sync to start clean.
            </div>
            <button
              onClick={clearKnowledge}
              disabled={clearLoading}
              style={{
                fontSize: 12, fontWeight: 600, color: errColor,
                background: 'rgba(255,59,48,0.08)',
                border: '1px solid rgba(255,59,48,0.2)',
                borderRadius: 7, padding: '8px 16px',
                cursor: clearLoading ? 'not-allowed' : 'pointer',
                opacity: clearLoading ? 0.65 : 1, transition: 'opacity 0.2s',
              }}
            >
              {clearLoading ? 'Clearing…' : 'Clear Knowledge Base'}
            </button>
            {clearMsg && (
              <div style={{ fontSize: 11, marginTop: 8, color: clearMsg.startsWith('Knowledge') ? okColor : errColor }}>
                {clearMsg}
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </>
  )
}
