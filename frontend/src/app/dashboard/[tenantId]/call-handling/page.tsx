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

// Numbered section header — the setup IS a sequence (add destinations → pick where
// calls go → add rules → test), so the step numbers guide the flow.
function StepHeader({ n, title, help }: { n: number; title: string; help?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 11, marginBottom: 15 }}>
      <span aria-hidden style={{
        flex: '0 0 auto', width: 24, height: 24, borderRadius: 7, marginTop: 1,
        display: 'grid', placeItems: 'center', fontSize: 12, fontWeight: 700,
        fontFamily: 'var(--font-mono), ui-monospace, monospace',
        background: 'var(--db-accent-bg)', color: 'var(--db-accent-text)',
        border: '1px solid var(--db-accent-border)',
      }}>{n}</span>
      <div>
        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--db-text)' }}>{title}</div>
        {help && <div style={{ fontSize: 13, color: 'var(--db-muted)', marginTop: 2, lineHeight: 1.5 }}>{help}</div>}
      </div>
    </div>
  )
}

function CallHandlingPage() {
  const { tenantId } = useParams<{ tenantId: string }>()

  const [loading, setLoading]   = useState(true)
  const [entitled, setEntitled] = useState<boolean | null>(null)
  const [profile, setProfile]   = useState<Profile>({})
  const [dests, setDests]       = useState<Destination[]>([])
  const [rules, setRules]       = useState<Rule[]>([])

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

  if (loading) return <div style={{ padding: 28, color: 'var(--db-muted)' }}>Loading…</div>

  if (entitled === false) return (
    <div style={{ padding: 28 }}>
      <div className="db-card" style={{ maxWidth: 560, padding: 26 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: 'var(--db-text)', margin: 0 }}>Call handling &amp; routing</h1>
          <span className="db-badge" style={{ background: 'var(--db-gold-grad)', color: 'var(--db-gold-text)', border: '1px solid var(--db-gold-border)' }}>Pro</span>
        </div>
        <p style={{ color: 'var(--db-muted)', lineHeight: 1.6, margin: '0 0 10px', fontSize: 14 }}>
          Answer routine calls with AI and transfer the ones that need a person to the right
          destination — with a safe fallback if no one picks up.
        </p>
        <p style={{ color: 'var(--db-muted)', margin: 0, fontSize: 14 }}>
          It&rsquo;s available on the <strong style={{ color: 'var(--db-text)' }}>Pro</strong> and{' '}
          <strong style={{ color: 'var(--db-text)' }}>Business</strong> plans.
        </p>
      </div>
    </div>
  )

  const sectionStyle: React.CSSProperties = { padding: '20px 22px', marginBottom: 16 }
  const rowStyle: React.CSSProperties = { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }
  const numFont = 'var(--font-mono), ui-monospace, monospace'
  const short = (d?: Destination | null) => (d ? (d.label || d.number_masked || 'destination') : null)
  const defaultDest = activeDests.find(d => d.id === profile.default_destination_id)
  const hasDefault = !!defaultDest
  const toggleDisabled = actState === 'saving' || (!routingActive && !canActivate)

  return (
    <div style={{ padding: 28, maxWidth: 780 }}>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 600, color: 'var(--db-text)', margin: 0, letterSpacing: '-0.01em' }}>Call handling &amp; routing</h1>
        <p style={{ fontSize: 14, color: 'var(--db-muted)', margin: '5px 0 0', lineHeight: 1.5, maxWidth: 620 }}>
          Answer routine calls with AI and transfer the ones that need a person to the right place — with a safe fallback if no one picks up.
        </p>
      </header>

      {/* ── Activation hero ── */}
      <div className="db-card" style={{ padding: '20px 22px', marginBottom: 20,
        borderColor: routingActive ? 'var(--db-accent-border)' : 'var(--db-border)',
        background: routingActive ? 'var(--db-accent-bg)' : 'var(--db-card)',
        boxShadow: routingActive ? 'var(--db-shadow-sm)' : 'var(--db-shadow-xs)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: '1 1 280px', minWidth: 0 }}>
            <span aria-hidden style={{ width: 10, height: 10, borderRadius: '50%', flex: '0 0 auto',
              background: routingActive ? 'var(--db-accent)' : 'var(--db-faint)',
              boxShadow: routingActive ? '0 0 0 4px var(--db-accent-bg)' : 'none' }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontWeight: 600, fontSize: 15, color: routingActive ? 'var(--db-accent-text)' : 'var(--db-text)' }}>Call routing</span>
                <span className={`db-badge ${routingActive ? 'db-badge--success' : 'db-badge--neutral'}`}>{routingActive ? 'Live' : 'Off'}</span>
              </div>
              <div style={{ fontSize: 13, color: 'var(--db-muted)', marginTop: 3, lineHeight: 1.5 }}>
                {routingActive
                  ? `Routing ${activeDests.length} destination${activeDests.length === 1 ? '' : 's'}${rules.length ? ` · ${rules.length} rule${rules.length === 1 ? '' : 's'}` : ''}${defaultDest ? ` · default: ${short(defaultDest)}` : ''}.`
                  : 'Nothing changes on your calls until you turn this on.'}
              </div>
            </div>
          </div>
          <button type="button" aria-label={routingActive ? 'Turn call routing off' : 'Turn call routing on'}
            className={`db-switch ${routingActive ? 'on' : ''}`}
            onClick={() => setRoutingOn(!routingActive)} disabled={toggleDisabled}
            style={{ opacity: toggleDisabled ? 0.45 : 1, cursor: toggleDisabled ? 'not-allowed' : 'pointer' }} />
        </div>

        {!routingActive && (
          <div style={{ marginTop: 15, paddingTop: 14, borderTop: '1px solid var(--db-border-lt)',
            display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[
              { done: canActivate, label: 'Add at least one transfer destination' },
              { done: hasDefault, label: 'Choose where unmatched callers go (default) — recommended' },
            ].map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: 13,
                color: s.done ? 'var(--db-text)' : 'var(--db-muted)' }}>
                <span aria-hidden style={{ width: 16, height: 16, flex: '0 0 auto', borderRadius: '50%',
                  display: 'grid', placeItems: 'center', fontSize: 10, fontWeight: 700,
                  background: s.done ? 'var(--db-accent)' : 'transparent', color: '#fff',
                  border: s.done ? 'none' : '1.5px solid var(--db-border)' }}>{s.done ? '✓' : ''}</span>
                {s.label}
              </div>
            ))}
          </div>
        )}
        {actWarn && (
          <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--db-warn-text)',
            background: 'var(--db-warn-bg)', borderRadius: 'var(--db-r-sm)', padding: '8px 11px' }}>{actWarn}</div>
        )}
      </div>

      {/* ── 1 · Destinations ── */}
      <div className="db-card" style={sectionStyle}>
        <StepHeader n={1} title="Transfer destinations"
          help="The phone numbers OpenLines can hand callers to. Domestic only, stored encrypted and shown masked." />
        <div style={{ marginBottom: 14 }}>
          {activeDests.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--db-muted)', padding: '12px 14px',
              border: '1px dashed var(--db-border)', borderRadius: 'var(--db-r-sm)', background: 'var(--db-subtle)' }}>
              No destinations yet — add your first one below.
            </div>
          )}
          {activeDests.map((d, i) => (
            <div key={d.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
              padding: '11px 0', borderTop: i === 0 ? 'none' : '1px solid var(--db-border-lt)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, flexWrap: 'wrap' }}>
                <span style={{ fontFamily: numFont, fontSize: 13.5, color: 'var(--db-text)', whiteSpace: 'nowrap' }}>{d.number_masked}</span>
                {d.label && <span style={{ fontSize: 13, color: 'var(--db-muted)' }}>{d.label}</span>}
                {d.type === 'urgent' && <span className="db-badge db-badge--warn">Urgent</span>}
                {d.id === profile.default_destination_id && <span className="db-badge db-badge--success">Default</span>}
              </div>
              <button type="button" className="db-btn db-btn--danger-ghost db-btn--sm" onClick={() => removeDestination(d.id)}>Remove</button>
            </div>
          ))}
        </div>
        <div style={rowStyle}>
          <input className="db-input" style={{ flex: '1 1 150px', fontFamily: numFont }} value={newNumber}
            onChange={e => setNewNumber(e.target.value)} placeholder="+1 647 555 0123" inputMode="tel" />
          <input className="db-input" style={{ flex: '1 1 130px' }} value={newLabel}
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
              Add this number? <strong style={{ fontFamily: numFont }}>{confirmNum}</strong>
            </div>
            <div style={{ fontSize: 12, color: 'var(--db-muted)', margin: '4px 0 10px' }}>
              Double-check the area code — it&rsquo;s masked once saved.
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className="db-btn db-btn--primary db-btn--sm" onClick={submitDestination}>Confirm &amp; add</button>
              <button type="button" className="db-btn db-btn--ghost db-btn--sm" onClick={() => setConfirmNum(null)}>Edit</button>
            </div>
          </div>
        )}
        {destErr && <div style={{ fontSize: 12, color: 'var(--db-danger-text)', marginTop: 8 }}>{destErr}</div>}
      </div>

      {/* ── 2 · Where calls go ── */}
      <div className="db-card" style={sectionStyle}>
        <StepHeader n={2} title="Where should calls go?"
          help="Pick from your destinations above. Urgent callers go to the on-call line; everyone else who needs a person goes to the default." />
        {activeDests.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--db-muted)' }}>Add a destination first.</div>
        ) : (
          <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 5 }}>Default human destination</div>
              <select className="db-select" style={{ width: '100%' }} value={profile.default_destination_id ?? ''}
                onChange={e => saveProfileField({ default_destination_id: e.target.value || null })}>
                <option value="">— none (take a callback) —</option>
                {activeDests.map(d => <option key={d.id} value={d.id}>{short(d)}</option>)}
              </select>
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)', marginBottom: 5 }}>Urgent / on-call destination</div>
              <select className="db-select" style={{ width: '100%' }} value={profile.urgent_destination_id ?? ''}
                onChange={e => saveProfileField({ urgent_destination_id: e.target.value || null })}>
                <option value="">— none —</option>
                {activeDests.map(d => <option key={d.id} value={d.id}>{short(d)}</option>)}
              </select>
            </div>
          </div>
        )}
      </div>

      {/* ── 3 · Rules ── */}
      <div className="db-card" style={sectionStyle}>
        <StepHeader n={3} title="Routing rules"
          help="Send callers to a specific destination based on why they're calling. Checked top to bottom; urgent always wins, and anything unmatched uses the default." />
        <div style={{ marginBottom: 14 }}>
          {rules.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--db-muted)', padding: '12px 14px',
              border: '1px dashed var(--db-border)', borderRadius: 'var(--db-r-sm)', background: 'var(--db-subtle)' }}>
              No rules yet — optional. Without rules, callers who need a person go to the default.
            </div>
          )}
          {rules.map((r, i) => {
            const dest = activeDests.find(d => d.id === r.destination_id)
            return (
              <div key={r.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
                padding: '11px 0', borderTop: i === 0 ? 'none' : '1px solid var(--db-border-lt)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, minWidth: 0, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, color: 'var(--db-text)' }}>{String((r.match as { intent?: string }).intent ?? 'any')}</span>
                  <span style={{ color: 'var(--db-faint)' }}>→</span>
                  <span className="db-badge db-badge--neutral">{short(dest) ?? 'destination'}</span>
                </div>
                <button type="button" className="db-btn db-btn--danger-ghost db-btn--sm" onClick={() => removeRule(r.id)}>Remove</button>
              </div>
            )
          })}
        </div>
        <div style={rowStyle}>
          <input className="db-input" style={{ flex: '1 1 150px' }} value={ruleIntent}
            onChange={e => setRuleIntent(e.target.value)} placeholder="If caller wants… (e.g. billing)" />
          <select className="db-select" style={{ flex: '1 1 170px' }} value={ruleDest} onChange={e => setRuleDest(e.target.value)}>
            <option value="">Send to…</option>
            {activeDests.map(d => <option key={d.id} value={d.id}>{short(d)}</option>)}
          </select>
          <button type="button" className="db-btn db-btn--primary" onClick={addRule}
            disabled={!ruleIntent.trim() || !ruleDest || ruleState === 'saving'}>
            {ruleState === 'saving' ? 'Adding…' : 'Add rule'}
          </button>
        </div>
        {ruleState === 'error' && <div style={{ fontSize: 12, color: 'var(--db-danger-text)', marginTop: 8 }}>Could not add rule — try again.</div>}
      </div>

      {/* ── 4 · Test ── */}
      <div className="db-card" style={sectionStyle}>
        <StepHeader n={4} title="Test it" help="Preview how a caller would be routed. No call is placed." />
        <div style={rowStyle}>
          <input className="db-input" style={{ flex: '1 1 220px' }} value={simIntent}
            onChange={e => setSimIntent(e.target.value)} placeholder="Pretend the caller wants… (e.g. billing)" />
          <select className="db-select" style={{ flex: '0 0 auto' }} value={simUrgency} onChange={e => setSimUrgency(e.target.value)}>
            <option value="low">Low urgency</option><option value="normal">Normal</option><option value="urgent">Urgent</option>
          </select>
          <button type="button" className="db-btn db-btn--dark" onClick={runSimulate} disabled={!simIntent.trim()}>Simulate</button>
        </div>
        {decision && (
          <div style={{ marginTop: 14, padding: '14px 16px', borderRadius: 'var(--db-r-sm)',
            border: '1px solid var(--db-border)', background: 'var(--db-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span className={`db-badge db-badge--${DECISION_TONE[decision.decision] ?? 'neutral'}`}>{decision.decision}</span>
              {decision.destination && (
                <span style={{ color: 'var(--db-text)', fontSize: 14 }}>
                  → {short(decision.destination)}
                  {decision.destination.number_masked &&
                    <span style={{ fontFamily: numFont, color: 'var(--db-muted)', marginLeft: 6, fontSize: 13 }}>{decision.destination.number_masked}</span>}
                </span>
              )}
            </div>
            <div style={{ fontSize: 12, color: 'var(--db-muted)', marginTop: 8 }}>{decision.reason}</div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function CallHandlingPageWrapper() {
  return <CallHandlingPage />
}
