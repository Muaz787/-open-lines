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

const INDUSTRY_LABEL: Record<string, string> = Object.fromEntries(
  INDUSTRIES.map(i => [i.value, i.label]),
)

// Industry-specific document upload hint
const DOC_HINT: Record<string, string> = {
  restaurant: 'Upload your menu and any set-menu or catering sheets.',
  dental:     'Upload your treatment price list and new-patient info.',
  clinic:     'Upload your services list, pricing, and patient FAQs.',
  realtor:    'Upload listing guides, buyer/seller info, and fee schedules.',
  legal:      'Upload your service descriptions and fee information.',
  plumber:    'Upload your service catalogue and call-out price list.',
  builder:    'Upload project brochures and service information.',
  beauty:     'Upload your service menu and price list.',
  parliament: 'Upload casework guidance and constituency information.',
  custom:     'Upload brochures, price lists, menus, FAQs, or policy documents.',
}

const AGENT_NAMES = ['Alex', 'Emma', 'Sophia', 'Mia', 'Sam']

const PROVISION_STEPS = [
  'Creating your phone line...',
  'Training your AI...',
  'Going live...',
  'Processing your documents...',
]

const ANALYZE_STAGES = [
  'Website found',
  'Business identified',
  'Services extracted',
  'FAQs discovered',
  'Knowledge base prepared',
  'AI receptionist configured',
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

interface Detection {
  business_name: string
  industry: string
  industry_confidence: number
  country: string
  services: string[]
  faq_count: number
  suggested_instructions: string
  scrape_ok: boolean
  knowledge_chars: number
  analysis_token: string
  website_url: string
}

type Stage = 'url' | 'analyzing' | 'customize' | 'review' | 'provisioning' | 'done'

const LogoMark = () => (
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

const Check = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
    <polyline points="20 6 9 17 4 12" />
  </svg>
)

export default function OnboardingPage() {
  const [stage, setStage] = useState<Stage>('url')
  const [form, setForm] = useState({
    website_url:          '',
    email:                '',
    business_name:        '',
    industry:             'custom',
    country:              'CA',
    wa_country:           'CA',
    wa_local:             '',
    extra_instructions:   '',
    agent_name:           'Alex',
    business_description: '',
    password:             '',
  })
  const [detected, setDetected]     = useState<Detection | null>(null)
  const [analysisToken, setToken]   = useState('')
  const [customAgent, setCustomAgent] = useState(false)
  const [files, setFiles]           = useState<File[]>([])
  const [dragOver, setDragOver]     = useState(false)
  const [stepIndex, setStepIndex]   = useState(0)
  const [analyzeIndex, setAnalyzeIndex] = useState(0)
  const [result, setResult]         = useState<ProvisionResult | null>(null)
  const [error, setError]           = useState<string | null>(null)
  const [sampleAvailable, setSampleAvailable] = useState(true)
  const fileInputRef                = useRef<HTMLInputElement>(null)

  useEffect(() => {
    // Country relies on client-only navigator/Intl, so it must be detected
    // after mount (SSR renders the default 'CA' to avoid a hydration mismatch).
    const cc = detectCountry()
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setForm(f => ({ ...f, country: cc, wa_country: cc }))
  }, [])

  useEffect(() => {
    const ft = getFirstTouch()
    trackEvent('signup_started', ft)
    trackEvent('onboarding_started', ft)
  }, [])

  // Provisioning step animation
  useEffect(() => {
    if (stage !== 'provisioning') return
    const total = files.length > 0 ? PROVISION_STEPS.length : PROVISION_STEPS.length - 1
    const interval = setInterval(() => {
      setStepIndex(i => Math.min(i + 1, total - 1))
    }, 12000)
    return () => clearInterval(interval)
  }, [stage, files.length])

  // Analysis checklist animation — advances while the request is in flight,
  // holding the final stage until the real response resolves. (index is reset
  // to 0 in runAnalysis() before the stage switches, so no setState here.)
  useEffect(() => {
    if (stage !== 'analyzing') return
    const interval = setInterval(() => {
      setAnalyzeIndex(i => Math.min(i + 1, ANALYZE_STAGES.length - 2))
    }, 1100)
    return () => clearInterval(interval)
  }, [stage])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target
    if (name === 'country') {
      setForm(f => ({ ...f, country: value, wa_country: value }))
    } else {
      setForm(f => ({ ...f, [name]: value }))
    }
  }

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

  // ── Step 1 → analysis ──
  const runAnalysis = async () => {
    setError(null)
    setAnalyzeIndex(0)
    setStage('analyzing')
    trackEvent('website_analysis_started', { has_url: !!form.website_url })
    const t0 = Date.now()

    try {
      const res = await fetch(`${API}/onboarding/analyze-website`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ website_url: form.website_url, email: form.email }),
      })
      if (!res.ok) throw new Error(`Analysis failed (${res.status})`)
      const d: Detection = await res.json()
      setDetected(d)
      setToken(d.analysis_token || '')

      // Prefill the customize step from detection (keep any user-typed name)
      setForm(f => ({
        ...f,
        business_name:      f.business_name || d.business_name || '',
        industry:           d.industry || 'custom',
        country:            d.country && COUNTRIES.some(c => c.code === d.country) ? d.country : f.country,
        wa_country:         d.country && COUNTRIES.some(c => c.code === d.country) ? d.country : f.wa_country,
        extra_instructions: f.extra_instructions || d.suggested_instructions || '',
      }))
      trackEvent('website_analysis_succeeded', {
        industry_detected: d.industry,
        services_count: (d.services || []).length,
        faq_count: d.faq_count,
        scrape_ok: d.scrape_ok,
        duration_ms: Date.now() - t0,
      })
      setAnalyzeIndex(ANALYZE_STAGES.length - 1)
      setTimeout(() => setStage('customize'), 650)
    } catch {
      // Soft-fail: let the user fill in details manually
      trackEvent('website_analysis_failed', { duration_ms: Date.now() - t0 })
      setDetected(null)
      setStage('customize')
    }
  }

  const skipWebsite = () => {
    trackEvent('website_analysis_skipped', {})
    setDetected(null)
    setStage('customize')
  }

  // ── Final provision ──
  const handleProvision = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setStepIndex(0)
    setStage('provisioning')

    trackEvent('provision_started', { industry: form.industry, has_website: !!form.website_url })
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
      agent_name:    form.agent_name || 'Alex',
      email:         form.email,
      password:      form.password,
    }
    if (whatsapp)                   body.whatsapp_number      = whatsapp
    if (form.website_url)           body.website_url          = detected?.website_url || form.website_url
    if (form.extra_instructions)    body.extra_instructions   = form.extra_instructions
    if (form.business_description)  body.business_description  = form.business_description
    if (analysisToken)              body.analysis_token       = analysisToken

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

      if (files.length > 0) {
        setStepIndex(PROVISION_STEPS.length - 1)
        try {
          const fd = new FormData()
          files.forEach(f => fd.append('files', f))
          await fetch(`${API}/knowledge/upload/${provisioned.tenant_id}`, { method: 'POST', body: fd })
          trackEvent('knowledge_base_uploaded', { file_count: files.length, source: 'onboarding' })
        } catch {}
      }

      trackEvent('onboarding_completed', { tenant_id: provisioned.tenant_id, ...getFirstTouch() })
      trackEvent('activation_screen_viewed', { tenant_id: provisioned.tenant_id })
      setResult(provisioned)
      setStage('done')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
      setStage('review')
    }
  }

  const provisionTotal = files.length > 0 ? PROVISION_STEPS.length : PROVISION_STEPS.length - 1
  const provisionPct = stage === 'provisioning' ? ((stepIndex + 1) / provisionTotal) * 100 : 0
  const selectedDial = COUNTRIES.find(c => c.code === form.wa_country)?.dial ?? '+1'
  const selectedFlag = COUNTRIES.find(c => c.code === form.wa_country)?.flag ?? '🌐'
  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)

  const cardWide = stage === 'customize' || stage === 'review'

  return (
    <div className="ob-page" id="onboarding">
      <motion.div
        className="ob-card"
        initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
        style={{ maxWidth: cardWide ? 540 : 480 }}
      >
        <div className="ob-logo">
          <LogoMark />
          <span style={{ fontSize: 14, fontWeight: 400, letterSpacing: '0.04em', color: 'var(--text)' }}>open lines</span>
        </div>

        <AnimatePresence mode="wait">

          {/* ───────── STAGE: URL ───────── */}
          {stage === 'url' && (
            <motion.div key="url" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
                Create your AI receptionist
              </div>
              <div className="ob-sub">
                Enter your website and we&rsquo;ll build your AI receptionist automatically — in seconds.
              </div>

              <div className="form-group">
                <label className="form-label">Business Website URL *</label>
                <input className="form-input" name="website_url" value={form.website_url}
                  onChange={handleChange} placeholder="https://yourbusiness.com" type="url"
                  autoFocus />
                <div style={{
                  marginTop: 12, padding: '12px 14px', borderRadius: 10,
                  background: 'var(--surface-2, rgba(127,127,127,0.06))', border: '1px solid var(--border)',
                }}>
                  <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 8, fontWeight: 600 }}>We&rsquo;ll automatically:</div>
                  {['Learn your services', 'Extract FAQs', 'Build your AI knowledge base', 'Configure your AI receptionist'].map(t => (
                    <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-2, var(--text))', marginBottom: 4 }}>
                      <span style={{ color: '#22c55e', display: 'inline-flex' }}><Check /></span>{t}
                    </div>
                  ))}
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Business Email *</label>
                <input className="form-input" name="email" type="email" value={form.email}
                  onChange={handleChange} placeholder="you@business.com" required />
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                  Used for your account and call notifications.
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">
                  Business Name{' '}
                  <span style={{ color: 'var(--text-3)', fontWeight: 300, textTransform: 'none', letterSpacing: 0 }}>
                    (optional — we&rsquo;ll detect it)
                  </span>
                </label>
                <input className="form-input" name="business_name" value={form.business_name}
                  onChange={handleChange} placeholder="Auto-detected from your website" />
              </div>

              <button
                type="button"
                className="btn-submit"
                disabled={!form.website_url || !emailValid}
                onClick={() => {
                  trackEvent('onboarding_step_completed', { step_number: 1, step_name: 'website_url' })
                  runAnalysis()
                }}
              >
                Analyze my website →
              </button>
              <div style={{ textAlign: 'center', marginTop: 12 }}>
                <button type="button" onClick={() => { if (emailValid) skipWebsite() }}
                  disabled={!emailValid}
                  style={{
                    background: 'none', border: 'none', cursor: emailValid ? 'pointer' : 'not-allowed',
                    color: 'var(--text-3)', fontSize: 12, textDecoration: 'underline',
                  }}>
                  I don&rsquo;t have a website — set up manually
                </button>
              </div>
            </motion.div>
          )}

          {/* ───────── STAGE: ANALYZING ───────── */}
          {stage === 'analyzing' && (
            <motion.div key="analyzing" className="progress-wrap"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div style={{ fontSize: 28, marginBottom: 16 }}>
                <motion.span animate={{ rotate: 360 }}
                  transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}
                  style={{ display: 'inline-block' }}>⚙</motion.span>
              </div>
              <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 20, marginBottom: 20 }}>
                Training your AI receptionist…
              </div>
              <div style={{ textAlign: 'left', maxWidth: 280, margin: '0 auto' }}>
                {ANALYZE_STAGES.map((s, i) => {
                  const done = i <= analyzeIndex
                  return (
                    <div key={s} style={{
                      display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0',
                      opacity: done ? 1 : 0.35, transition: 'opacity 0.3s', fontSize: 14,
                    }}>
                      <span style={{
                        width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        background: done ? '#22c55e' : 'var(--border)', color: '#fff',
                      }}>
                        {done ? <Check /> : ''}
                      </span>
                      {s}
                    </div>
                  )
                })}
              </div>
            </motion.div>
          )}

          {/* ───────── STAGE: CUSTOMIZE ───────── */}
          {stage === 'customize' && (
            <motion.div key="customize" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
                Train your AI receptionist
              </div>
              <div className="ob-sub">
                {detected?.scrape_ok
                  ? `We analysed your website${detected.business_name ? ` and recognised ${detected.business_name}` : ''}. Review and fine-tune below.`
                  : 'Tell us a little about your business so your AI is set up correctly.'}
              </div>

              {detected?.scrape_ok && detected.services.length > 0 && (
                <div style={{
                  margin: '0 0 18px', padding: '12px 14px', borderRadius: 10,
                  background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.25)',
                }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2, var(--text))', marginBottom: 8 }}>
                    Detected services
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {detected.services.map(s => (
                      <span key={s} style={{
                        fontSize: 12, padding: '4px 10px', borderRadius: 999,
                        background: 'var(--surface-2, rgba(127,127,127,0.08))', border: '1px solid var(--border)',
                      }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}

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
                {detected?.scrape_ok && detected.industry_confidence > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                    Auto-detected — change if it&rsquo;s not quite right.
                  </div>
                )}
              </div>

              {form.industry === 'custom' && (
                <div className="form-group">
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                    <label className="form-label">Describe Your Business *</label>
                    <MicButton size={30} onResult={t => appendField('business_description', t)} />
                  </div>
                  <textarea className="form-input" name="business_description" value={form.business_description}
                    onChange={handleChange} rows={3}
                    placeholder="e.g. We are a family-run pet grooming salon offering baths, haircuts, and nail trims."
                    style={{ resize: 'vertical', lineHeight: 1.6 }} required />
                </div>
              )}

              <div className="form-group">
                <label className="form-label">Country *</label>
                <select className="form-input" name="country" value={form.country} onChange={handleChange}>
                  {COUNTRIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.name}</option>)}
                </select>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                  A local phone number will be provisioned in this country.
                </div>
              </div>

              {/* Agent name chips */}
              <div className="form-group">
                <label className="form-label">AI Receptionist Name</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {AGENT_NAMES.map(n => {
                    const active = !customAgent && form.agent_name === n
                    return (
                      <button type="button" key={n}
                        onClick={() => { setCustomAgent(false); setForm(f => ({ ...f, agent_name: n })) }}
                        style={{
                          padding: '8px 16px', borderRadius: 999, fontSize: 13, cursor: 'pointer',
                          border: `1px solid ${active ? 'var(--text)' : 'var(--border)'}`,
                          background: active ? 'var(--text)' : 'transparent',
                          color: active ? 'var(--bg, #fff)' : 'var(--text)',
                          fontWeight: active ? 600 : 400, transition: 'all 0.15s',
                        }}>{n}</button>
                    )
                  })}
                  <button type="button"
                    onClick={() => { setCustomAgent(true); setForm(f => ({ ...f, agent_name: '' })) }}
                    style={{
                      padding: '8px 16px', borderRadius: 999, fontSize: 13, cursor: 'pointer',
                      border: `1px solid ${customAgent ? 'var(--text)' : 'var(--border)'}`,
                      background: customAgent ? 'var(--text)' : 'transparent',
                      color: customAgent ? 'var(--bg, #fff)' : 'var(--text)',
                      fontWeight: customAgent ? 600 : 400, transition: 'all 0.15s',
                    }}>Custom</button>
                </div>
                {customAgent && (
                  <input className="form-input" name="agent_name" value={form.agent_name}
                    onChange={handleChange} placeholder="Enter a name" style={{ marginTop: 10 }} autoFocus />
                )}
              </div>

              {/* Documents */}
              <div className="form-group">
                <label className="form-label">
                  Documents{' '}
                  <span style={{ color: 'var(--text-3)', fontWeight: 300, textTransform: 'none', letterSpacing: 0 }}>
                    (optional — up to 10 files, 10 MB each)
                  </span>
                </label>
                <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 8 }}>
                  {DOC_HINT[form.industry] || DOC_HINT.custom}
                </div>
                <div
                  className={`upload-zone${dragOver ? ' drag-over' : ''}`}
                  onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <div className="upload-zone-icon">📎</div>
                  <div className="upload-zone-text">Drop files here or click to browse</div>
                  <div className="upload-zone-hint">PDF · Word · Excel · Plain text</div>
                </div>
                <input ref={fileInputRef} type="file" multiple
                  accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.csv"
                  style={{ display: 'none' }} onChange={e => addFiles(e.target.files)} />
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

              {/* Instructions (prefilled) */}
              <div className="form-group">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                  <label className="form-label">
                    AI Instructions{' '}
                    <span style={{ color: 'var(--text-3)', fontWeight: 300, textTransform: 'none', letterSpacing: 0 }}>
                      {detected?.suggested_instructions ? '(suggested — edit freely)' : '(optional)'}
                    </span>
                  </label>
                  <MicButton size={30} onResult={t => appendField('extra_instructions', t)} />
                </div>
                <textarea className="form-input" name="extra_instructions" value={form.extra_instructions}
                  onChange={handleChange} rows={4}
                  placeholder={'e.g. Always collect caller name and phone number.\nOffer appointment booking whenever appropriate.'}
                  style={{ resize: 'vertical', lineHeight: 1.6 }} />
              </div>

              {/* WhatsApp */}
              <div className="form-group">
                <label className="form-label">
                  WhatsApp Notifications{' '}
                  <span style={{ color: 'var(--text-3)', fontWeight: 300, textTransform: 'none', letterSpacing: 0 }}>
                    (optional)
                  </span>
                </label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <select name="wa_country" value={form.wa_country} onChange={handleChange}
                    className="form-input" style={{ width: 110, flexShrink: 0, paddingRight: 6 }}>
                    {COUNTRIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.dial}</option>)}
                  </select>
                  <input className="form-input" name="wa_local" value={form.wa_local}
                    onChange={handleChange} placeholder="416 555 0100" inputMode="tel" style={{ flex: 1 }} />
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                  Receive call summaries, lead alerts and booking updates here. Customers never see this number.
                </div>
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
                <button type="button" className="btn-ghost" onClick={() => setStage('url')}
                  style={{ flex: '0 0 auto', padding: '13px 20px' }}>← Back</button>
                <button type="button" className="btn-submit" style={{ flex: 1, margin: 0 }}
                  disabled={!form.business_name || (form.industry === 'custom' && !form.business_description.trim())}
                  onClick={() => {
                    trackEvent('onboarding_step_completed', { step_number: 2, step_name: 'customize', industry: form.industry })
                    setStage('review')
                  }}>
                  Continue →
                </button>
              </div>
            </motion.div>
          )}

          {/* ───────── STAGE: REVIEW ───────── */}
          {stage === 'review' && (
            <motion.div key="review" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="ob-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
                Review &amp; launch
              </div>
              <div className="ob-sub">One last look, then we&rsquo;ll create your AI receptionist and phone number.</div>

              <div style={{
                borderRadius: 12, border: '1px solid var(--border)', overflow: 'hidden', marginBottom: 18,
              }}>
                {[
                  ['Business', form.business_name],
                  ['Industry', INDUSTRY_LABEL[form.industry] || form.industry],
                  ['Website', form.website_url || '—'],
                  ['AI receptionist', form.agent_name || 'Alex'],
                  ['Notifications', form.wa_local ? `${selectedFlag} ${selectedDial}${form.wa_local.replace(/\D/g, '')}` : 'Not set'],
                  ['Detected services', detected?.services?.length ? `${detected.services.length} found` : '—'],
                  ['Knowledge base', (detected?.knowledge_chars || files.length) ? 'Ready' : 'Will use defaults'],
                ].map(([k, v], idx, arr) => (
                  <div key={k} style={{
                    display: 'flex', justifyContent: 'space-between', gap: 12, padding: '11px 14px',
                    borderBottom: idx < arr.length - 1 ? '1px solid var(--border)' : 'none', fontSize: 13,
                  }}>
                    <span style={{ color: 'var(--text-3)' }}>{k}</span>
                    <span style={{ fontWeight: 500, textAlign: 'right', wordBreak: 'break-word' }}>{v}</span>
                  </div>
                ))}
              </div>

              <form onSubmit={handleProvision}>
                <div className="form-group">
                  <label className="form-label">Create a Password *</label>
                  <input className="form-input" name="password" type="password" value={form.password}
                    onChange={handleChange} placeholder="Min. 8 characters" required minLength={8} autoFocus />
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>
                    Secures your dashboard at {form.email || 'your email'}.
                  </div>
                </div>

                {/* Trust row */}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', margin: '4px 0 16px' }}>
                  {['Setup in under 60 seconds', 'No coding required', 'Business number included', 'Cancel anytime'].map(t => (
                    <span key={t} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: 'var(--text-3)' }}>
                      <span style={{ color: '#22c55e', display: 'inline-flex' }}><Check /></span>{t}
                    </span>
                  ))}
                </div>

                <div style={{ display: 'flex', gap: 10 }}>
                  <button type="button" className="btn-ghost" onClick={() => setStage('customize')}
                    style={{ flex: '0 0 auto', padding: '13px 20px' }}>← Back</button>
                  <button type="submit" className="btn-submit" style={{ flex: 1, margin: 0 }}
                    disabled={form.password.length < 8}>
                    Create My AI Receptionist →
                  </button>
                </div>
                {error && <div className="error-msg">{error}</div>}
              </form>
            </motion.div>
          )}

          {/* ───────── STAGE: PROVISIONING ───────── */}
          {stage === 'provisioning' && (
            <motion.div key="provisioning" className="progress-wrap"
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
                    {PROVISION_STEPS[stepIndex]}
                  </motion.span>
                </AnimatePresence>
              </div>
              <div className="progress-track">
                <motion.div className="progress-bar" style={{ width: `${provisionPct}%` }} />
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 14 }}>
                This takes about 60 seconds — hang tight.
              </div>
            </motion.div>
          )}

          {/* ───────── STAGE: DONE / ACTIVATION ───────── */}
          {stage === 'done' && result && (
            <motion.div key="done" className="success-wrap"
              initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.4 }}>
              <div style={{ fontSize: 36, marginBottom: 8 }}>🎉</div>
              <div className="success-msg" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
                Your AI receptionist is ready
              </div>

              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, margin: '18px 0 8px', textAlign: 'left',
              }}>
                <div style={{ padding: '12px 14px', borderRadius: 10, border: '1px solid var(--border)', gridColumn: '1 / -1' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 2 }}>Your business number</div>
                  <div className="success-number" style={{ margin: 0 }}>{result.phone_number}</div>
                </div>
                <div style={{ padding: '12px 14px', borderRadius: 10, border: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 2 }}>AI receptionist</div>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>{form.agent_name || 'Alex'}</div>
                </div>
                <div style={{ padding: '12px 14px', borderRadius: 10, border: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 2 }}>Knowledge base</div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: '#22c55e' }}>Ready</div>
                </div>
              </div>

              <div style={{ margin: '10px 0 4px', fontSize: 13, color: 'var(--text-2, var(--text))', fontWeight: 600 }}>
                Try it now — call your AI:
              </div>

              <a href={`tel:${result.phone_number}`}
                onClick={() => trackEvent('first_test_call_started', { method: 'tel', tenant_id: result.tenant_id })}
                style={{ textDecoration: 'none', display: 'block' }}>
                <button className="btn-submit" style={{ width: '100%', margin: '6px 0' }}>
                  📞 Call My AI Now
                </button>
              </a>

              {sampleAvailable && (
                <div style={{ margin: '12px 0' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 6 }}>
                    Or hear a sample conversation:
                  </div>
                  {/* Drop a file at frontend/public/sample-call.mp3 to enable this player */}
                  <audio controls preload="none" style={{ width: '100%', height: 36 }}
                    onPlay={() => trackEvent('first_test_call_started', { method: 'sample', tenant_id: result.tenant_id })}
                    onError={() => setSampleAvailable(false)}>
                    <source src="/sample-call.mp3" type="audio/mpeg" />
                  </audio>
                </div>
              )}

              <Link href={`/dashboard/${result.tenant_id}`}>
                <button className="btn-dashboard" style={{ marginTop: 8 }}>View your dashboard →</button>
              </Link>
            </motion.div>
          )}

        </AnimatePresence>
      </motion.div>
    </div>
  )
}
