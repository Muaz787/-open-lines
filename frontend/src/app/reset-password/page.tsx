'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { trackEvent } from '@/lib/analytics'

const LogoMark = () => (
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

type Phase = 'verifying' | 'form' | 'invalid' | 'done'

export default function ResetPasswordPage() {
  const router = useRouter()
  const [phase, setPhase]         = useState<Phase>('verifying')
  const [newPw, setNewPw]         = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [saving, setSaving]       = useState(false)
  const [error, setError]         = useState<string | null>(null)

  // Detect the Supabase recovery session. The supabase-js client auto-exchanges
  // the recovery token in the URL (detectSessionInUrl) and emits PASSWORD_RECOVERY.
  useEffect(() => {
    let settled = false
    const markReady = () => { if (!settled) { settled = true; setPhase('form') } }

    // If Supabase redirected back with an error (e.g. expired/used link), the
    // details land in the query string or the URL hash fragment.
    const url = new URL(window.location.href)
    const hash = new URLSearchParams(url.hash.replace(/^#/, ''))
    const errDesc = url.searchParams.get('error_description') || hash.get('error_description')
      || url.searchParams.get('error') || hash.get('error')
    if (errDesc) {
      settled = true
      setPhase('invalid')
      return
    }

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'PASSWORD_RECOVERY' || (event === 'SIGNED_IN' && session)) markReady()
    })

    // Fallback: a session may already exist (event fired before we subscribed).
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) markReady()
      else {
        // Give detectSessionInUrl a moment to exchange the token before deciding.
        setTimeout(() => { if (!settled) { settled = true; setPhase('invalid') } }, 2500)
      }
    })

    return () => subscription.unsubscribe()
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (newPw.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (newPw !== confirmPw) { setError("Passwords don't match."); return }
    setSaving(true)
    try {
      const { error: upErr } = await supabase.auth.updateUser({ password: newPw })
      if (upErr) throw upErr
      trackEvent('password_reset_completed')
      setPhase('done')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not update password. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  // Reuse the existing post-auth routing: tenant_id -> dashboard, else admin, else login.
  const goToDashboard = async () => {
    const { data: { user } } = await supabase.auth.getUser()
    const tenantId = user?.user_metadata?.tenant_id
    if (tenantId) { router.replace(`/dashboard/${tenantId}`); return }
    const { data: { session } } = await supabase.auth.getSession()
    try {
      const meRes = await fetch('/api/admin/me', {
        headers: { Authorization: `Bearer ${session?.access_token}` },
      })
      if (meRes.ok) { router.replace('/admin'); return }
    } catch { /* fall through */ }
    router.replace('/login')
  }

  return (
    <div className="ob-page">
      <div className="ob-card" style={{ maxWidth: 400 }}>
        <div className="ob-logo">
          <LogoMark />
          <span style={{ fontSize: 14, fontWeight: 400, letterSpacing: '0.04em', color: 'var(--text)' }}>open lines</span>
        </div>

        {phase === 'verifying' && (
          <>
            <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 6 }}>
              Verifying your link…
            </div>
            <div className="ob-sub">One moment while we confirm your reset link.</div>
          </>
        )}

        {phase === 'invalid' && (
          <>
            <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 6 }}>
              This link is invalid or has expired
            </div>
            <div className="ob-sub" style={{ marginBottom: 24 }}>
              Password reset links can only be used once and expire after a short time.
              Please request a new one.
            </div>
            <Link href="/forgot-password" className="btn-submit" style={{ display: 'block', textAlign: 'center', textDecoration: 'none' }}>
              Request a new link
            </Link>
          </>
        )}

        {phase === 'form' && (
          <>
            <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 6 }}>
              Choose a new password
            </div>
            <div className="ob-sub" style={{ marginBottom: 28 }}>
              Enter a new password for your account.
            </div>

            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label className="form-label">New password</label>
                <input
                  className="form-input"
                  type="password"
                  value={newPw}
                  onChange={e => setNewPw(e.target.value)}
                  placeholder="Min. 8 characters"
                  required
                  autoFocus
                />
              </div>

              <div className="form-group">
                <label className="form-label">Confirm new password</label>
                <input
                  className="form-input"
                  type="password"
                  value={confirmPw}
                  onChange={e => setConfirmPw(e.target.value)}
                  placeholder="Repeat new password"
                  required
                />
              </div>

              {error && <div className="error-msg">{error}</div>}

              <button type="submit" className="btn-submit" disabled={saving || !newPw || !confirmPw}>
                {saving ? 'Updating…' : 'Update password'}
              </button>
            </form>
          </>
        )}

        {phase === 'done' && (
          <>
            <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 6 }}>
              Password updated successfully
            </div>
            <div className="ob-sub" style={{ marginBottom: 24 }}>
              You can now continue to your dashboard.
            </div>
            <button type="button" className="btn-submit" onClick={goToDashboard}>
              Continue to Dashboard
            </button>
          </>
        )}
      </div>
    </div>
  )
}
