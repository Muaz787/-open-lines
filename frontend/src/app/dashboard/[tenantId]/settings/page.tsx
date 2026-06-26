'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

import { authedFetch } from '@/lib/api'
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

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
  const [emailState, setEmailState]               = useState<SaveState>('idle')
  const [emailMsg, setEmailMsg]                   = useState('')
  const [currentPw, setCurrentPw]         = useState('')
  const [newPw, setNewPw]                 = useState('')
  const [confirmPw, setConfirmPw]         = useState('')
  const [pwState, setPwState]             = useState<SaveState>('idle')
  const [pwMsg, setPwMsg]                 = useState('')

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) { router.replace('/login'); return }
      setEmail(data.user.email ?? '')
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
      }
    })
  }, [tenantId, router])

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
    setEmailState('saving')
    setEmailMsg('')
    const { error } = await supabase.auth.updateUser({ email: email.trim() })
    if (error) {
      setEmailState('error')
      setEmailMsg(error.message)
    } else {
      setEmailState('saved')
      setEmailMsg('Verification link sent — check your new inbox to confirm.')
    }
    setTimeout(() => { setEmailState('idle'); setEmailMsg('') }, 6000)
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
                  from your call-summary email above. Changing it sends a verification link to
                  the new address — the change only applies once you confirm it.
                </div>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                  placeholder="you@example.com" className="db-input" />
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button className="db-btn db-btn--accent-ghost" onClick={saveEmail} disabled={emailState === 'saving'}>
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
