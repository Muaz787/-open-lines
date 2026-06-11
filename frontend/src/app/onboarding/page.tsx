'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import MicButton from '@/app/components/MicButton'
import { trackEvent, identifyUser, getFirstTouch } from '@/lib/analytics'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const INDUSTRIES = [
  { value: 'realtor',    label: 'Realtor / Real Estate' },
  { value: 'clinic',     label: 'Medical Clinic' },
  { value: 'dental',     label: 'Dental / Physiotherapy' },
  { value: 'legal',      label: 'Law Firm / Legal Services' },
  { value: 'plumber',    label: 'Plumbing & HVAC' },
  { value: 'builder',    label: 'Builder / Contractor' },
  { value: 'restaurant', label: 'Restaurant / Café' },
  { value: 'beauty',     label: 'Hair & Beauty Salon' },
  { value: 'parliament', label: 'Member of Parliament' },
  { value: 'custom',     label: 'Other (describe your business)' },
]

const STEPS = [
  'Creating your phone line...',
  'Scraping your website...',
  'Training your AI...',
  'Going live...',
  'Processing your documents...',
]

interface Country {
  code: string
  name: string
  dial: string
  flag: string
}

const COUNTRIES: Country[] = [
  { code: 'CA', name: 'Canada',         dial: '+1',   flag: '🇨🇦' },
  { code: 'US', name: 'United States',  dial: '+1',   flag: '🇺🇸' },
  { code: 'GB', name: 'United Kingdom', dial: '+44',  flag: '🇬🇧' },
  { code: 'AU', name: 'Australia',      dial: '+61',  flag: '🇦🇺' },
  { code: 'IE', name: 'Ireland',        dial: '+353', flag: '🇮🇪' },
  { code: 'NZ', name: 'New Zealand',    dial: '+64',  flag: '🇳🇿' },
]

function detectCountry(): string {
  try {
    const lang = navigator.language ?? ''
    if (lang.includes('-')) {
      const cc = lang.split('-').pop()?.toUpperCase() ?? ''
      if (COUNTRIES.some(c => c.code === cc)) return cc
    }
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    if (/Toronto|Vancouver|Edmonton|Winnipeg|Halifax|Regina|St_Johns/.test(tz)) return 'CA'
    if (tz.startsWith('America/')) return 'US'
    if (/Dublin/.test(tz)) return 'IE'
    if (/London/.test(tz)) return 'GB'
    if (tz.startsWith('Australia/')) return 'AU'
    if (/Auckland|Wellington|Christchurch/.test(tz)) return 'NZ'
  } catch {}
  return 'CA'
}

function fileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (ext === 'pdf')  return '📄'
  if (['docx', 'doc'].includes(ext)) return '📝'
  if (['xlsx', 'xls'].includes(ext)) return '📊'
  return '📃'
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

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
  const [step, setStep]             = useState<1 | 2>(1)
  const [form, setForm]             = useState({
    business_name:        '',
    industry:             'realtor',
    owner_name:           '',
    country:              'CA',
    wa_country:           'CA',
    wa_local:             '',
    website_url:          '',
    extra_instructions:   '',
    agent_name:           '',
    business_description: '',
    email:                '',
    password:             '',
  })
  const [files, setFiles]           = useState<File[]>([])
  const [dragOver, setDragOver]     = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [stepIndex, setStepIndex]   = useState(0)
  const [result, setResult]         = useState<ProvisionResult | null>(null)
  const [error, setError]           = useState<string | null>(null)
  const fileInputRef                = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const cc = detectCountry()
    setForm(f => ({ ...f, country: cc, wa_country: cc }))
  }, [])

  useEffect(() => {
    const ft = getFirstTouch()
    trackEvent('signup_started', ft)
    trackEvent('onboarding_started', ft)
  }, [])

  useEffect(() => {
    if (!submitting) return
    const totalSteps = files.length > 0 ? STEPS.length : STEPS.length - 1
    const interval = setInterval(() => {
      setStepIndex(i => Math.min(i + 1, totalSteps - 1))
    }, 7000)
    return () => clearInterval(interval)
  }, [submitting, files.length])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target
    if (name === 'country') {
      setForm(f => ({ ...f, country: value, wa_country: value }))
    } else {
      setForm(f => ({ ...f, [name]: value }))
    }
  }

  // Append dictated text to a form field (used by the mic buttons)
  const appendField = (name: 'business_description' | 'extra_instructions', t: string) => {
    setForm(f => {
      const prev = (f[name] || '').trim()
      return { ...f, [name]: (prev ? prev + ' ' : '') + t }
    })
  }

  const addFiles = useCallback((incoming: FileList | null) => {
    if (!incoming) return
    const allowed = ['pdf', 'docx', 'doc', 'xlsx', 'xls', 'txt', 'md', 'csv']
    const newFiles = Array.from(incoming).filter(f => {
      const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
      return allowed.includes(ext)
    })
    setFiles(prev => {
      const existing = new Set(prev.map(f => f.name))
      const unique = newFiles.filter(f => !existing.has(f.name))
      return [...prev, ...unique].slice(0, 10)
    })
  }, [])

  const removeFile = (name: string) =>
    setFiles(prev => prev.filter(f => f.name !== name))

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    addFiles(e.dataTransfer.files)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    setStepIndex(0)

    trackEvent('onboarding_step_completed', { step_number: 2, step_name: 'knowledge_contact' })
    // PRIVACY: only the *presence* of instructions is tracked — never the text
    if (form.extra_instructions.trim()) {
      trackEvent('instructions_added', { length: form.extra_instructions.trim().length })
    }

    const dialCode = COUNTRIES.find(c => c.code === form.wa_country)?.dial ?? '+1'
    const localNum = form.wa_local.replace(/\D/g, '')
    const whatsapp = localNum ? `${dialCode}${localNum}` : ''

    const body: Record<string, string> = {
      business_name: form.business_name,
      industry:      form.industry,
      country:       form.country,
    }
    if (form.owner_name)              body.owner_name              = form.owner_name
    if (whatsapp)                     body.whatsapp_number         = whatsapp
    if (form.website_url)             body.website_url             = form.website_url
    if (form.agent_name)              body.agent_name              = form.agent_name
    if (form.extra_instructions)      body.extra_instructions      = form.extra_instructions
    if (form.business_description)    body.business_description    = form.business_description
    if (form.email)                   body.email                   = form.email
    if (form.password)                body.password                = form.password

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
      const provisioned: ProvisionResult = await res.json()

      // Sign in immediately so the dashboard session is established
      if (form.email && form.password) {
        const { data: signInData } = await supabase.auth.signInWithPassword({ email: form.email, password: form.password })
        if (signInData?.user) {
          identifyUser(signInData.user.id, {
            email: form.email,
            tenant_id: provisioned.tenant_id,
            business_name: form.business_name,
            industry: form.industry,
            ...getFirstTouch(),
          })
        }
      }

      // Upload documents if any (non-fatal)
      if (files.length > 0) {
        setStepIndex(STEPS.length - 1)
        try {
          const fd = new FormData()
          files.forEach(f => fd.append('files', f))
          await fetch(`${API}/knowledge/upload/${provisioned.tenant_id}`, {
            method: 'POST',
            body: fd,
          })
          // PRIVACY: only the file count is tracked — never names or contents
          trackEvent('knowledge_base_uploaded', { file_count: files.length, source: 'onboarding' })
        } catch {}
      }

      trackEvent('onboarding_completed', { tenant_id: provisioned.tenant_id, ...getFirstTouch() })
      setResult(provisioned)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const totalSteps  = files.length > 0 ? STEPS.length : STEPS.length - 1
  const progressPct = submitting ? ((stepIndex + 1) / totalSteps) * 100 : 0
  const selectedDial = COUNTRIES.find(c => c.code === form.wa_country)?.dial ?? '+1'
  const selectedFlag = COUNTRIES.find(c => c.code === form.wa_country)?.flag ?? '🌐'

  return (
    <div className="ob-page" id="onboarding">
      <motion.div
        className="ob-card"
        initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
        style={{ maxWidth: result || submitting ? 480 : 520 }}
      >
        <div className="ob-logo">
          <LogoMark />
          <span style={{ fontSize: 14, fontWeight: 400, letterSpacing: '0.04em', color: 'var(--text)' }}>open lines</span>
        </div>

        <AnimatePresence mode="wait">

          {/* ── SUCCESS ── */}
          {result && (
            <motion.div key="success" className="success-wrap"
              initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.4 }}>
              <div style={{ fontSize: 36, marginBottom: 8 }}>🎉</div>
              <div className="success-msg" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>You're live.</div>
              <div className="success-number">{result.phone_number}</div>
              <div className="success-label">Share this number with your clients</div>
              <Link href={`/dashboard/${result.tenant_id}`}>
                <button className="btn-dashboard">View your dashboard →</button>
              </Link>
            </motion.div>
          )}

          {/* ── LOADING ── */}
          {!result && submitting && (
            <motion.div key="loading" className="progress-wrap"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div style={{ fontSize: 32, marginBottom: 20 }}>
                <motion.span animate={{ rotate: 360 }}
                  transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}
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

          {/* ── FORM ── */}
          {!result && !submitting && (
            <motion.div key="form" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>

              {/* Step indicator */}
              <div className="step-indicator">
                <div className="step-node">
                  <div className={`step-dot ${step === 1 ? 'active' : 'done'}`}>
                    {step > 1 ? '✓' : '1'}
                  </div>
                  <span className={`step-label ${step === 1 ? 'active' : ''}`}>Basics</span>
                </div>
                <div className="step-line" />
                <div className="step-node">
                  <div className={`step-dot ${step === 2 ? 'active' : 'pending'}`}>2</div>
                  <span className={`step-label ${step === 2 ? 'active' : ''}`}>Knowledge & Contact</span>
                </div>
              </div>

              <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
                {step === 1 ? 'Get your AI receptionist' : 'Knowledge & contact'}
              </div>
              <div className="ob-sub">
                {step === 1
                  ? "Fill in your business details. We'll provision a real phone number and live AI agent in under 60 seconds."
                  : 'Upload documents to train your AI, add custom instructions, and set your WhatsApp number for call summaries.'}
              </div>

              {/* ── Step 1 ── */}
              {step === 1 && (
                <div>
                  <div className="form-group">
                    <label className="form-label">Business Name *</label>
                    <input className="form-input" name="business_name" value={form.business_name}
                      onChange={handleChange} placeholder="e.g. Riverside Medical Clinic" required />
                  </div>

                  <div className="form-group">
                    <label className="form-label">Industry *</label>
                    <select className="form-input" name="industry" value={form.industry} onChange={handleChange}>
                      {INDUSTRIES.map(i => <option key={i.value} value={i.value}>{i.label}</option>)}
                    </select>
                  </div>

                  {form.industry === 'custom' && (
                    <div className="form-group">
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                        <label className="form-label">Describe Your Business *</label>
                        <MicButton size={30} onResult={t => appendField('business_description', t)} />
                      </div>
                      <textarea
                        className="form-input"
                        name="business_description"
                        value={form.business_description}
                        onChange={handleChange}
                        rows={3}
                        placeholder="e.g. We are a family-run pet grooming salon specialising in dogs and cats, offering baths, haircuts, and nail trims."
                        style={{ resize: 'vertical', lineHeight: 1.6 }}
                        required
                      />
                      <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                        Your AI agent's script will be generated from this description
                      </div>
                    </div>
                  )}

                  <div className="form-group">
                    <label className="form-label">Country *</label>
                    <select className="form-input" name="country" value={form.country} onChange={handleChange}>
                      {COUNTRIES.map(c => (
                        <option key={c.code} value={c.code}>{c.flag} {c.name}</option>
                      ))}
                    </select>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                      A local phone number will be provisioned in this country
                    </div>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Owner Name</label>
                    <input className="form-input" name="owner_name" value={form.owner_name}
                      onChange={handleChange} placeholder="Your full name" />
                  </div>

                  <div style={{ borderTop: '1px solid var(--border)', margin: '20px 0 20px', paddingTop: 20 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-3)', letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 14 }}>
                      Create your account
                    </div>
                    <div className="form-group">
                      <label className="form-label">Email *</label>
                      <input className="form-input" name="email" type="email" value={form.email}
                        onChange={handleChange} placeholder="you@business.com" required />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Password *</label>
                      <input className="form-input" name="password" type="password" value={form.password}
                        onChange={handleChange} placeholder="Min. 8 characters" required minLength={8} />
                    </div>
                  </div>

                  <button
                    type="button"
                    className="btn-submit"
                    disabled={
                      !form.business_name ||
                      !form.email ||
                      form.password.length < 8 ||
                      (form.industry === 'custom' && !form.business_description.trim())
                    }
                    onClick={() => {
                      trackEvent('onboarding_step_completed', { step_number: 1, step_name: 'basics', industry: form.industry })
                      trackEvent('business_profile_completed', { industry: form.industry })
                      setStep(2)
                    }}
                  >
                    Next →
                  </button>
                </div>
              )}

              {/* ── Step 2 ── */}
              {step === 2 && (
                <form onSubmit={handleSubmit}>

                  <div className="form-group">
                    <label className="form-label">
                      Agent Name{' '}
                      <span style={{ color: 'var(--text-3)', fontWeight: 300, textTransform: 'none', letterSpacing: 0 }}>
                        (optional, default "Alex")
                      </span>
                    </label>
                    <input className="form-input" name="agent_name" value={form.agent_name}
                      onChange={handleChange} placeholder="Alex" />
                  </div>

                  <div className="form-group">
                    <label className="form-label">Website URL</label>
                    <input className="form-input" name="website_url" value={form.website_url}
                      onChange={handleChange} placeholder="https://yourbusiness.com" type="url" />
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                      We'll scrape this to train your AI on your services and FAQs
                    </div>
                  </div>

                  <div className="form-group">
                    <label className="form-label">
                      Documents{' '}
                      <span style={{ color: 'var(--text-3)', fontWeight: 300, textTransform: 'none', letterSpacing: 0 }}>
                        (optional — up to 10 files, 10 MB each)
                      </span>
                    </label>

                    {/* Drop zone */}
                    <div
                      className={`upload-zone${dragOver ? ' drag-over' : ''}`}
                      onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                      onDragLeave={() => setDragOver(false)}
                      onDrop={handleDrop}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <div className="upload-zone-icon">📎</div>
                      <div className="upload-zone-text">Drop files here or click to browse</div>
                      <div className="upload-zone-hint">PDF · Word (.docx) · Excel (.xlsx) · Plain text (.txt / .csv / .md)</div>
                    </div>

                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.csv"
                      style={{ display: 'none' }}
                      onChange={e => addFiles(e.target.files)}
                    />

                    {/* File list */}
                    {files.length > 0 && (
                      <div className="file-list">
                        {files.map(f => (
                          <div key={f.name} className="file-item">
                            <span className="file-icon">{fileIcon(f.name)}</span>
                            <span className="file-name">{f.name}</span>
                            <span className="file-size">{formatBytes(f.size)}</span>
                            <button type="button" className="file-remove" onClick={() => removeFile(f.name)}>×</button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="form-group">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                      <label className="form-label">
                        Extra Instructions{' '}
                        <span style={{ color: 'var(--text-3)', fontWeight: 300, textTransform: 'none', letterSpacing: 0 }}>
                          (optional)
                        </span>
                      </label>
                      <MicButton size={30} onResult={t => appendField('extra_instructions', t)} />
                    </div>
                    <textarea
                      className="form-input"
                      name="extra_instructions"
                      value={form.extra_instructions}
                      onChange={handleChange}
                      rows={4}
                      placeholder={`e.g. Always mention our 24/7 emergency line is 1-800-XXX-XXXX.\nWe don't handle commercial properties.\nIf asked about pricing, say quotes are provided after a consultation.`}
                      style={{ resize: 'vertical', lineHeight: 1.6 }}
                    />
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                      These instructions are added directly to your AI agent's behaviour on top of the default script
                    </div>
                  </div>

                  <div className="form-group">
                    <label className="form-label">WhatsApp Number</label>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <select
                        name="wa_country"
                        value={form.wa_country}
                        onChange={handleChange}
                        className="form-input"
                        style={{ width: 110, flexShrink: 0, paddingRight: 6 }}
                      >
                        {COUNTRIES.map(c => (
                          <option key={c.code} value={c.code}>{c.flag} {c.dial}</option>
                        ))}
                      </select>
                      <input
                        className="form-input"
                        name="wa_local"
                        value={form.wa_local}
                        onChange={handleChange}
                        placeholder="416 555 0100"
                        inputMode="tel"
                        style={{ flex: 1 }}
                      />
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                      {form.wa_local
                        ? `Will be saved as ${selectedFlag} ${selectedDial}${form.wa_local.replace(/\D/g, '')}`
                        : 'Call summaries will be sent here after each call'}
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
                    <button
                      type="button"
                      className="btn-ghost"
                      onClick={() => setStep(1)}
                      style={{ flex: '0 0 auto', padding: '13px 20px' }}
                    >
                      ← Back
                    </button>
                    <button type="submit" className="btn-submit" style={{ flex: 1, margin: 0 }}>
                      Provision my line →
                    </button>
                  </div>

                  {error && <div className="error-msg">{error}</div>}
                </form>
              )}

            </motion.div>
          )}

        </AnimatePresence>
      </motion.div>
    </div>
  )
}
