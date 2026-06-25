'use client'

import { useState } from 'react'
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

export default function ForgotPasswordPage() {
  const [email, setEmail]     = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent]       = useState(false)
  const [error, setError]     = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    // Base URL: prefer an explicit override, else the current origin (works for
    // localhost + production as long as the origin is in Supabase's allowlist).
    const base = process.env.NEXT_PUBLIC_SITE_URL || window.location.origin
    try {
      // Intentionally ignore whether the email exists — Supabase does not reveal
      // it, and we always show the same generic success message below.
      await supabase.auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${base}/reset-password`,
      })
      trackEvent('password_reset_requested')
      setSent(true)
    } catch {
      // Neutral failure (network/rate limit). Does not reveal account existence.
      setError("We couldn't send the email right now. Please try again in a moment.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="ob-page">
      <div className="ob-card" style={{ maxWidth: 400 }}>
        <div className="ob-logo">
          <LogoMark />
          <span style={{ fontSize: 14, fontWeight: 400, letterSpacing: '0.04em', color: 'var(--text)' }}>open lines</span>
        </div>

        {sent ? (
          <>
            <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 6 }}>
              Check your email
            </div>
            <div
              style={{
                marginTop: 12, marginBottom: 24, padding: '14px 16px',
                background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 10,
                fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6,
              }}
            >
              If an account exists for this email, we&apos;ve sent a password reset link.
              Please check your inbox (and spam folder).
            </div>
            <Link href="/login" className="btn-submit" style={{ display: 'block', textAlign: 'center', textDecoration: 'none' }}>
              Back to sign in
            </Link>
          </>
        ) : (
          <>
            <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 6 }}>
              Forgot your password?
            </div>
            <div className="ob-sub" style={{ marginBottom: 28 }}>
              Enter your email and we&apos;ll send you a secure password reset link.
            </div>

            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label className="form-label">Email</label>
                <input
                  className="form-input"
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="you@business.com"
                  required
                  autoFocus
                />
              </div>

              {error && <div className="error-msg">{error}</div>}

              <button type="submit" className="btn-submit" disabled={loading || !email.trim()}>
                {loading ? 'Sending…' : 'Send Reset Link'}
              </button>
            </form>

            <div style={{ marginTop: 20, textAlign: 'center', fontSize: 13, color: 'var(--text-3)' }}>
              Remembered it?{' '}
              <Link href="/login" style={{ color: 'var(--accent-text)', textDecoration: 'none' }}>
                Back to sign in
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
