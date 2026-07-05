'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

import { authedFetch } from '@/lib/api'
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

const TONE_OPTIONS = [
  'Warm and friendly',
  'Premium and calm',
  'Fast and efficient',
  'Professional and formal',
  'Reassuring and patient',
]

const PRIORITY_OPTIONS = [
  'Book an appointment whenever it makes sense for the caller',
  'Qualify the caller before booking',
  'Always collect a deposit when one is required',
  'Flag or transfer emergencies immediately',
  "Capture the caller's name and reason for calling before ending",
  "Don't quote exact prices unless confirmed in the knowledge base",
]

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  business_phone?: string
  subscription_plan?: string
  subscription_status?: string
}

function SettingsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const router = useRouter()

  const [tenant, setTenant]               = useState<Tenant | null>(null)

  const [notifEmail, setNotifEmail]               = useState('')
  const [emailEnabled, setEmailEnabled]           = useState(true)
  const [smsEnabled, setSmsEnabled]               = useState(false)
  const [whatsappEnabled, setWhatsappEnabled]     = useState(false)
  const [smsNumber, setSmsNumber]                 = useState('')
  const [notifEmailState, setNotifEmailState]     = useState<SaveState>('idle')
  const [bizPhone, setBizPhone]                   = useState('')
  const [bizPhoneState, setBizPhoneState]         = useState<SaveState>('idle')
  const [email, setEmail]                         = useState('')
  const [loginEmail, setLoginEmail]               = useState('')
  const [emailPw, setEmailPw]                     = useState('')
  const [emailState, setEmailState]               = useState<SaveState>('idle')
  const [emailMsg, setEmailMsg]                   = useState('')
  const [currentPw, setCurrentPw]         = useState('')
  const [newPw, setNewPw]                 = useState('')
  const [confirmPw, setConfirmPw]         = useState('')
  const [pwState, setPwState]             = useState<SaveState>('idle')
  const [pwMsg, setPwMsg]                 = useState('')

  // Receptionist behaviour (owner operating layer)
  const [bizInstructions, setBizInstructions] = useState('')
  const [subtype, setSubtype]                 = useState('')
  const [tone, setTone]                       = useState('')
  const [priorities, setPriorities]           = useState<string[]>([])
  const [behaviorState, setBehaviorState]     = useState<SaveState>('idle')
  const [behaviorMsg, setBehaviorMsg]         = useState('')

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) { router.replace('/login'); return }
      setEmail(data.user.email ?? '')
      setLoginEmail(data.user.email ?? '')
    })
    authedFetch(`${API}/onboarding/status/${tenantId}`).then(async tRes => {
      if (tRes.ok) {
        const d = await tRes.json()
        setTenant(d)
        if (d?.notification_email) setNotifEmail(d.notification_email)
        if (d?.email_enabled != null) setEmailEnabled(!!d.email_enabled)
        if (d?.sms_enabled != null) setSmsEnabled(!!d.sms_enabled)
        if (d?.whatsapp_enabled != null) setWhatsappEnabled(!!d.whatsapp_enabled)
        if (d?.sms_alert_number) setSmsNumber(d.sms_alert_number)
        if (d?.business_phone) setBizPhone(d.business_phone)
        if (d?.extra_instructions) setBizInstructions(d.extra_instructions)
        if (d?.business_subtype) setSubtype(d.business_subtype)
        if (d?.receptionist_tone) setTone(d.receptionist_tone)
        if (Array.isArray(d?.operating_priorities)) setPriorities(d.operating_priorities)
      }
    })
  }, [tenantId, router])

  const movePriority = (i: number, dir: -1 | 1) => {
    setPriorities(list => {
      const j = i + dir
      if (j < 0 || j >= list.length) return list
      const next = [...list]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }

  const saveBehavior = async () => {
    setBehaviorState('saving'); setBehaviorMsg('')
    try {
      const res = await authedFetch(`${API}/onboarding/settings/${tenantId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          extra_instructions:   bizInstructions.trim(),
          business_subtype:     subtype.trim(),
          receptionist_tone:    tone.trim(),
          operating_priorities: priorities,
        }),
      })
      if (res.ok) { setBehaviorState('saved'); setTimeout(() => setBehaviorState('idle'), 2500) }
      else {
        const d = await res.json().catch(() => ({}))
        setBehaviorState('error'); setBehaviorMsg(d?.detail || 'Save failed — try again')
      }
    } catch { setBehaviorState('error'); setBehaviorMsg('Save failed — try again') }
  }

  const saveNotifEmail = async () => {
    setNotifEmailState('saving')
    try {
      const res = await authedFetch(`${API}/onboarding/settings/${tenantId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notification_email: notifEmail.trim(), email_enabled: emailEnabled, sms_enabled: smsEnabled, whatsapp_enabled: whatsappEnabled, sms_alert_number: smsNumber.trim() }),
      })
      setNotifEmailState(res.ok ? 'saved' : 'error')
      setTimeout(() => setNotifEmailState('idle'), 3000)
    } catch {
      setNotifEmailState('error')
      setTimeout(() => setNotifEmailState('idle'), 3000)
    }
  }

  const saveBizPhone = async () => {
    setBizPhoneState('saving')
    try {
      const res = await authedFetch(`${API}/onboarding/settings/${tenantId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ business_phone: bizPhone.trim() }),
      })
      setBizPhoneState(res.ok ? 'saved' : 'error')
      setTimeout(() => setBizPhoneState('idle'), 3000)
    } catch {
      setBizPhoneState('error')
      setTimeout(() => setBizPhoneState('idle'), 3000)
    }
  }

  const saveEmail = async () => {
    setEmailMsg('')
    const fail = (msg: string) => {
      setEmailState('error'); setEmailMsg(msg)
      setTimeout(() => { setEmailState('idle'); setEmailMsg('') }, 6000)
    }
    const newEmail = email.trim()
    if (!newEmail) return fail('Enter a new email address.')
    if (newEmail.toLowerCase() === loginEmail.toLowerCase()) return fail('That is already your login email.')
    if (!emailPw) return fail('Enter your current password to confirm.')

    setEmailState('saving')
    // Step-up: re-authenticate with the current password before this sensitive
    // change (consistent with the password-change flow). Blocks an idle/borrowed
    // session from changing the account email. Supabase "Secure email change"
    // then requires confirmation from BOTH the old and new inbox.
    const { error: signInError } = await supabase.auth.signInWithPassword({ email: loginEmail, password: emailPw })
    if (signInError) return fail('Current password is incorrect.')

    const { error } = await supabase.auth.updateUser({ email: newEmail })
    if (error) {
      setEmailState('error')
      setEmailMsg(error.message)
    } else {
      setEmailState('saved')
      setEmailPw('')
      setEmailMsg('Confirm from BOTH your current and new inbox to complete the change.')
    }
    setTimeout(() => { setEmailState('idle'); setEmailMsg('') }, 8000)
  }

  const savePassword = async () => {
    if (!currentPw) { setPwState('error'); setPwMsg('Enter your current password.'); setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000); return }
    if (newPw.length < 8) { setPwState('error'); setPwMsg('New password must be at least 8 characters.'); setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000); return }
    if (newPw !== confirmPw) { setPwState('error'); setPwMsg("New passwords don't match."); setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000); return }
    setPwState('saving'); setPwMsg('')
    const { data: userData } = await supabase.auth.getUser()
    const { error: signInError } = await supabase.auth.signInWithPassword({ email: userData.user?.email ?? '', password: currentPw })
    if (signInError) { setPwState('error'); setPwMsg('Current password is incorrect.'); setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000); return }
    const { error } = await supabase.auth.updateUser({ password: newPw })
    if (error) { setPwState('error'); setPwMsg(error.message) }
    else { setPwState('saved'); setPwMsg('Password updated.'); setCurrentPw(''); setNewPw(''); setConfirmPw('') }
    setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000)
  }

  return (
    <>

        {/* Desktop topbar */}
        <div className="db-topbar">
          <span className="db-topbar-title">Settings</span>
          {tenant?.twilio_phone_number && (
            <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: 'var(--db-accent)', marginRight: 5 }} />
              {tenant.twilio_phone_number}
            </div>
          )}
        </div>

        {/* Content */}
        <div className="db-content">
          <div className="db-form-grid">

            {/* ── Notifications ── */}
            <section>
            <div className="db-page-heading">Notifications</div>

            {/* ── Call summary notifications ── */}
            <div className="db-card" style={{ overflow: 'hidden' }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--db-border-lt)' }}>
                <label style={{ fontSize: 14, fontWeight: 600, color: 'var(--db-text)' }}>
                  Call summary notifications
                </label>
                <div className="db-field-help">
                  Get a summary after every call. Turn on each channel you&rsquo;d like.
                </div>

                {/* Per-channel toggles */}
                {([
                  ['Email', 'A summary email after every call.', emailEnabled, setEmailEnabled],
                  ['SMS', 'A text message to your mobile.', smsEnabled, setSmsEnabled],
                  ['WhatsApp', 'A WhatsApp message to your mobile.', whatsappEnabled, setWhatsappEnabled],
                ] as const).map(([label, desc, on, setOn]) => (
                  <div key={label} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '11px 0', borderTop: '1px solid var(--db-border-lt)' }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--db-text)' }}>{label}</div>
                      <div style={{ fontSize: 12, color: 'var(--db-muted)' }}>{desc}</div>
                    </div>
                    <button
                      type="button"
                      className={`db-switch${on ? ' on' : ''}`}
                      onClick={() => setOn(v => !v)}
                      aria-pressed={on}
                      aria-label={`Toggle ${label} notifications`}
                    />
                  </div>
                ))}

                {/* Email destination */}
                {emailEnabled && (
                  <div style={{ marginTop: 14 }}>
                    <label className="db-field-label" style={{ fontSize: 12 }}>Email address</label>
                    <input
                      type="email" value={notifEmail} onChange={e => setNotifEmail(e.target.value)}
                      placeholder="you@example.com" className="db-input"
                    />
                    <div className="db-field-help" style={{ marginBottom: 0, marginTop: 4 }}>Can differ from your login email.</div>
                  </div>
                )}

                {/* Shared mobile destination — for SMS and/or WhatsApp */}
                {(smsEnabled || whatsappEnabled) && (
                  <div style={{ marginTop: 14 }}>
                    <label className="db-field-label" style={{ fontSize: 12 }}>Mobile number</label>
                    <input
                      type="tel" value={smsNumber} onChange={e => setSmsNumber(e.target.value)}
                      placeholder={bizPhone.trim() ? `Defaults to ${bizPhone}` : '+1 (647) 555-0123'}
                      className="db-input"
                    />
                    <div className="db-field-help" style={{ marginBottom: 0, marginTop: 4 }}>
                      Used for {smsEnabled && whatsappEnabled ? 'SMS and WhatsApp' : smsEnabled ? 'SMS' : 'WhatsApp'} alerts — use a mobile/SMS-capable number.
                      {bizPhone.trim() && ' Leave blank to use your business phone.'}
                      {whatsappEnabled && ' WhatsApp alerts use an approved message template and require this number to be on WhatsApp.'}
                      {!smsNumber.trim() && !bizPhone.trim() && (
                        <span style={{ color: 'var(--db-danger-text)' }}> Add a number here or a business phone below.</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button
                  className="db-btn db-btn--accent-ghost"
                  onClick={saveNotifEmail}
                  disabled={notifEmailState === 'saving' || (emailEnabled && !notifEmail.trim())}
                >
                  {notifEmailState === 'saving' ? 'Saving…' : 'Save'}
                </button>
                {notifEmailState === 'saved' && <span style={{ fontSize: 12, color: 'var(--db-accent-text)' }}>✓ Saved</span>}
                {notifEmailState === 'error'  && <span style={{ fontSize: 12, color: 'var(--db-danger-text)' }}>Save failed — try again</span>}
              </div>
            </div>
            </section>

            {/* ── Receptionist behaviour ── */}
            <section>
            <div className="db-page-heading">Receptionist behaviour</div>
            <div className="db-card" style={{ overflow: 'hidden' }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--db-border-lt)' }}>

                {/* Business type */}
                <label className="db-field-label" style={{ marginBottom: 4 }}>What kind of business is this?</label>
                <input
                  type="text" value={subtype} onChange={e => setSubtype(e.target.value)}
                  placeholder="e.g. sushi restaurant, med spa, appliance repair" className="db-input"
                />
                <div className="db-field-help" style={{ marginTop: 4 }}>Helps your AI use the right language for your business.</div>

                {/* Tone */}
                <label className="db-field-label" style={{ marginBottom: 4, marginTop: 16 }}>How should your AI receptionist sound?</label>
                <select value={tone} onChange={e => setTone(e.target.value)} className="db-input">
                  <option value="">Default (warm &amp; professional)</option>
                  {TONE_OPTIONS.map(t => <option key={t} value={t}>{t}</option>)}
                </select>

                {/* Priorities */}
                <label className="db-field-label" style={{ marginBottom: 4, marginTop: 16 }}>What should your AI prioritize on calls?</label>
                <div className="db-field-help" style={{ marginTop: 0 }}>Order matters — earlier items win if two conflict. Leave empty to use sensible defaults.</div>
                {priorities.map((p, i) => (
                  <div key={p} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', borderTop: '1px solid var(--db-border-lt)' }}>
                    <span style={{ fontSize: 12, color: 'var(--db-muted)', width: 16 }}>{i + 1}.</span>
                    <span style={{ flex: 1, fontSize: 13, color: 'var(--db-text)' }}>{p}</span>
                    <button type="button" aria-label="Move up" onClick={() => movePriority(i, -1)} disabled={i === 0}
                      style={{ cursor: i === 0 ? 'default' : 'pointer', opacity: i === 0 ? 0.3 : 1, background: 'none', border: 'none', fontSize: 14 }}>▲</button>
                    <button type="button" aria-label="Move down" onClick={() => movePriority(i, 1)} disabled={i === priorities.length - 1}
                      style={{ cursor: i === priorities.length - 1 ? 'default' : 'pointer', opacity: i === priorities.length - 1 ? 0.3 : 1, background: 'none', border: 'none', fontSize: 14 }}>▼</button>
                    <button type="button" aria-label="Remove" onClick={() => setPriorities(list => list.filter(x => x !== p))}
                      style={{ cursor: 'pointer', background: 'none', border: 'none', fontSize: 15, color: 'var(--db-muted)' }}>✕</button>
                  </div>
                ))}
                {PRIORITY_OPTIONS.filter(o => !priorities.includes(o)).length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
                    {PRIORITY_OPTIONS.filter(o => !priorities.includes(o)).map(o => (
                      <button key={o} type="button" onClick={() => setPriorities(list => [...list, o])}
                        style={{ cursor: 'pointer', fontSize: 12, padding: '5px 10px', borderRadius: 16, border: '1px solid var(--db-border-lt)', background: 'transparent', color: 'var(--db-text)' }}>
                        + {o}
                      </button>
                    ))}
                  </div>
                )}

                {/* Business instructions */}
                <label className="db-field-label" style={{ marginBottom: 4, marginTop: 16 }}>Anything specific your AI receptionist should follow?</label>
                <textarea
                  value={bizInstructions} onChange={e => setBizInstructions(e.target.value)}
                  rows={4} className="db-input"
                  placeholder="e.g. Always mention our free first consultation. Confirm parking is available on request."
                  style={{ resize: 'vertical', fontFamily: 'inherit' }}
                />
                <div className="db-field-help" style={{ marginTop: 4 }}>
                  These instructions guide how your AI receptionist handles calls. They cannot override safety, privacy, or legal rules.
                </div>
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button className="db-btn db-btn--accent-ghost" onClick={saveBehavior} disabled={behaviorState === 'saving'}>
                  {behaviorState === 'saving' ? 'Saving…' : 'Save'}
                </button>
                {behaviorState === 'saved' && <span style={{ fontSize: 12, color: 'var(--db-accent-text)' }}>✓ Saved — your AI is updating</span>}
                {behaviorState === 'error' && <span style={{ fontSize: 12, color: 'var(--db-danger-text)' }}>{behaviorMsg || 'Save failed — try again'}</span>}
              </div>
            </div>
            </section>

            {/* ── Email address ── */}
            <section>
            <div className="db-page-heading">Login email</div>
            <div className="db-card" style={{ overflow: 'hidden' }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--db-border-lt)' }}>
                <label className="db-field-label" style={{ marginBottom: 4 }}>
                  Account login email
                </label>
                <div className="db-field-help">
                  The address you use to sign in and receive password resets. This is separate
                  from your call-summary email above. For your security, changing it requires
                  your current password, and you must then confirm from <strong>both</strong> your
                  current and new inbox before it takes effect.
                </div>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                  placeholder="you@example.com" className="db-input" autoComplete="email" />
                <label className="db-field-label" style={{ fontSize: 12, marginTop: 12 }}>Current password</label>
                <input type="password" value={emailPw} onChange={e => setEmailPw(e.target.value)}
                  placeholder="Confirm it's you" className="db-input" autoComplete="current-password" />
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button className="db-btn db-btn--accent-ghost" onClick={saveEmail}
                  disabled={emailState === 'saving' || !email.trim() || !emailPw}>
                  {emailState === 'saving' ? 'Sending…' : 'Update email'}
                </button>
                {emailMsg && (
                  <span style={{ fontSize: 12, color: emailState === 'error' ? 'var(--db-danger-text)' : 'var(--db-accent-text)', lineHeight: 1.4, maxWidth: 280 }}>
                    {emailMsg}
                  </span>
                )}
              </div>
            </div>
            </section>

            {/* ── Business phone ── */}
            <section>
            <div className="db-page-heading">Business phone</div>
            <div className="db-card" style={{ overflow: 'hidden' }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--db-border-lt)' }}>
                <label className="db-field-label" style={{ marginBottom: 4 }}>
                  Your business phone number
                </label>
                <div className="db-field-help">
                  Your own published business line — separate from your AI receptionist number
                  {tenant?.twilio_phone_number ? ` (${tenant.twilio_phone_number})` : ''}. Used as
                  your contact number on the account; update it here if it changes.
                </div>
                <input
                  type="tel" value={bizPhone} onChange={e => setBizPhone(e.target.value)}
                  placeholder="+1 (647) 555-0123" className="db-input"
                />
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button className="db-btn db-btn--accent-ghost" onClick={saveBizPhone} disabled={bizPhoneState === 'saving'}>
                  {bizPhoneState === 'saving' ? 'Saving…' : 'Save'}
                </button>
                {bizPhoneState === 'saved' && <span style={{ fontSize: 12, color: 'var(--db-accent-text)' }}>✓ Saved</span>}
                {bizPhoneState === 'error' && <span style={{ fontSize: 12, color: 'var(--db-danger-text)' }}>Enter a valid phone number</span>}
              </div>
            </div>
            </section>

            {/* ── Password ── */}
            <section>
            <div className="db-page-heading">Password</div>
            <div className="db-card" style={{ overflow: 'hidden' }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--db-border-lt)', display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <label className="db-field-label" style={{ marginBottom: 6 }}>Current password</label>
                  <input type="password" value={currentPw} onChange={e => setCurrentPw(e.target.value)}
                    placeholder="Your current password" className="db-input" />
                </div>
                <div style={{ height: 1, background: 'var(--db-border-lt)' }} />
                <div>
                  <label className="db-field-label" style={{ marginBottom: 6 }}>New password</label>
                  <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)}
                    placeholder="Min. 8 characters" className="db-input" />
                </div>
                <div>
                  <label className="db-field-label" style={{ marginBottom: 6 }}>Confirm new password</label>
                  <input type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)}
                    placeholder="Repeat new password" className="db-input" />
                </div>
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button className="db-btn db-btn--accent-ghost" onClick={savePassword} disabled={pwState === 'saving' || !currentPw || !newPw}>
                  {pwState === 'saving' ? 'Updating…' : 'Update password'}
                </button>
                {pwMsg && <span style={{ fontSize: 12, color: pwState === 'error' ? 'var(--db-danger-text)' : 'var(--db-accent-text)' }}>{pwMsg}</span>}
              </div>
            </div>
            </section>

          </div>
        </div>
    </>
  )
}

export default function SettingsPageWrapper() {
  return <SettingsPage />
}
