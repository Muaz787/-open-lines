'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { authedFetch, API } from '@/lib/api'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

interface Profile {
  id?: string
  mode?: string
  overflow_enabled?: boolean
  default_destination_id?: string | null
  urgent_destination_id?: string | null
  default_fallback_action?: string
}
interface Destination {
  id: string
  type: string
  label?: string | null
  number_masked?: string | null
  enabled: boolean
}
interface Rule {
  id: string
  priority: number
  enabled: boolean
  match: Record<string, unknown>
  destination_id?: string | null
}
interface Decision {
  decision: string
  reason: string
  destination_id?: string | null
  destination?: Destination | null
}

const MODES: { value: string; title: string; blurb: string }[] = [
  { value: 'ai_first',        title: 'Answer every call with AI',       blurb: 'OpenLines answers all inbound calls (today’s behaviour).' },
  { value: 'ai_overflow',     title: 'Only when we’re busy or closed', blurb: 'Your team answers first; OpenLines catches overflow (via carrier forwarding).' },
  { value: 'ai_first_routing', title: 'AI answers and routes',           blurb: 'AI answers, handles routine calls, and transfers the rest to the right person.' },
]

function CallHandlingPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [loading, setLoading]     = useState(true)
  const [entitled, setEntitled]   = useState<boolean | null>(null)
  const [profile, setProfile]     = useState<Profile>({})
  const [dests, setDests]         = useState<Destination[]>([])
  const [rules, setRules]         = useState<Rule[]>([])

  const [modeState, setModeState] = useState<SaveState>('idle')
  const [destState, setDestState] = useState<SaveState>('idle')
  const [destErr, setDestErr]     = useState('')
  const [newNumber, setNewNumber] = useState('')
  const [newLabel, setNewLabel]   = useState('')
  const [newType, setNewType]     = useState('phone')

  const [ruleState, setRuleState] = useState<SaveState>('idle')
  const [ruleIntent, setRuleIntent] = useState('')
  const [ruleDest, setRuleDest]     = useState('')

  const [simIntent, setSimIntent]   = useState('')
  const [simUrgency, setSimUrgency] = useState('normal')
  const [decision, setDecision]     = useState<Decision | null>(null)

  const activeDests = dests.filter(d => d.enabled)

  const loadRules = useCallback(async (profileId?: string) => {
    if (!profileId) { setRules([]); return }
    const r = await authedFetch(`${API}/routing/${tenantId}/rules?profile_id=${profileId}`)
    if (r.ok) setRules((await r.json()).rules ?? [])
  }, [tenantId])

  // Initial load. All setState calls run inside the async IIFE (after an await),
  // so none happen synchronously in the effect body.
  useEffect(() => {
    let active = true
    void (async () => {
      const pRes = await authedFetch(`${API}/routing/${tenantId}/profile`)
      if (!active) return
      if (pRes.status === 403) { setEntitled(false); setLoading(false); return }
      setEntitled(true)
      const prof: Profile = pRes.ok ? await pRes.json() : {}
      if (!active) return
      setProfile(prof)
      const dRes = await authedFetch(`${API}/routing/${tenantId}/destinations`)
      if (active && dRes.ok) setDests((await dRes.json()).destinations ?? [])
      await loadRules(prof.id)
      if (active) setLoading(false)
    })()
    return () => { active = false }
  }, [tenantId, loadRules])

  // Ensure a saved profile exists (returns its id) so rules/destinations can attach.
  const ensureProfile = useCallback(async (patch: Partial<Profile> = {}): Promise<Profile> => {
    const res = await authedFetch(`${API}/routing/${tenantId}/profile`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...patch }),
    })
    const prof = res.ok ? await res.json() : profile
    setProfile(prof)
    return prof
  }, [tenantId, profile])

  const saveMode = async (mode: string) => {
    setModeState('saving')
    try {
      const overflow = mode === 'ai_overflow'
      const prof = await ensureProfile({ mode, overflow_enabled: overflow })
      await loadRules(prof.id)
      setModeState('saved'); setTimeout(() => setModeState('idle'), 1500)
    } catch { setModeState('error') }
  }

  const saveProfileField = async (patch: Partial<Profile>) => {
    setProfile(p => ({ ...p, ...patch }))
    await ensureProfile(patch)
  }

  const addDestination = async () => {
    setDestErr(''); setDestState('saving')
    const res = await authedFetch(`${API}/routing/${tenantId}/destinations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ number: newNumber.trim(), label: newLabel.trim() || null, type: newType }),
    })
    if (res.ok) {
      const d: Destination = await res.json()
      setDests(list => [...list, d])
      setNewNumber(''); setNewLabel(''); setDestState('saved'); setTimeout(() => setDestState('idle'), 1200)
    } else {
      const body = await res.json().catch(() => ({}))
      setDestErr(body.detail || 'Could not add destination'); setDestState('error')
    }
  }

  const removeDestination = async (id: string) => {
    await authedFetch(`${API}/routing/${tenantId}/destinations/${id}`, { method: 'DELETE' })
    setDests(list => list.map(d => d.id === id ? { ...d, enabled: false } : d))
  }

  const addRule = async () => {
    setRuleState('saving')
    const prof = await ensureProfile()
    const res = await authedFetch(`${API}/routing/${tenantId}/rules`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_id: prof.id, match: { intent: ruleIntent.trim() }, destination_id: ruleDest || null }),
    })
    if (res.ok) {
      setRuleIntent(''); setRuleDest(''); setRuleState('saved'); setTimeout(() => setRuleState('idle'), 1200)
      await loadRules(prof.id)
    } else { setRuleState('error') }
  }

  const removeRule = async (id: string) => {
    await authedFetch(`${API}/routing/${tenantId}/rules/${id}`, { method: 'DELETE' })
    setRules(list => list.filter(r => r.id !== id))
  }

  const runSimulate = async () => {
    const res = await authedFetch(`${API}/routing/${tenantId}/simulate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent: simIntent.trim(), urgency: simUrgency, confidence: 0.9 }),
    })
    if (res.ok) setDecision(await res.json())
  }

  const destLabel = (d: Destination) => `${d.label ? d.label + ' — ' : ''}${d.number_masked ?? ''}${d.type === 'urgent' ? ' (urgent)' : ''}`

  if (loading) return <div style={{ padding: 24, color: 'var(--db-muted)' }}>Loading…</div>

  if (entitled === false) return (
    <div style={{ padding: 24 }}>
      <div style={{ maxWidth: 620, border: '1px solid var(--db-border-lt)', borderRadius: 12, padding: 24 }}>
        <h2 style={{ marginTop: 0, color: 'var(--db-text)' }}>Call handling &amp; routing</h2>
        <p style={{ color: 'var(--db-muted)', lineHeight: 1.5 }}>
          Answer calls only when your team is busy or closed, and transfer callers who need a
          person to the right destination — with a safe fallback if no one answers.
        </p>
        <p style={{ color: 'var(--db-muted)' }}>
          This feature isn&rsquo;t enabled for your account yet. It&rsquo;s available on the Pro and
          Business plans.
        </p>
      </div>
    </div>
  )

  return (
    <div style={{ padding: 24, maxWidth: 760 }}>
      <h1 style={{ color: 'var(--db-text)', marginTop: 0 }}>Call handling &amp; routing</h1>

      {/* Mode */}
      <section style={{ marginTop: 8 }}>
        <label className="db-field-label">How should calls be answered?</label>
        <div style={{ display: 'grid', gap: 10, marginTop: 8 }}>
          {MODES.map(m => (
            <button key={m.value} type="button" onClick={() => saveMode(m.value)}
              style={{ textAlign: 'left', padding: '12px 14px', borderRadius: 10, cursor: 'pointer',
                border: `1px solid ${profile.mode === m.value ? 'var(--db-accent-text)' : 'var(--db-border-lt)'}`,
                background: profile.mode === m.value ? 'var(--db-accent-bg, transparent)' : 'transparent' }}>
              <div style={{ fontWeight: 600, color: 'var(--db-text)' }}>{m.title}</div>
              <div style={{ fontSize: 13, color: 'var(--db-muted)' }}>{m.blurb}</div>
            </button>
          ))}
        </div>
        {modeState === 'saved' && <span style={{ fontSize: 12, color: 'var(--db-accent-text)' }}>✓ Saved</span>}
        {modeState === 'error' && <span style={{ fontSize: 12, color: 'var(--db-danger-text)' }}>Save failed</span>}
      </section>

      {/* Destinations */}
      <section style={{ marginTop: 28 }}>
        <label className="db-field-label">Transfer destinations</label>
        <p style={{ fontSize: 13, color: 'var(--db-muted)', marginTop: 2 }}>
          Domestic numbers only. Numbers are stored encrypted and shown masked.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
          {activeDests.length === 0 && <div style={{ fontSize: 13, color: 'var(--db-muted)' }}>No destinations yet.</div>}
          {activeDests.map(d => (
            <div key={d.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '8px 0', borderTop: '1px solid var(--db-border-lt)' }}>
              <span style={{ color: 'var(--db-text)', fontSize: 14 }}>{destLabel(d)}</span>
              <button type="button" onClick={() => removeDestination(d.id)}
                style={{ fontSize: 12, color: 'var(--db-danger-text)', background: 'none', border: 'none', cursor: 'pointer' }}>
                Remove
              </button>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
          <input value={newNumber} onChange={e => setNewNumber(e.target.value)} placeholder="+1 647 555 0123"
            style={{ flex: '1 1 160px', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--db-border-lt)' }} />
          <input value={newLabel} onChange={e => setNewLabel(e.target.value)} placeholder="Label (e.g. On-call)"
            style={{ flex: '1 1 140px', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--db-border-lt)' }} />
          <select value={newType} onChange={e => setNewType(e.target.value)}
            style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--db-border-lt)' }}>
            <option value="phone">Regular</option>
            <option value="urgent">Urgent / on-call</option>
          </select>
          <button type="button" onClick={addDestination} disabled={!newNumber.trim() || destState === 'saving'}
            className="db-btn">{destState === 'saving' ? 'Adding…' : 'Add'}</button>
        </div>
        {destErr && <div style={{ fontSize: 12, color: 'var(--db-danger-text)', marginTop: 6 }}>{destErr}</div>}
      </section>

      {/* Default + urgent destination */}
      <section style={{ marginTop: 28 }}>
        <label className="db-field-label">Where should calls go?</label>
        <div style={{ display: 'grid', gap: 12, marginTop: 8 }}>
          <div>
            <div style={{ fontSize: 13, color: 'var(--db-muted)' }}>Default human destination</div>
            <select value={profile.default_destination_id ?? ''} onChange={e => saveProfileField({ default_destination_id: e.target.value || null })}
              style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--db-border-lt)', minWidth: 240 }}>
              <option value="">— none —</option>
              {activeDests.map(d => <option key={d.id} value={d.id}>{destLabel(d)}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 13, color: 'var(--db-muted)' }}>Urgent / on-call destination</div>
            <select value={profile.urgent_destination_id ?? ''} onChange={e => saveProfileField({ urgent_destination_id: e.target.value || null })}
              style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--db-border-lt)', minWidth: 240 }}>
              <option value="">— none —</option>
              {activeDests.map(d => <option key={d.id} value={d.id}>{destLabel(d)}</option>)}
            </select>
          </div>
        </div>
      </section>

      {/* Rules */}
      <section style={{ marginTop: 28 }}>
        <label className="db-field-label">Routing rules</label>
        <p style={{ fontSize: 13, color: 'var(--db-muted)', marginTop: 2 }}>When the caller&rsquo;s reason matches, send them to a destination.</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
          {rules.map(r => (
            <div key={r.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '8px 0', borderTop: '1px solid var(--db-border-lt)' }}>
              <span style={{ color: 'var(--db-text)', fontSize: 14 }}>
                {String((r.match as { intent?: string }).intent ?? 'any')} → {activeDests.find(d => d.id === r.destination_id)?.label ?? 'destination'}
              </span>
              <button type="button" onClick={() => removeRule(r.id)}
                style={{ fontSize: 12, color: 'var(--db-danger-text)', background: 'none', border: 'none', cursor: 'pointer' }}>Remove</button>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
          <input value={ruleIntent} onChange={e => setRuleIntent(e.target.value)} placeholder="Intent (e.g. billing)"
            style={{ flex: '1 1 160px', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--db-border-lt)' }} />
          <select value={ruleDest} onChange={e => setRuleDest(e.target.value)}
            style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--db-border-lt)' }}>
            <option value="">Destination…</option>
            {activeDests.map(d => <option key={d.id} value={d.id}>{destLabel(d)}</option>)}
          </select>
          <button type="button" onClick={addRule} disabled={!ruleIntent.trim() || !ruleDest || ruleState === 'saving'}
            className="db-btn">{ruleState === 'saving' ? 'Adding…' : 'Add rule'}</button>
        </div>
      </section>

      {/* Simulate */}
      <section style={{ marginTop: 28, marginBottom: 40 }}>
        <label className="db-field-label">Test it — no call is placed</label>
        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <input value={simIntent} onChange={e => setSimIntent(e.target.value)} placeholder="Pretend the caller wants… (e.g. billing)"
            style={{ flex: '1 1 220px', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--db-border-lt)' }} />
          <select value={simUrgency} onChange={e => setSimUrgency(e.target.value)}
            style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--db-border-lt)' }}>
            <option value="low">Low</option><option value="normal">Normal</option><option value="urgent">Urgent</option>
          </select>
          <button type="button" onClick={runSimulate} className="db-btn">Simulate</button>
        </div>
        {decision && (
          <div style={{ marginTop: 10, padding: 12, borderRadius: 8, border: '1px solid var(--db-border-lt)', fontSize: 14, color: 'var(--db-text)' }}>
            Decision: <strong>{decision.decision}</strong>
            {decision.destination && <> → {destLabel(decision.destination)}</>}
            <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>{decision.reason}</div>
          </div>
        )}
      </section>
    </div>
  )
}

export default function CallHandlingPageWrapper() {
  return <CallHandlingPage />
}
