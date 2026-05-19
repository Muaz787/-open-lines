'use client'

import { useState, useEffect, Suspense } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

function SettingsPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const router = useRouter()

  const [whatsapp, setWhatsapp]       = useState('')
  const [whatsappState, setWhatsappState] = useState<SaveState>('idle')

  const [email, setEmail]             = useState('')
  const [emailState, setEmailState]   = useState<SaveState>('idle')
  const [emailMsg, setEmailMsg]       = useState('')

  const [newPw, setNewPw]             = useState('')
  const [confirmPw, setConfirmPw]     = useState('')
  const [pwState, setPwState]         = useState<SaveState>('idle')
  const [pwMsg, setPwMsg]             = useState('')

  // Auth guard + load current values
  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) { router.replace('/login'); return }
      setEmail(data.user.email ?? '')
    })
    fetch(`${API}/onboarding/status/${tenantId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.whatsapp_number) setWhatsapp(d.whatsapp_number) })
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
    if (newPw !== confirmPw) {
      setPwState('error')
      setPwMsg("Passwords don't match.")
      setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000)
      return
    }
    if (newPw.length < 8) {
      setPwState('error')
      setPwMsg('Password must be at least 8 characters.')
      setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000)
      return
    }
    setPwState('saving')
    setPwMsg('')
    const { error } = await supabase.auth.updateUser({ password: newPw })
    if (error) {
      setPwState('error')
      setPwMsg(error.message)
    } else {
      setPwState('saved')
      setPwMsg('Password updated.')
      setNewPw('')
      setConfirmPw('')
    }
    setTimeout(() => { setPwState('idle'); setPwMsg('') }, 4000)
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', paddingBottom: 60 }}>

      {/* Nav */}
      <div className="db-nav">
        <div className="nav-logo">
          <svg width="26" height="26" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
            <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
          </svg>
          <span className="logo-name" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Open Lines</span>
        </div>
        <div className="db-nav-actions">
          <Link href={`/dashboard/${tenantId}`} className="db-nav-btn">← Dashboard</Link>
        </div>
      </div>

      <div style={{ maxWidth: 560, margin: '0 auto', padding: '40px 20px 0' }}>

        <div style={{
          fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
          color: 'var(--text-3)', marginBottom: 6,
        }}>
          Account
        </div>
        <h1 style={{
          fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 32,
          fontFamily: 'var(--font-syne), sans-serif', letterSpacing: '-0.02em',
        }}>
          Settings
        </h1>

        {/* ── Notifications ── */}
        <section style={{ marginBottom: 24 }}>
          <div className="db-section-title" style={{ marginBottom: 14 }}>Notifications</div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg-2)', overflow: 'hidden' }}>
            <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--border)' }}>
              <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', display: 'block', marginBottom: 4 }}>
                WhatsApp number
              </label>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 12, lineHeight: 1.5 }}>
                After every call, a summary is sent here. Include country code (e.g. +1 416 555 0123).
              </div>
              <input
                type="tel"
                value={whatsapp}
                onChange={e => setWhatsapp(e.target.value)}
                placeholder="+1 416 555 0123"
                style={{
                  width: '100%', padding: '9px 12px', fontSize: 13,
                  border: '1px solid var(--border-2)', borderRadius: 7,
                  background: 'var(--bg)', color: 'var(--text)',
                  outline: 'none', boxSizing: 'border-box',
                }}
              />
            </div>
            <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <button
                onClick={saveWhatsapp}
                disabled={whatsappState === 'saving'}
                style={{
                  fontSize: 12, fontWeight: 600, padding: '7px 18px',
                  borderRadius: 7, border: '1px solid var(--accent)',
                  background: 'var(--accent-dim)', color: 'var(--accent)',
                  cursor: whatsappState === 'saving' ? 'default' : 'pointer',
                  opacity: whatsappState === 'saving' ? 0.6 : 1,
                  transition: 'opacity 0.15s',
                }}
              >
                {whatsappState === 'saving' ? 'Saving…' : 'Save'}
              </button>
              {whatsappState === 'saved' && (
                <span style={{ fontSize: 12, color: '#34C759' }}>✓ Saved</span>
              )}
              {whatsappState === 'error' && (
                <span style={{ fontSize: 12, color: '#FF3B30' }}>Save failed — try again</span>
              )}
            </div>
          </div>
        </section>

        {/* ── Email address ── */}
        <section style={{ marginBottom: 24 }}>
          <div className="db-section-title" style={{ marginBottom: 14 }}>Email address</div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg-2)', overflow: 'hidden' }}>
            <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--border)' }}>
              <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', display: 'block', marginBottom: 12 }}>
                New email
              </label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                style={{
                  width: '100%', padding: '9px 12px', fontSize: 13,
                  border: '1px solid var(--border-2)', borderRadius: 7,
                  background: 'var(--bg)', color: 'var(--text)',
                  outline: 'none', boxSizing: 'border-box',
                }}
              />
            </div>
            <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <button
                onClick={saveEmail}
                disabled={emailState === 'saving'}
                style={{
                  fontSize: 12, fontWeight: 600, padding: '7px 18px',
                  borderRadius: 7, border: '1px solid var(--accent)',
                  background: 'var(--accent-dim)', color: 'var(--accent)',
                  cursor: emailState === 'saving' ? 'default' : 'pointer',
                  opacity: emailState === 'saving' ? 0.6 : 1,
                  transition: 'opacity 0.15s',
                }}
              >
                {emailState === 'saving' ? 'Sending…' : 'Update email'}
              </button>
              {emailMsg && (
                <span style={{ fontSize: 12, color: emailState === 'error' ? '#FF3B30' : '#34C759', lineHeight: 1.4, maxWidth: 280 }}>
                  {emailMsg}
                </span>
              )}
            </div>
          </div>
        </section>

        {/* ── Password ── */}
        <section>
          <div className="db-section-title" style={{ marginBottom: 14 }}>Password</div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg-2)', overflow: 'hidden' }}>
            <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div>
                <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', display: 'block', marginBottom: 6 }}>
                  New password
                </label>
                <input
                  type="password"
                  value={newPw}
                  onChange={e => setNewPw(e.target.value)}
                  placeholder="Min. 8 characters"
                  style={{
                    width: '100%', padding: '9px 12px', fontSize: 13,
                    border: '1px solid var(--border-2)', borderRadius: 7,
                    background: 'var(--bg)', color: 'var(--text)',
                    outline: 'none', boxSizing: 'border-box',
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', display: 'block', marginBottom: 6 }}>
                  Confirm password
                </label>
                <input
                  type="password"
                  value={confirmPw}
                  onChange={e => setConfirmPw(e.target.value)}
                  placeholder="Repeat new password"
                  style={{
                    width: '100%', padding: '9px 12px', fontSize: 13,
                    border: '1px solid var(--border-2)', borderRadius: 7,
                    background: 'var(--bg)', color: 'var(--text)',
                    outline: 'none', boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>
            <div style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <button
                onClick={savePassword}
                disabled={pwState === 'saving' || !newPw}
                style={{
                  fontSize: 12, fontWeight: 600, padding: '7px 18px',
                  borderRadius: 7, border: '1px solid var(--accent)',
                  background: 'var(--accent-dim)', color: 'var(--accent)',
                  cursor: (pwState === 'saving' || !newPw) ? 'default' : 'pointer',
                  opacity: (pwState === 'saving' || !newPw) ? 0.5 : 1,
                  transition: 'opacity 0.15s',
                }}
              >
                {pwState === 'saving' ? 'Updating…' : 'Update password'}
              </button>
              {pwMsg && (
                <span style={{ fontSize: 12, color: pwState === 'error' ? '#FF3B30' : '#34C759' }}>
                  {pwMsg}
                </span>
              )}
            </div>
          </div>
        </section>

      </div>
    </div>
  )
}

export default function SettingsPageWrapper() {
  return (
    <Suspense fallback={
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
        <div style={{ fontSize: 13, color: 'var(--text-3)' }}>Loading…</div>
      </div>
    }>
      <SettingsPage />
    </Suspense>
  )
}
