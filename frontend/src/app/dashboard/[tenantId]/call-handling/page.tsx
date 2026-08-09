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
  { value: 'ai_first',         title: 'Answer every call with AI',       blurb: 'OpenLines answers all inbound calls (today’s behaviour).' },
  { value: 'ai_overflow',      title: 'Only when we’re busy or closed',  blurb: 'Your team answers first; OpenLines catches overflow via carrier forwarding.' },
  { value: 'ai_first_routing', title: 'AI answers and routes',           blurb: 'AI answers, handles routine calls, and transfers the rest to the right person.' },
]

const DECISION_TONE: Record<string, string> = {
  transfer: 'success', callback: 'info', handled_ai: 'neutral',
}

// Show the FULL number (area code included) for a confirm step before it gets
// masked — the safeguard against an area-code typo hiding behind •••1234.
function formatForConfirm(raw: string): string {
  let d = raw.replace(/\D/g, '')
  if (d.length === 11 && d.startsWith('1')) d = d.slice(1)
  if (d.length === 10) return `+1 (${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`
  return raw.trim()
}

function CallHandlingPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [loading, setLoading]   = useState(true)
  const [entitled, setEntitled] = useState<boolean | null>(null)
  const [profile, setProfile]   = useState<Profile>({})
  const [dests, setDests]       = useState<Destination[]>([])
  const [rules, setRules]       = useState<Rule[]>([])

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

  const [routingActive, setRoutingActive] = useState(false)
  const [actState, setActState] = useState<SaveState>('idle')
  const [actWarn, setActWarn]   = useState('')
  const [confirmNum, setConfirmNum] = useState<string | null>(null)

  const activeDests = dests.filter(d => d.enabled)
  const canActivate = activeDests.length >= 1

  const loadRules = useCallback(async (profileId?: string) => {
    if (!profileId) { setRules([]); return }
    const r = await authedFetch(`${API}/routing/${tenantId}/rules?profile_id=${profileId}`)
    if (r.ok) setRules((await r.json()).rules ?? [])
  }, [tenantId])

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
      const sRes = await authedFetch(`${API}/routing/${tenantId}/status`)
      if (active && sRes.ok) setRoutingActive((await sRes.json()).routing_active ?? false)
      const dRes = await authedFetch(`${API}/routing/${tenantId}/destinations`)
      if (active && dRes.ok) setDests((await dRes.json()).destinations ?? [])
      await loadRules(prof.id)
      if (active) setLoading(false)
    })()
    return () => { active = false }
  }, [tenantId, loadRules])

  // Ensure a saved profile exists (returns it, WITH id). Never clobbers state with
  // an empty response: an empty patch just returns the profile we already have.
  const ensureProfile = useCallback(async (patch: Partial<Profile> = {}): Promise<Profile> => {
    if (Object.keys(patch).length === 0 && profile.id) return profile
    const res = await authedFetch(`${API}/routing/${tenantId}/profile`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
    })
    if (res.ok) {
      const prof = await res.json()
      if (prof && prof.id) { setProfile(prof); return prof }
    }
    return profile
  }, [tenantId, profile])

  const flash = (set: (s: SaveState) => void) => { set('saved'); setTimeout(() => set('idle'), 1400) }

  const saveMode = async (mode: string) => {
    setModeState('saving')
    try {
      const prof = await ensureProfile({ mode, overflow_enabled: mode === 'ai_overflow' })
      await loadRules(prof.id)
      flash(setModeState)
    } catch { setModeState('error') }
  }

  const saveProfileField = async (patch: Partial<Profile>) => {
    setProfile(p => ({ ...p, ...patch }))
    await ensureProfile(patch)
  }

  // Two-step add: show the full number for confirmation, THEN submit — so an
  // area-code typo is caught before it disappears behind the mask.
  const requestAddDestination = () => {
    if (!newNumber.trim()) return
    setDestErr(''); setConfirmNum(formatForConfirm(newNumber))
  }

  const submitDestination = async () => {
    setDestErr(''); setDestState('saving'); setConfirmNum(null)
    const res = await authedFetch(`${API}/routing/${tenantId}/destinations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ number: newNumber.trim(), label: newLabel.trim() || null, type: newType }),
    })
    if (res.ok) {
      const d: Destination = await res.json()
      setDests(list => [...list, d]); setNewNumber(''); setNewLabel(''); flash(setDestState)
    } else {
      const body = await res.json().catch(() => ({}))
      setDestErr(body.detail || 'Could not add destination'); setDestState('error')
    }
  }

  const setRoutingOn = async (on: boolean) => {
    setActState('saving'); setActWarn('')
    const res = await authedFetch(`${API}/routing/${tenantId}/${on ? 'activate' : 'deactivate'}`, { method: 'POST' })
    if (res.ok) {
      const body = await res.json().catch(() => ({}))
      setRoutingActive(on); setActState('idle')
      if (on && body.assistant_synced === false) {
        setActWarn(body.warning || 'Routing is on; the voice assistant will finish syncing on the next call.')
      }
    } else {
      const body = await res.json().catch(() => ({}))
      setActWarn(body.detail || `Could not turn routing ${on ? 'on' : 'off'}`); setActState('error')
    }
  }

  const removeDestination = async (id: string) => {
    await authedFetch(`${API}/routing/${tenantId}/destinations/${id}`, { method: 'DELETE' })
    setDests(list => list.map(d => d.id === id ? { ...d, enabled: false } : d))
    setProfile(p => ({
      ...p,
      default_destination_id: p.default_destination_id === id ? null : p.default_destination_id,
      urgent_destination_id: p.urgent_destination_id === id ? null : p.urgent_destination_id,
    }))
  }

  const addRule = async () => {
    setRuleState('saving')
    const prof = await ensureProfile()
    if (!prof.id) { setRuleState('error'); return }
    const res = await authedFetch(`${API}/routing/${tenantId}/rules`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_id: prof.id, match: { intent: ruleIntent.trim() }, destination_id: ruleDest || null }),
    })
    if (res.ok) { setRuleIntent(''); setRuleDest(''); flash(setRuleState); await loadRules(prof.id) }
    else { setRuleState('error') }
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

  const destLabel = (d: Destination) =>
    `${d.label ? d.label + ' — ' : ''}${d.number_masked ?? ''}${d.type === 'urgent' ? ' · urgent' : ''}`

  if (loading) return <div style={{ padding: 28, color: 'var(--db-muted)' }}>Loading…</div>

  if (entitled === false) return (
    <div style={{ padding: 28 }}>
      <div className="db-card" style={{ maxWidth: 560, padding: 24 }}>
        <div className="db-page-heading">Call handling &amp; routing</div>
        <p style={{ color: 'var(--db-muted)', lineHeight: 1.55, margin: '0 0 8px' }}>
          Answer calls only when your team is busy or closed, and transfer callers who need a
          person to the right destination — with a safe fallback if no one answers.
        </p>
        <p style={{ color: 'var(--db-muted)', margin: 0 }}>
          This feature isn&rsquo;t enabled for your account yet — it&rsquo;s available on the Pro and
          Business plans.
        </p>
      </div>
    </div>
  )

  const cardStyle: React.CSSProperties = { padding: '18px 20px', marginBottom: 16 }
  const rowStyle: React.CSSProperties = { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }

  return (
    <div style={{ padding: 28, maxWidth: 800 }}>
      <header style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, color: 'var(--db-text)', margin: 0 }}>Call handling &amp; routing</h1>
        <p style={{ fontSize: 14, color: 'var(--db-muted)', margin: '4px 0 0' }}>
          Catch overflow calls, answer routine questions, and route callers who need a person — with a safe fallback.
        </p>
      </header>

      {/* Activation */}
      <div className="db-card" style={{ ...cardStyle, borderColor: routingActive ? 'var(--db-accent-border)' : 'var(--db-border)',
        background: routingActive ? 'var(--db-accent-bg)' : 'var(--db-card)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 300px' }}>
            <div style={{ fontWeight: 600, color: routingActive ? 'var(--db-accent-text)' : 'var(--db-text)' }}>
              Call routing is {routingActive ? 'on' : 'off'}
            </div>
            <div style={{ fontSize: 13, color: 'var(--db-muted)', marginTop: 3, lineHeight: 1.5 }}>
              {routingActive
                ? 'Live — callers are being routed and transferred based on your setup below.'
                : 'Set up your destinations and rules below, then turn routing on. Nothing changes on your calls until you do.'}
            </div>
          </div>
          <button type="button"
            className={`db-btn ${routingActive ? 'db-btn--danger-ghost' : 'db-btn--primary'}`}
            onClick={() => setRoutingOn(!routingActive)}
            disabled={actState === 'saving' || (!routingActive && !canActivate)}>
            {actState === 'saving' ? '…' : routingActive ? 'Turn off' : 'Turn on'}
          </button>
        </div>
        {!routingActive && !canActivate && (
          <div style={{ fontSize: 12, color: 'var(--db-muted)', marginTop: 10 }}>
            Add at least one destination below before turning routing on.
          </div>
        )}
        {actWarn && <div style={{ fontSize: 12, color: 'var(--db-danger-text)', marginTop: 10 }}>{actWarn}</div>}
      </div>

      {/* Mode */}
      <div className="db-card" style={cardStyle}>
        <label className="db-field-label">How should calls be answered?</label>
        <div style={{ display: 'grid', gap: 10, marginTop: 4 }}>
          {MODES.map(m => {
            const on = profile.mode === m.value
            return (
              <button key={m.value} type="button" onClick={() => saveMode(m.value)}
                style={{ textAlign: 'left', padding: '12px 14px', borderRadius: 'var(--db-r-sm)', cursor: 'pointer',
                  border: `1px solid ${on ? 'var(--db-accent-border)' : 'var(--db-border)'}`,
                  background: on ? 'var(--db-accent-bg)' : 'var(--db-card)', transition: 'border-color .12s, background .12s' }}>
                <div style={{ fontWeight: 600, color: on ? 'var(--db-accent-text)' : 'var(--db-text)' }}>{m.title}</div>
                <div style={{ fontSize: 13, color: 'var(--db-muted)', marginTop: 2 }}>{m.blurb}</div>
              </button>
            )
          })}
        </div>
        {modeState === 'saved' && <div style={{ fontSize: 12, color: 'var(--db-accent-text)', marginTop: 8 }}>✓ Saved</div>}
      </div>

      {/* Destinations */}
      <div className="db-card" style={cardStyle}>
        <label className="db-field-label">Transfer destinations</label>
        <p style={{ fontSize: 13, color: 'var(--db-muted)', margin: '0 0 12px' }}>
          Domestic numbers only. Stored encrypted, shown masked.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 14 }}>
          {activeDests.length === 0 && <div style={{ fontSize: 13, color: 'var(--db-muted)' }}>No destinations yet.</div>}
          {activeDests.map(d => (
            <div key={d.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '9px 0', borderTop: '1px solid var(--db-border-lt)' }}>
              <span style={{ color: 'var(--db-text)', fontSize: 14 }}>{destLabel(d)}</span>
              <button type="button" className="db-btn db-btn--danger-ghost db-btn--sm" onClick={() => removeDestination(d.id)}>Remove</button>
            </div>
          ))}
        </div>
        <div style={rowStyle}>
          <input className="db-input" style={{ flex: '1 1 150px' }} value={newNumber}
            onChange={e => setNewNumber(e.target.value)} placeholder="+1 647 555 0123" />
          <input className="db-input" style={{ flex: '1 1 140px' }} value={newLabel}
            onChange={e => setNewLabel(e.target.value)} placeholder="Label (e.g. On-call)" />
          <select className="db-select" style={{ flex: '0 0 auto' }} value={newType} onChange={e => setNewType(e.target.value)}>
            <option value="phone">Regular</option>
            <option value="urgent">Urgent / on-call</option>
          </select>
          <button type="button" className="db-btn db-btn--primary" onClick={requestAddDestination}
            disabled={!newNumber.trim() || destState === 'saving' || confirmNum !== null}>
            {destState === 'saving' ? 'Adding…' : 'Add'}
          </button>
        </div>
        {confirmNum && (
          <div style={{ marginTop: 12, padding: '12px 14px', borderRadius: 'var(--db-r-sm)',
            border: '1px solid var(--db-accent-border)', background: 'var(--db-accent-bg)' }}>
            <div style={{ fontSize: 13, color: 'var(--db-text)' }}>
              Add this number? <strong style={{ fontVariantNumeric: 'tabular-nums' }}>{confirmNum}</strong>
            </div>
            <div style={{ fontSize: 12, color: 'var(--db-muted)', margin: '4px 0 10px' }}>
              Double-check the area code — it’s masked once saved.
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className="db-btn db-btn--primary db-btn--sm" onClick={submitDestination}>Confirm &amp; add</button>
              <button type="button" className="db-btn db-btn--sm" onClick={() => setConfirmNum(null)}>Edit</button>
            </div>
          </div>
        )}
        {destErr && <div style={{ fontSize: 12, color: 'var(--db-danger-text)', marginTop: 8 }}>{destErr}</div>}
      </div>

      {/* Where should calls go */}
      <div className="db-card" style={cardStyle}>
        <label className="db-field-label">Where should calls go?</label>
        <div style={{ display: 'grid', gap: 14, marginTop: 4, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <div>
            <div style={{ fontSize: 13, color: 'var(--db-muted)', marginBottom: 5 }}>Default human destination</div>
            <select className="db-select" style={{ width: '100%' }} value={profile.default_destination_id ?? ''}
              onChange={e => saveProfileField({ default_destination_id: e.target.value || null })}>
              <option value="">— none —</option>
              {activeDests.map(d => <option key={d.id} value={d.id}>{destLabel(d)}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 13, color: 'var(--db-muted)', marginBottom: 5 }}>Urgent / on-call destination</div>
            <select className="db-select" style={{ width: '100%' }} value={profile.urgent_destination_id ?? ''}
              onChange={e => saveProfileField({ urgent_destination_id: e.target.value || null })}>
              <option value="">— none —</option>
              {activeDests.map(d => <option key={d.id} value={d.id}>{destLabel(d)}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* Rules */}
      <div className="db-card" style={cardStyle}>
        <label className="db-field-label">Routing rules</label>
        <p style={{ fontSize: 13, color: 'var(--db-muted)', margin: '0 0 12px' }}>When the caller’s reason matches, send them to a destination.</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 14 }}>
          {rules.length === 0 && <div style={{ fontSize: 13, color: 'var(--db-muted)' }}>No rules yet.</div>}
          {rules.map(r => (
            <div key={r.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '9px 0', borderTop: '1px solid var(--db-border-lt)' }}>
              <span style={{ color: 'var(--db-text)', fontSize: 14 }}>
                <strong>{String((r.match as { intent?: string }).intent ?? 'any')}</strong>
                {' → '}{activeDests.find(d => d.id === r.destination_id)?.label ?? 'destination'}
              </span>
              <button type="button" className="db-btn db-btn--danger-ghost db-btn--sm" onClick={() => removeRule(r.id)}>Remove</button>
            </div>
          ))}
        </div>
        <div style={rowStyle}>
          <input className="db-input" style={{ flex: '1 1 160px' }} value={ruleIntent}
            onChange={e => setRuleIntent(e.target.value)} placeholder="Intent (e.g. billing)" />
          <select className="db-select" style={{ flex: '1 1 180px' }} value={ruleDest} onChange={e => setRuleDest(e.target.value)}>
            <option value="">Destination…</option>
            {activeDests.map(d => <option key={d.id} value={d.id}>{destLabel(d)}</option>)}
          </select>
          <button type="button" className="db-btn db-btn--primary" onClick={addRule}
            disabled={!ruleIntent.trim() || !ruleDest || ruleState === 'saving'}>
            {ruleState === 'saving' ? 'Adding…' : 'Add rule'}
          </button>
        </div>
        {ruleState === 'error' && <div style={{ fontSize: 12, color: 'var(--db-danger-text)', marginTop: 8 }}>Could not add rule — try again.</div>}
      </div>

      {/* Simulate */}
      <div className="db-card" style={cardStyle}>
        <label className="db-field-label">Test it</label>
        <p style={{ fontSize: 13, color: 'var(--db-muted)', margin: '0 0 12px' }}>See how a caller would be routed. No call is placed.</p>
        <div style={rowStyle}>
          <input className="db-input" style={{ flex: '1 1 220px' }} value={simIntent}
            onChange={e => setSimIntent(e.target.value)} placeholder="Pretend the caller wants… (e.g. billing)" />
          <select className="db-select" style={{ flex: '0 0 auto' }} value={simUrgency} onChange={e => setSimUrgency(e.target.value)}>
            <option value="low">Low</option><option value="normal">Normal</option><option value="urgent">Urgent</option>
          </select>
          <button type="button" className="db-btn db-btn--dark" onClick={runSimulate}>Simulate</button>
        </div>
        {decision && (
          <div style={{ marginTop: 14, padding: '12px 14px', borderRadius: 'var(--db-r-sm)',
            border: '1px solid var(--db-border)', background: 'var(--db-subtle)' }}>
            <span className={`db-badge db-badge--${DECISION_TONE[decision.decision] ?? 'neutral'}`}>{decision.decision}</span>
            {decision.destination && <span style={{ marginLeft: 10, color: 'var(--db-text)', fontSize: 14 }}>→ {destLabel(decision.destination)}</span>}
            <div style={{ fontSize: 12, color: 'var(--db-muted)', marginTop: 6 }}>{decision.reason}</div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function CallHandlingPageWrapper() {
  return <CallHandlingPage />
}
