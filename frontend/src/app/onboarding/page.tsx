'use client'

import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const INDUSTRIES = [
  { value: 'realtor',    label: 'Realtor' },
  { value: 'clinic',     label: 'Medical Clinic' },
  { value: 'parliament', label: 'Member of Parliament' },
]

const STEPS = [
  'Creating your phone line...',
  'Scraping your website...',
  'Training your AI...',
  'Going live...',
]

interface ProvisionResult {
  tenant_id: string
  phone_number: string
  assistant_id: string
  status: string
  dashboard_url: string
}

const LogoMark = () => (
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

export default function OnboardingPage() {
  const [form, setForm] = useState({
    business_name: '',
    industry: 'realtor',
    owner_name: '',
    whatsapp_number: '',
    website_url: '',
    agent_name: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [stepIndex, setStepIndex]   = useState(0)
  const [result, setResult]         = useState<ProvisionResult | null>(null)
  const [error, setError]           = useState<string | null>(null)

  useEffect(() => {
    if (!submitting) return
    const interval = setInterval(() => {
      setStepIndex(i => Math.min(i + 1, STEPS.length - 1))
    }, 7000)
    return () => clearInterval(interval)
  }, [submitting])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setForm(f => ({ ...f, [e.target.name]: e.target.value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    setStepIndex(0)

    const body: Record<string, string> = { ...form }
    if (!body.agent_name) delete body.agent_name

    try {
      const res = await fetch(`${API}/onboarding/provision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail ?? `Request failed (${res.status})`)
      }
      setResult(await res.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const progressPct = submitting ? ((stepIndex + 1) / STEPS.length) * 100 : 0

  return (
    <div className="ob-page" id="onboarding">
      <motion.div className="ob-card"
        initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}>

        <div className="ob-logo">
          <LogoMark />
          <span style={{ fontSize: 14, fontWeight: 400, letterSpacing: '0.04em', color: 'var(--text)' }}>open lines</span>
        </div>

        <AnimatePresence mode="wait">

          {/* SUCCESS */}
          {result && (
            <motion.div key="success" className="success-wrap"
              initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.4 }}>
              <div style={{ fontSize: 36, marginBottom: 8 }}>🎉</div>
              <div className="success-msg" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
                You're live.
              </div>
              <div className="success-number">{result.phone_number}</div>
              <div className="success-label">Share this number with your clients</div>
              <Link href={`/dashboard/${result.tenant_id}`}>
                <button className="btn-dashboard">View your dashboard →</button>
              </Link>
            </motion.div>
          )}

          {/* LOADING */}
          {!result && submitting && (
            <motion.div key="loading" className="progress-wrap"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div style={{ fontSize: 32, marginBottom: 20 }}>
                <motion.span animate={{ rotate: 360 }} transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}
                  style={{ display: 'inline-block' }}>⚙</motion.span>
              </div>
              <div className="progress-step">
                <AnimatePresence mode="wait">
                  <motion.span key={stepIndex}
                    initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.3 }}>
                    {STEPS[stepIndex]}
                  </motion.span>
                </AnimatePresence>
              </div>
              <div className="progress-track">
                <motion.div className="progress-bar" style={{ width: `${progressPct}%` }} />
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 14 }}>
                This takes about 60 seconds — hang tight.
              </div>
            </motion.div>
          )}

          {/* FORM */}
          {!result && !submitting && (
            <motion.div key="form" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
                Get your AI receptionist
              </div>
              <div className="ob-sub">
                Fill in the details below. We'll provision a real phone number and live AI agent in under 60 seconds.
              </div>

              <form onSubmit={handleSubmit}>
                <div className="form-group">
                  <label className="form-label">Business Name *</label>
                  <input className="form-input" name="business_name" value={form.business_name}
                    onChange={handleChange} placeholder="e.g. Shahid Real Estate" required />
                </div>

                <div className="form-group">
                  <label className="form-label">Industry *</label>
                  <select className="form-input" name="industry" value={form.industry} onChange={handleChange}>
                    {INDUSTRIES.map(i => <option key={i.value} value={i.value}>{i.label}</option>)}
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Owner Name</label>
                  <input className="form-input" name="owner_name" value={form.owner_name}
                    onChange={handleChange} placeholder="Your full name" />
                </div>

                <div className="form-group">
                  <label className="form-label">WhatsApp Number</label>
                  <input className="form-input" name="whatsapp_number" value={form.whatsapp_number}
                    onChange={handleChange} placeholder="+1 416 555 0100" />
                </div>

                <div className="form-group">
                  <label className="form-label">Website URL</label>
                  <input className="form-input" name="website_url" value={form.website_url}
                    onChange={handleChange} placeholder="https://yourbusiness.com" type="url" />
                </div>

                <div className="form-group">
                  <label className="form-label">Agent Name <span style={{ color: 'var(--text-3)', fontWeight: 300, textTransform: 'none', letterSpacing: 0 }}>(optional, default "Alex")</span></label>
                  <input className="form-input" name="agent_name" value={form.agent_name}
                    onChange={handleChange} placeholder="Alex" />
                </div>

                <button type="submit" className="btn-submit" disabled={!form.business_name}>
                  Provision my line →
                </button>

                {error && (
                  <div className="error-msg">{error}</div>
                )}
              </form>
            </motion.div>
          )}

        </AnimatePresence>
      </motion.div>
    </div>
  )
}
