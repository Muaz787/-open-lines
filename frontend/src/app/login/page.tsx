'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { trackEvent, identifyUser } from '@/lib/analytics'

const LogoMark = () => (
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { data, error: authError } = await supabase.auth.signInWithPassword({ email, password })
      if (authError) throw authError
      const tenantId = data.user?.user_metadata?.tenant_id
      if (!tenantId) {
        // Check if this is an admin account
        const meRes = await fetch('/api/admin/me', {
          headers: { Authorization: `Bearer ${data.session?.access_token}` },
        })
        if (meRes.ok) {
          trackEvent('login_completed')
          router.replace('/admin')
          return
        }
        throw new Error('No dashboard found for this account.')
      }
      if (data.user) {
        identifyUser(data.user.id, { email: data.user.email, tenant_id: tenantId })
        trackEvent('login_completed')
      }
      router.replace(`/dashboard/${tenantId}`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.')
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

        <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 6 }}>
          Sign in
        </div>
        <div className="ob-sub" style={{ marginBottom: 28 }}>
          Access your AI receptionist dashboard.
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

          <div className="form-group">
            <label className="form-label">Password</label>
            <input
              className="form-input"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
            <div style={{ marginTop: 8, textAlign: 'right' }}>
              <Link href="/forgot-password" style={{ fontSize: 12.5, color: 'var(--text-3)', textDecoration: 'none' }}>
                Forgot your password?
              </Link>
            </div>
          </div>

          {error && <div className="error-msg">{error}</div>}

          <button type="submit" className="btn-submit" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in →'}
          </button>
        </form>

        <div style={{ marginTop: 20, textAlign: 'center', fontSize: 13, color: 'var(--text-3)' }}>
          Don&apos;t have an account?{' '}
          <Link href="/onboarding" style={{ color: 'var(--accent-text)', textDecoration: 'none' }}>
            Get started
          </Link>
        </div>
      </div>
    </div>
  )
}
