'use client'

/**
 * How the owner wants call summaries delivered.
 *
 * ONE COMPONENT, TWO SURFACES — the onboarding step and Settings → Notifications
 * both render this, so the question and the answer cannot drift apart.
 *
 * THE BACKEND DECIDES WHAT IS AVAILABLE. This never works out for itself whether
 * SMS or WhatsApp can deliver: SMS is sent from the tenant's own number, and
 * whether that number can send one is a fact only the server can establish. It
 * renders `available` and nothing more. No country logic lives here.
 */
import { useEffect, useMemo, useState } from 'react'
import { authedFetch } from '@/lib/api'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type Channel = 'email' | 'sms' | 'whatsapp'

type Options = {
  channels: Record<Channel, { available: boolean; enabled: boolean; destination: string }>
  dashboard_only: boolean
  suggested_email: string
  explicitly_set: boolean
}

/** Dialling codes offered by the destination picker. The onboarding country is
 *  floated to the top as a convenience; it is never forced. */
const DIAL_CODES: Array<{ iso: string; code: string; label: string }> = [
  { iso: 'CA', code: '+1',   label: 'Canada (+1)' },
  { iso: 'US', code: '+1',   label: 'United States (+1)' },
  { iso: 'IE', code: '+353', label: 'Ireland (+353)' },
  { iso: 'GB', code: '+44',  label: 'United Kingdom (+44)' },
  { iso: 'AU', code: '+61',  label: 'Australia (+61)' },
  { iso: 'NZ', code: '+64',  label: 'New Zealand (+64)' },
]

const CARDS: Array<{ id: Channel; title: string; copy: string }> = [
  { id: 'email',    title: 'Email',    copy: 'Get call summaries in your inbox.' },
  { id: 'sms',      title: 'SMS',      copy: 'Get a short summary by text.' },
  { id: 'whatsapp', title: 'WhatsApp', copy: 'Receive call summaries in WhatsApp.' },
]

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
/** Mirrors telephony.E164_RE and migration 037's CHECK: 7-15 digits total.
 *  Client-side for immediate feedback only — the server revalidates. */
const E164_RE = /^\+[1-9][0-9]{6,14}$/

function splitE164(value: string, fallbackIso: string) {
  const match = DIAL_CODES
    .filter(d => value.startsWith(d.code))
    .sort((a, b) => b.code.length - a.code.length)[0]
  if (match) return { iso: match.iso, national: value.slice(match.code.length) }
  return { iso: fallbackIso, national: value.replace(/^\+/, '') }
}

