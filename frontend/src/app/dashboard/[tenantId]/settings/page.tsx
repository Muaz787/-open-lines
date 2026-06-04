'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

interface Tenant {
  id: string
  business_name: string
  industry: string
  twilio_phone_number?: string
  subscription_plan?: string
  subscription_status?: string
}

function SettingsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const router = useRouter()

  const [tenant, setTenant]               = useState<Tenant | null>(null)

  const [whatsapp, setWhatsapp]           = useState('')
  const [whatsappState, setWhatsappState] = useState<SaveState>('idle')
  const [email, setEmail]                 = useState('')
  const [emailState, setEmailState]       = useState<SaveState>('idle')
  const [emailMsg, setEmailMsg]           = useState('')
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
    fetch(`${API}/onboarding/status/${tenantId}`).then(async tRes => {
      if (tRes.ok) {
        const d = await tRes.json()
        setTenant(d)
        if (d?.whatsapp_number) setWhatsapp(d.whatsapp_number)
      }
    })
  }, [tenantId, router])

  const saveWhatsapp = async () => {
    setWhatsappState('saving')
    try {
      const res = await fetch(`${API}/onboarding/settings/${tenantId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ whatsapp_number: whatsapp.trim() }),
      })
      setWhatsappState(res.ok ? 'saved' : 'error')
      setTimeout(() => setWhatsappState('idle'), 3000)
    } catch {
      setWhatsappState('error')
      setTimeout(() => setWhatsappState('idle'), 3000)
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

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '9px 12px', fontSize: 13,
    border: '1px solid #e8e6e0', borderRadius: 7,
    background: '#fff', color: '#16161a',
    outline: 'none', boxSizing: 'border-box',
    fontFamily: 'var(--font-dm), sans-serif',
  }
  const btnStyle = (disabled = false): React.CSSProperties => ({
    fontSize: 12, fontWeight: 600, padding: '7px 18px',
    borderRadius: 7, border: '1px solid #3dba72',
    background: '#eafaf2', color: '#1a7a45',
    cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    transition: 'opacity 0.15s',
    fontFamily: 'var(--font-dm), sans-serif',
  })

  return (
    <>

        {/* Desktop topbar */}
        <div className="db-topbar">
          <span className="db-topbar-title">Settings</span>
          {tenant?.twilio_phone_number && (
            <div style={{ fontSize: 12, color: '#888' }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#3dba72', marginRight: 5 }} />
              {tenant.twilio_phone_number}
            </div>
          )}
        </div>

        {/* Content */}
        <div className="db-content">
          <div style={{ maxWidth: 520 }}>

            {/* ── Notifications ── */}
            <div className="db-section-title" style={{ marginBottom: 14 }}>Notifications</div>
            <div style={{ border: '1px solid #e8e6e0', borderRadius: 10, background: '#fff', overflow: 'hidden', marginBottom: 24 }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid #f0ede8' }}>
                <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 4 }}>
                  WhatsApp number
                </label>
                <div style={{ fontSize: 12, color: '#aaa', marginBottom: 12, lineHeight: 1.5 }}>
                  After every call, a summary is sent here. Include country code (e.g. +1 416 555 0123).
                </div>
                <input type="tel" value={whatsapp} onChange={e => setWhatsapp(e.target.value)}
                  placeholder="+1 416 555 0123" style={inputStyle} />
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button onClick={saveWhatsapp} disabled={whatsappState === 'saving'} style={btnStyle(whatsappState === 'saving')}>
                  {whatsappState === 'saving' ? 'Saving…' : 'Save'}
                </button>
                {whatsappState === 'saved' && <span style={{ fontSize: 12, color: '#34C759' }}>✓ Saved</span>}
                {whatsappState === 'error' && <span style={{ fontSize: 12, color: '#FF3B30' }}>Save failed — try again</span>}
              </div>
            </div>

            {/* ── Email address ── */}
            <div className="db-section-title" style={{ marginBottom: 14 }}>Email address</div>
            <div style={{ border: '1px solid #e8e6e0', borderRadius: 10, background: '#fff', overflow: 'hidden', marginBottom: 24 }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid #f0ede8' }}>
                <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 12 }}>
                  New email
                </label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                  placeholder="you@example.com" style={inputStyle} />
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button onClick={saveEmail} disabled={emailState === 'saving'} style={btnStyle(emailState === 'saving')}>
                  {emailState === 'saving' ? 'Sending…' : 'Update email'}
                </button>
                {emailMsg && (
                  <span style={{ fontSize: 12, color: emailState === 'error' ? '#FF3B30' : '#34C759', lineHeight: 1.4, maxWidth: 280 }}>
                    {emailMsg}
                  </span>
                )}
              </div>
            </div>

            {/* ── Password ── */}
            <div className="db-section-title" style={{ marginBottom: 14 }}>Password</div>
            <div style={{ border: '1px solid #e8e6e0', borderRadius: 10, background: '#fff', overflow: 'hidden', marginBottom: 24 }}>
              <div style={{ padding: '18px 20px', borderBottom: '1px solid #f0ede8', display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 6 }}>Current password</label>
                  <input type="password" value={currentPw} onChange={e => setCurrentPw(e.target.value)}
                    placeholder="Your current password" style={inputStyle} />
                </div>
                <div style={{ height: 1, background: '#f0ede8' }} />
                <div>
                  <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 6 }}>New password</label>
                  <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)}
                    placeholder="Min. 8 characters" style={inputStyle} />
                </div>
                <div>
                  <label style={{ fontSize: 13, fontWeight: 600, color: '#16161a', display: 'block', marginBottom: 6 }}>Confirm new password</label>
                  <input type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)}
                    placeholder="Repeat new password" style={inputStyle} />
                </div>
              </div>
              <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button onClick={savePassword} disabled={pwState === 'saving' || !currentPw || !newPw}
                  style={btnStyle(pwState === 'saving' || !currentPw || !newPw)}>
                  {pwState === 'saving' ? 'Updating…' : 'Update password'}
                </button>
                {pwMsg && <span style={{ fontSize: 12, color: pwState === 'error' ? '#FF3B30' : '#34C759' }}>{pwMsg}</span>}
              </div>
            </div>

          </div>
        </div>
    </>
  )
}

export default function SettingsPageWrapper() {
  return <SettingsPage />
}
