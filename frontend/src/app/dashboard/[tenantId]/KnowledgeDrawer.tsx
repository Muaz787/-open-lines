'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { supabase } from '@/lib/supabase'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

interface UploadResult {
  file: string
  status: string
  vectors_stored?: number
  reason?: string
}

interface KbEntry {
  id: string
  type: 'file' | 'text' | 'website'
  label: string
  preview?: string
  added_at: string
}

interface Props {
  tenantId: string
  websiteUrl?: string
  lastCrawlAt?: string
  onClose: () => void
}

const TYPE_ICON: Record<string, string> = { file: '📄', text: '📝', website: '🌐' }

function timeAgoShort(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const d = Math.floor(diff / 86400000)
  if (d === 0) return 'Today'
  if (d === 1) return 'Yesterday'
  if (d < 30) return `${d}d ago`
  return new Date(iso).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' })
}

export function KnowledgeDrawer({ tenantId, websiteUrl, lastCrawlAt, onClose }: Props) {
  const [urlInput, setUrlInput]           = useState(websiteUrl ?? '')
  const [urlSaving, setUrlSaving]         = useState(false)
  const [urlMsg, setUrlMsg]               = useState<string | null>(null)

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

  const [repairLoading, setRepairLoading] = useState(false)
  const [repairMsg, setRepairMsg]         = useState<string | null>(null)

  const [entries, setEntries]             = useState<KbEntry[]>([])
  const [deletingId, setDeletingId]       = useState<string | null>(null)

  const loadEntries = useCallback(async () => {
    const ah = await authHeaders()
    fetch(`${API}/knowledge/entries/${tenantId}`, { headers: ah })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.entries) setEntries(d.entries) })
      .catch(() => {})
  }, [tenantId])

  useEffect(() => { loadEntries() }, [loadEntries])

  const deleteEntry = async (id: string) => {
    setDeletingId(id)
    try {
      const ah = await authHeaders()
      await fetch(`${API}/knowledge/entries/${tenantId}/${id}`, { method: 'DELETE', headers: ah })
      setEntries(prev => prev.filter(e => e.id !== id))
    } catch {}
    finally { setDeletingId(null) }
  }

  const repairPrompt = async () => {
    setRepairLoading(true)
    setRepairMsg(null)
    try {
      const ah  = await authHeaders()
      const res = await fetch(`${API}/knowledge/repair-prompt/${tenantId}`, { method: 'POST', headers: ah })
      const data = await res.json()
      setRepairMsg(res.ok ? 'AI prompt updated successfully.' : data.detail || 'Repair failed')
    } catch {
      setRepairMsg('Network error — try again')
    } finally {
      setRepairLoading(false)
    }
  }

  const saveUrl = async () => {
    const url = urlInput.trim()
    if (!url) return
    setUrlSaving(true)
    setUrlMsg(null)
    try {
      const ah  = await authHeaders()
      const res = await fetch(`${API}/knowledge/website/${tenantId}`, {
        method:  'PATCH',
        headers: { 'Content-Type': 'application/json', ...ah },
        body:    JSON.stringify({ website_url: url }),
      })
      const data = await res.json()
      setUrlMsg(res.ok ? 'URL saved.' : data.detail || 'Failed to save URL')
    } catch {
      setUrlMsg('Network error — try again')
    } finally {
      setUrlSaving(false)
    }
  }

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
      if (res.ok) loadEntries()
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
      const ah  = await authHeaders()
      const res = await fetch(`${API}/knowledge/upload/${tenantId}`, {
        method: 'POST', headers: { ...ah }, body: form,
      })
      const data = await res.json()
      setUploadResults(data.results ?? [])
      if (data.results?.some((r: UploadResult) => r.status === 'ok')) loadEntries()
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
      const ah  = await authHeaders()
      const res = await fetch(`${API}/knowledge/text/${tenantId}`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...ah },
        body:    JSON.stringify({ text }),
      })
      const data = await res.json()
      if (res.ok) { setTextMsg(`Added — ${data.vectors_stored} vectors stored`); setText(''); loadEntries() }
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
      const ah  = await authHeaders()
      const res = await fetch(`${API}/knowledge/clear/${tenantId}`, { method: 'POST', headers: { ...ah } })
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
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 190 }}
      />

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
          <button onClick={onClose} style={{
            background: 'none', border: '1px solid var(--border-2)',
            borderRadius: 6, cursor: 'pointer', color: 'var(--text-3)',
            fontSize: 16, lineHeight: 1, width: 30, height: 30,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>×</button>
        </div>

        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: 28, flex: 1 }}>

          {/* ── Sources ── */}
          <div>
            <div style={labelStyle}>Sources ({entries.length})</div>
            <div style={{
              border: '1px solid var(--border)', borderRadius: 10,
              overflow: 'hidden', background: 'var(--bg)',
            }}>
              {entries.length === 0 ? (
                <div style={{ padding: '16px 14px', fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>
                  No sources yet — add your website, upload files, or paste text below.
                </div>
              ) : (
                entries.map((e, i) => (
                  <div key={e.id} style={{
                    display: 'grid', gridTemplateColumns: '1fr auto',
                    alignItems: 'center', gap: 10,
                    padding: '10px 12px',
                    borderTop: i > 0 ? '1px solid var(--border)' : 'none',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                      <span style={{ fontSize: 14, flexShrink: 0 }}>{TYPE_ICON[e.type] ?? '📄'}</span>
                      <div style={{ minWidth: 0 }}>
                        <div style={{
                          fontSize: 12, color: 'var(--text)', fontWeight: 500,
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>{e.label}</div>
                        <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 1 }}>
                          {e.type} · {timeAgoShort(e.added_at)}
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={() => deleteEntry(e.id)}
                      disabled={deletingId === e.id}
                      title="Remove from knowledge base"
                      style={{
                        background: 'none', border: 'none', cursor: 'pointer',
                        color: 'var(--text-3)', fontSize: 16, lineHeight: 1,
                        padding: '2px 4px', borderRadius: 4,
                        opacity: deletingId === e.id ? 0.4 : 1,
                        transition: 'color 0.15s',
                      }}
                      onMouseEnter={e2 => (e2.currentTarget.style.color = errColor)}
                      onMouseLeave={e2 => (e2.currentTarget.style.color = 'var(--text-3)')}
                    >×</button>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* ── Website ── */}
          <div>
            <div style={labelStyle}>Website URL</div>
            <input
              type="url"
              value={urlInput}
              onChange={e => { setUrlInput(e.target.value); setUrlMsg(null) }}
              placeholder="https://yourbusiness.com"
              style={{
                width: '100%', boxSizing: 'border-box', padding: '10px 12px',
                background: 'var(--bg)', border: '1px solid var(--border-2)',
                borderRadius: 8, fontSize: 13, color: 'var(--text)',
                outline: 'none', fontFamily: 'var(--font-dm), sans-serif',
              }}
            />
            {urlInput.trim() !== (websiteUrl ?? '') && (
              <button onClick={saveUrl} disabled={urlSaving || !urlInput.trim()} style={{
                marginTop: 8, fontSize: 12, fontWeight: 600,
                color: 'var(--bg)', background: 'var(--accent)',
                border: 'none', borderRadius: 7, padding: '8px 14px',
                cursor: urlSaving ? 'not-allowed' : 'pointer',
                opacity: urlSaving ? 0.65 : 1, transition: 'opacity 0.2s',
              }}>
                {urlSaving ? 'Saving…' : 'Save URL'}
              </button>
            )}
            {urlMsg && (
              <div style={{ fontSize: 11, marginTop: 6, color: urlMsg === 'URL saved.' ? okColor : errColor }}>
                {urlMsg}
              </div>
            )}
            {lastCrawlAt && (
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 8 }}>
                Last synced {new Date(lastCrawlAt).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' })}
              </div>
            )}
            <button onClick={syncWebsite} disabled={syncLoading || !urlInput.trim()} style={{
              marginTop: 10, fontSize: 12, fontWeight: 600, color: 'var(--bg)',
              background: urlInput.trim() ? 'var(--text)' : 'var(--text-3)',
              border: 'none', borderRadius: 7, padding: '8px 16px',
              cursor: urlInput.trim() && !syncLoading ? 'pointer' : 'not-allowed',
              opacity: syncLoading ? 0.65 : 1, transition: 'opacity 0.2s',
            }}>
              {syncLoading ? 'Syncing…' : 'Re-sync Website'}
            </button>
            {syncMsg && (
              <div style={{ fontSize: 11, marginTop: 8, color: syncMsg.startsWith('Synced') ? okColor : errColor }}>
                {syncMsg}
              </div>
            )}
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
                ref={fileInputRef} type="file" multiple
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
                padding: '12px 14px', background: 'var(--bg)',
                border: '1px solid var(--border-2)', borderRadius: 8,
                fontSize: 12, color: 'var(--text)', lineHeight: 1.6,
                fontFamily: 'var(--font-dm), sans-serif', outline: 'none',
              }}
            />
            <button onClick={addText} disabled={textLoading || !text.trim()} style={{
              marginTop: 10, fontSize: 12, fontWeight: 600,
              color: text.trim() ? 'var(--bg)' : 'var(--text-3)',
              background: text.trim() ? 'var(--text)' : 'var(--bg-3)',
              border: 'none', borderRadius: 7, padding: '9px 18px',
              cursor: text.trim() && !textLoading ? 'pointer' : 'not-allowed',
              opacity: textLoading ? 0.65 : 1, transition: 'opacity 0.2s, background 0.2s',
            }}>
              {textLoading ? 'Processing…' : 'Add to Knowledge Base'}
            </button>
            {textMsg && (
              <div style={{ fontSize: 11, marginTop: 8, color: textMsg.startsWith('Added') ? okColor : errColor }}>
                {textMsg}
              </div>
            )}
          </div>

          {/* ── Repair Prompt ── */}
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 24 }}>
            <div style={labelStyle}>AI Prompt</div>
            <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 12, lineHeight: 1.5 }}>
              Re-push the latest knowledge base and instructions to the AI. Use this after uploading new files or changing settings.
            </div>
            <button onClick={repairPrompt} disabled={repairLoading} style={{
              fontSize: 12, fontWeight: 600, color: 'var(--bg)', background: 'var(--text)',
              border: 'none', borderRadius: 7, padding: '8px 16px',
              cursor: repairLoading ? 'not-allowed' : 'pointer',
              opacity: repairLoading ? 0.65 : 1, transition: 'opacity 0.2s',
            }}>
              {repairLoading ? 'Updating…' : 'Update AI Prompt'}
            </button>
            {repairMsg && (
              <div style={{ fontSize: 11, marginTop: 8, color: repairMsg.startsWith('AI prompt') ? okColor : errColor }}>
                {repairMsg}
              </div>
            )}
          </div>

          {/* ── Danger Zone ── */}
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 24 }}>
            <div style={labelStyle}>Danger Zone</div>
            <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 12, lineHeight: 1.5 }}>
              Remove all stored content. Use this before a full re-sync to start clean.
            </div>
            <button onClick={clearKnowledge} disabled={clearLoading} style={{
              fontSize: 12, fontWeight: 600, color: errColor,
              background: 'rgba(255,59,48,0.08)', border: '1px solid rgba(255,59,48,0.2)',
              borderRadius: 7, padding: '8px 16px',
              cursor: clearLoading ? 'not-allowed' : 'pointer',
              opacity: clearLoading ? 0.65 : 1, transition: 'opacity 0.2s',
            }}>
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