export default function NotificationPreferences({
  tenantId, country = 'CA', onSaved, saveLabel = 'Save preferences', compact = false,
}: {
  tenantId: string
  country?: string
  onSaved?: () => void
  saveLabel?: string
  compact?: boolean
}) {
  const [opts, setOpts] = useState<Options | null>(null)
  const [loadError, setLoadError] = useState('')
  const [on, setOn] = useState<Record<Channel, boolean>>({ email: false, sms: false, whatsapp: false })
  const [dashboardOnly, setDashboardOnly] = useState(false)
  const [emailTo, setEmailTo] = useState('')
  const [smsIso, setSmsIso] = useState(country)
  const [smsNat, setSmsNat] = useState('')
  const [waIso, setWaIso] = useState(country)
  const [waNat, setWaNat] = useState('')
  const [touched, setTouched] = useState(false)
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [msg, setMsg] = useState('')

  const dial = (iso: string) => DIAL_CODES.find(d => d.iso === iso)?.code ?? '+1'
  const smsE164 = smsNat.trim() ? `${dial(smsIso)}${smsNat.replace(/\D/g, '')}` : ''
  const waE164 = waNat.trim() ? `${dial(waIso)}${waNat.replace(/\D/g, '')}` : ''

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await authedFetch(`${API}/onboarding/notification-options/${tenantId}`)
        if (!res.ok) throw new Error(String(res.status))
        const d: Options = await res.json()
        if (cancelled) return
        setOpts(d)
        setOn({ email: d.channels.email.enabled, sms: d.channels.sms.enabled, whatsapp: d.channels.whatsapp.enabled })
        // A tenant who has never been asked is NOT shown as "Dashboard only" —
        // that would present silence as a decision they made.
        setDashboardOnly(d.explicitly_set && d.dashboard_only)
        setEmailTo(d.channels.email.destination || d.suggested_email || '')
        if (d.channels.sms.destination) {
          const s = splitE164(d.channels.sms.destination, country); setSmsIso(s.iso); setSmsNat(s.national)
        }
        if (d.channels.whatsapp.destination) {
          const w = splitE164(d.channels.whatsapp.destination, country); setWaIso(w.iso); setWaNat(w.national)
        }
      } catch {
        if (!cancelled) setLoadError("We couldn't load your notification options.")
      }
    })()
    return () => { cancelled = true }
  }, [tenantId, country])

  const available = (c: Channel) => !!opts?.channels[c]?.available
  const visibleCards = useMemo(
    () => CARDS.filter(c => c.id === 'email' || !!opts?.channels[c.id]?.available), [opts])

  const pick = (c: Channel) => {
    setTouched(true); setState('idle')
    setDashboardOnly(false)
    setOn(prev => ({ ...prev, [c]: !prev[c] }))
  }
  const pickDashboard = () => {
    setTouched(true); setState('idle')
    setDashboardOnly(true)
    setOn({ email: false, sms: false, whatsapp: false })
  }

  const errors: Partial<Record<Channel, string>> = {}
  if (on.email && !EMAIL_RE.test(emailTo.trim())) errors.email = 'Enter a valid email address.'
  if (on.sms && !E164_RE.test(smsE164)) errors.sms = 'Enter a valid mobile number.'
  if (on.whatsapp && !E164_RE.test(waE164)) errors.whatsapp = 'Enter a valid WhatsApp number.'
  const anyExternal = on.email || on.sms || on.whatsapp
  const chosen = anyExternal || dashboardOnly
  const canSave = chosen && Object.keys(errors).length === 0 && state !== 'saving'

  const save = async () => {
    setState('saving'); setMsg('')
    try {
      const res = await authedFetch(`${API}/onboarding/settings/${tenantId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email_enabled: on.email,
          sms_enabled: on.sms,
          whatsapp_enabled: on.whatsapp,
          ...(on.email ? { notification_email: emailTo.trim() } : {}),
          ...(on.sms ? { sms_alert_number: smsE164 } : {}),
          ...(on.whatsapp ? { whatsapp_alert_number: waE164 } : {}),
        }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        // Never claim success, and never quietly fall back to emailing the
        // account address — the tenant asked for something specific.
        setState('error')
        setMsg(typeof d?.detail === 'string' ? d.detail : "We couldn't save that. Please try again.")
        return
      }
      setState('saved'); onSaved?.()
    } catch {
      setState('error'); setMsg("We couldn't save that. Please try again.")
    }
  }

  const codes = useMemo(() => ([
    ...DIAL_CODES.filter(d => d.iso === country),
    ...DIAL_CODES.filter(d => d.iso !== country),
  ]), [country])

  if (loadError) return <p className="np-error" role="alert">{loadError}</p>
  if (!opts) return <p className="np-muted">Loading your options…</p>

  const phoneField = (
    label: string, iso: string, setIso: (v: string) => void,
    nat: string, setNat: (v: string) => void, id: string, error?: string,
  ) => (
    <div className="np-dest">
      <label htmlFor={id} className="np-dest-label">{label}</label>
      <div className="np-phone">
        <select aria-label="Country code" value={iso}
                onChange={e => { setIso(e.target.value); setTouched(true); setState('idle') }}>
          {codes.map(c => <option key={c.iso} value={c.iso}>{c.label}</option>)}
        </select>
        <input id={id} type="tel" inputMode="tel" autoComplete="tel" value={nat}
               placeholder="87 123 4567"
               aria-invalid={!!error} aria-describedby={error ? `${id}-err` : undefined}
               onChange={e => { setNat(e.target.value); setTouched(true); setState('idle') }} />
      </div>
      {error && <p id={`${id}-err`} className="np-error" role="alert">{error}</p>}
    </div>
  )

  return (
    <div className={compact ? 'np np-compact' : 'np'}>
      {!compact && (
        <>
          <h2 className="np-title">How would you like to receive call summaries?</h2>
          <p className="np-sub">Choose where OpenLines should send a quick recap after each
            call. You can change this anytime.</p>
        </>
      )}

      <div className="np-cards" role="group" aria-label="Call summary delivery channels">
        {visibleCards.map(card => {
          const selected = on[card.id]
          return (
            <button key={card.id} type="button" role="checkbox" aria-checked={selected}
                    className={`np-card${selected ? ' is-selected' : ''}`}
                    onClick={() => pick(card.id)}>
              <span className="np-card-check" aria-hidden="true">{selected ? '✓' : ''}</span>
              <span className="np-card-title">{card.title}</span>
              <span className="np-card-copy">{card.copy}</span>
            </button>
          )
        })}
        <button type="button" role="checkbox" aria-checked={dashboardOnly}
                className={`np-card${dashboardOnly ? ' is-selected' : ''}`}
                onClick={pickDashboard}>
          <span className="np-card-check" aria-hidden="true">{dashboardOnly ? '✓' : ''}</span>
          <span className="np-card-title">Dashboard only</span>
          <span className="np-card-copy">Don&apos;t send notifications. I&apos;ll review calls in OpenLines.</span>
        </button>
      </div>

      {on.email && (
        <div className="np-dest">
          <label htmlFor="np-email" className="np-dest-label">Send call summaries to</label>
          <input id="np-email" type="email" autoComplete="email" value={emailTo}
                 aria-invalid={!!errors.email}
                 aria-describedby={errors.email ? 'np-email-err' : undefined}
                 onChange={e => { setEmailTo(e.target.value); setTouched(true); setState('idle') }} />
          {errors.email && <p id="np-email-err" className="np-error" role="alert">{errors.email}</p>}
        </div>
      )}

      {on.sms && phoneField('Send call summaries to', smsIso, setSmsIso, smsNat, setSmsNat,
                            'np-sms', errors.sms)}

      {on.whatsapp && (
        <>
          {phoneField('Send call summaries to', waIso, setWaIso, waNat, setWaNat,
                      'np-wa', errors.whatsapp)}
          {on.sms && smsNat.trim() !== '' && (
            /* A convenience that COPIES. The fields stay independent afterwards —
               changing one later must not move the other. */
            <button type="button" className="np-link"
                    onClick={() => { setWaIso(smsIso); setWaNat(smsNat); setTouched(true) }}>
              Use the same number for WhatsApp
            </button>
          )}
        </>
      )}

      {touched && !chosen && (
        <p className="np-error" role="alert">
          Pick at least one option — or choose Dashboard only.
        </p>
      )}

      <div className="np-actions">
        <button type="button" className="btn-primary" disabled={!canSave} onClick={save}>
          {state === 'saving' ? 'Saving…' : saveLabel}
        </button>
        {state === 'saved' && <span className="np-ok" role="status">Saved</span>}
        {state === 'error' && <span className="np-error" role="alert">{msg}</span>}
      </div>
    </div>
  )
}
