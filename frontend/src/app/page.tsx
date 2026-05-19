'use client'

import React, { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'

// ── Update this when you have your Calendly link ──
const DEMO_BOOKING_URL = 'https://calendly.com/open-lines/demo'

const TYPING_PHRASES = [
  'Realtors',
  'Property Managers',
  'Medical & Wellness',
  'Law Firms',
  'Plumbers',
  'Restaurants',
  'Builders',
  'Logistics',
  'Home Services',
  'Landscaping',
  'E-commerce & Retail',
  'Automotive',
]

function useTypewriter(phrases: string[], typeMs = 65, deleteMs = 38, pauseMs = 1800) {
  const [displayed, setDisplayed] = useState('')
  const [phraseIdx, setPhraseIdx] = useState(0)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    const phrase = phrases[phraseIdx]
    if (!deleting && displayed === phrase) {
      const t = setTimeout(() => setDeleting(true), pauseMs)
      return () => clearTimeout(t)
    }
    if (deleting && displayed === '') {
      setDeleting(false)
      setPhraseIdx(i => (i + 1) % phrases.length)
      return
    }
    const t = setTimeout(() => {
      setDisplayed(deleting
        ? phrase.slice(0, displayed.length - 1)
        : phrase.slice(0, displayed.length + 1))
    }, deleting ? deleteMs : typeMs)
    return () => clearTimeout(t)
  }, [displayed, deleting, phraseIdx, phrases, typeMs, deleteMs, pauseMs])

  return displayed
}

const PROBLEMS = [
  {
    icon: '📵',
    title: 'Missed calls, lost revenue.',
    body: "Most callers won't leave a voicemail — they'll call your competitor. The first business to pick up wins the client, and right now that's not you.",
  },
  {
    icon: '🌙',
    title: 'No coverage after hours.',
    body: "Your phone goes to voicemail after 5pm, on weekends, and during your busiest moments — exactly when new clients are trying to reach you.",
  },
  {
    icon: '📋',
    title: 'Leads that never convert.',
    body: "Your team spends hours returning calls only to find the prospect wasn't a fit, wanted the wrong service, or already booked elsewhere.",
  },
  {
    icon: '💸',
    title: "Overhead that doesn't scale.",
    body: "A full-time receptionist costs $2,800–$4,000 a month. Part-time staff means gaps. Neither adapts to call volume or grows with your business.",
  },
]

const INDUSTRIES = [
  { id: 're',     label: 'Realtors' },
  { id: 'dental', label: 'Dental' },
  { id: 'legal',  label: 'Legal' },
  { id: 'beauty', label: 'Beauty' },
]

const DEMO_SCRIPT = [
  { who: 'ai',  msg: "Hi, you've reached Shahid Real Estate. I'm Alex, your AI assistant — how can I help you today?" },
  { who: 'you', msg: "Hi, I'm calling about the property on 42 Harbour Boulevard." },
  { who: 'ai',  msg: "42 Harbour Blvd is a 4-bed, 2-bath home listed at $1.15M — pool and double garage included. Are you pre-approved for finance?" },
  { who: 'you', msg: "Yes, we're pre-approved up to $1.3 million." },
  { who: 'ai',  msg: "Perfect. I have Thursday at 2pm or Saturday at 10am available for a viewing. Which works better for you?" },
  { who: 'you', msg: "Saturday morning works great." },
  { who: 'ai',  msg: "Done — Saturday at 10am is booked. You'll get a text confirmation shortly. Is there anything else I can help you with?" },
]

const up = (delay: number) => ({
  initial: { opacity: 0, y: 18 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.8, ease: [0.4, 0, 0.2, 1] as [number, number, number, number], delay },
})

const hwaveAnim = (delay: number) => ({
  animate: { scaleY: [0.28, 1, 0.28], opacity: [0.35, 0.9, 0.35] },
  transition: { duration: 2.2, delay, repeat: Infinity, ease: 'easeInOut' as const },
})

const LogoMark = ({ size = 28 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', transition: 'color 0.5s', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
  </svg>
)

export default function Home() {
  const [isDark, setIsDark]           = useState(false)
  const [activeInd, setActiveInd]     = useState('re')
  const typedText                     = useTypewriter(TYPING_PHRASES)
  const [transcript, setTranscript]   = useState<{ who: string; msg: string }[]>([])
  const [callRunning, setCallRunning] = useState(false)
  const [callStatus, setCallStatus]   = useState<'ready' | 'live' | 'ended'>('ready')
  const transcriptRef  = useRef<HTMLDivElement>(null)
  const demoSectionRef = useRef<HTMLDivElement>(null)
  const autoPlayedRef  = useRef(false)
  const [activeProb, setActiveProb] = useState<number | null>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = isDark ? 'dark' : 'light'
  }, [isDark])

  // Auto-play demo when section scrolls into view (fires once)
  useEffect(() => {
    const el = demoSectionRef.current
    if (!el) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !autoPlayedRef.current) {
        autoPlayedRef.current = true
        observer.disconnect()
        // Small delay so the section has settled into view before starting
        setTimeout(() => runDemo(), 600)
      }
    }, { threshold: 0.3 })
    observer.observe(el)
    return () => observer.disconnect()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const runDemo = () => {
    if (callRunning) return
    setCallRunning(true)
    setTranscript([])
    setCallStatus('live')
    let delay = 500
    DEMO_SCRIPT.forEach((line, i) => {
      setTimeout(() => {
        setTranscript(prev => [...prev, line])
        requestAnimationFrame(() => {
          if (transcriptRef.current) transcriptRef.current.scrollTop = 9999
        })
        if (i === DEMO_SCRIPT.length - 1) {
          setTimeout(() => {
            setCallStatus('ended')
            setTimeout(() => { setCallStatus('ready'); setCallRunning(false) }, 3000)
          }, 600)
        }
      }, delay)
      delay += line.msg.length * 26 + 350
    })
  }

  const RealtorRows = [
    { init: 'JD', name: 'John Doe · +1 (555) 019‑2847',      desc: 'Asking about 42 Harbour Blvd. Budget $1.2M. Pre-approved.', tag: 'hot',  label: '🔥 Hot Lead' },
    { init: 'MR', name: 'Maria Rodriguez · +1 (555) 034‑1190', desc: 'First-time buyer. 3BR in Eastside. Budget $750K.',           tag: 'warm', label: 'Warm' },
    { init: 'TC', name: 'Thomas Clark · +1 (555) 088‑7312',   desc: 'Seller inquiry. 5BR property. Wants valuation call-back.',   tag: 'ok',   label: 'Seller' },
  ]
  const DentalRows = [
    { init: 'AL', name: 'Ahmed Lamine · New Patient',      desc: 'Toothache — requesting emergency appointment today.',           tag: 'urg',  label: 'Urgent' },
    { init: 'SF', name: 'Sophie Farley · Existing Patient', desc: 'Annual check-up booked for Thursday 10am. Confirmed.',         tag: 'sched', label: 'Booked' },
    { init: 'RK', name: 'Rachel Kim · Inquiry',             desc: 'Asking about whitening treatment cost and availability.',      tag: 'new',  label: 'New' },
  ]
  const LegalRows = [
    { init: 'NP', name: 'Nancy Patel · New Client',   desc: 'Real estate transaction — closing in 3 weeks. Referred to conveyancing team.', tag: 'new',  label: 'Referred' },
    { init: 'BT', name: 'Ben Turner · Existing Client', desc: 'Follow-up on family law matter. Case officer notified.',                      tag: 'pend', label: 'Pending' },
    { init: 'CW', name: 'Claire Wong · Inquiry',        desc: 'Employment dispute. Booked initial consultation for Friday 2pm.',             tag: 'sched', label: 'Booked' },
  ]
  const BeautyRows = [
    { init: 'LS', name: 'Laura S. · +1 (555) 091‑4422', desc: 'Haircut + colour on Saturday at 11am with Maya. Confirmed.',  tag: 'sched', label: 'Booked' },
    { init: 'DM', name: 'Diana M. · Inquiry',             desc: 'Asking about balayage pricing and next available appointment.', tag: 'new',  label: 'New' },
    { init: 'RO', name: 'Ryan O. · +1 (555) 063‑8810',  desc: 'Beard trim rescheduled from Tuesday to Thursday at 3pm.',      tag: 'warm', label: 'Rescheduled' },
  ]

  const IND_ROWS: Record<string, typeof RealtorRows> = { re: RealtorRows, dental: DentalRows, legal: LegalRows, beauty: BeautyRows }
  const IND_HEADS: Record<string, { title: string; live: string }> = {
    re:     { title: 'Active Lead Queue — Shahid Real Estate',      live: 'Live · 3 new today' },
    dental: { title: 'Patient Inquiry Queue — Smile Dental Group',  live: 'Live · 5 calls today' },
    legal:  { title: 'Client Intake — Hartwell & Associates LLP',   live: 'Live · 4 this afternoon' },
    beauty: { title: 'Booking Queue — Studio Nova Hair & Beauty',   live: 'Live · 8 bookings today' },
  }

  const [menuOpen, setMenuOpen] = useState(false)
  const closeMenu = () => setMenuOpen(false)

  return (
    <>
      {/* NAV */}
      <nav>
        <a href="#" className="nav-logo">
          <LogoMark />
          <span className="logo-name">open lines</span>
        </a>
        <div className="nav-mid">
          <a href="#demo">How it works</a>
          <a href="#industries">Industries</a>
          <a href="#platform">Platform</a>
          <Link href="/pricing">Pricing</Link>
        </div>
        <div className="nav-right">
          <div className="toggle" onClick={() => setIsDark(d => !d)}>
            <div className="toggle-knob" />
          </div>
          <Link href="/login">
            <button className="btn-nav" style={{ background: 'transparent', color: 'var(--text-2)', border: '1px solid var(--border-2)' }}>
              Sign in
            </button>
          </Link>
          <a href={DEMO_BOOKING_URL} target="_blank" rel="noopener noreferrer">
            <button className="btn-nav">Book a Demo</button>
          </a>
          {/* Hamburger — mobile only */}
          <button
            className="hamburger"
            onClick={() => setMenuOpen(o => !o)}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          >
            {menuOpen ? (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <line x1="4" y1="4" x2="16" y2="16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                <line x1="16" y1="4" x2="4" y2="16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <line x1="2" y1="5"  x2="18" y2="5"  stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                <line x1="2" y1="10" x2="18" y2="10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                <line x1="2" y1="15" x2="18" y2="15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
              </svg>
            )}
          </button>
        </div>
      </nav>

      {/* Mobile menu */}
      <AnimatePresence>
        {menuOpen && (
          <motion.div
            className="mobile-menu"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            <a href="#demo"       className="mobile-menu-link" onClick={closeMenu}>How it works</a>
            <a href="#industries" className="mobile-menu-link" onClick={closeMenu}>Industries</a>
            <a href="#platform"   className="mobile-menu-link" onClick={closeMenu}>Platform</a>
            <Link href="/pricing" className="mobile-menu-link" onClick={closeMenu}>Pricing</Link>
          </motion.div>
        )}
      </AnimatePresence>

      {/* HERO */}
      <section className="hero">
        <div className="hero-grid" />

        <motion.div className="hero-mark" {...up(0)}>
          <svg viewBox="0 0 100 100" fill="none" style={{ width: 110, height: 110, color: 'var(--text)', transition: 'color 0.5s' }}>
            <path d="M 56.8,11.6 A 39,39 0 0,1 56.8,88.4" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round"/>
            <path d="M 43.2,88.4 A 39,39 0 0,1 43.2,11.6" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round"/>
            <motion.line x1="37" y1="32" x2="37" y2="68"
              stroke="currentColor" strokeWidth="4" strokeLinecap="round"
              style={{ transformBox: 'fill-box' as 'fill-box', transformOrigin: 'center' }}
              {...hwaveAnim(0)} />
            <motion.line x1="50" y1="24" x2="50" y2="76"
              stroke="currentColor" strokeWidth="4" strokeLinecap="round"
              style={{ transformBox: 'fill-box' as 'fill-box', transformOrigin: 'center' }}
              {...hwaveAnim(0.22)} />
            <motion.line x1="63" y1="29" x2="63" y2="71"
              stroke="currentColor" strokeWidth="4" strokeLinecap="round"
              style={{ transformBox: 'fill-box' as 'fill-box', transformOrigin: 'center' }}
              {...hwaveAnim(0.44)} />
          </svg>
        </motion.div>

        <motion.h1 {...up(0.3)} style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
          Your AI Receptionist for
          <br />
          <span className="typewriter-phrase">
            {typedText}<span className="typewriter-cursor">|</span>
          </span>
        </motion.h1>
        <motion.p className="hero-sub" {...up(0.5)}>
          Answers calls, captures leads, books appointments. 24/7. No staff required.
        </motion.p>
        <motion.div className="hero-cta" {...up(0.7)}>
          <a href={DEMO_BOOKING_URL} target="_blank" rel="noopener noreferrer">
            <button className="btn-main">Book a Demo</button>
          </a>
          <Link href="/onboarding">
            <button className="btn-ghost">Build your own agent →</button>
          </Link>
        </motion.div>

        {/* Social proof line */}
        <motion.p {...up(0.9)} style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 22 }}>
          Setup in under 10 minutes · No contracts · Cancel any time
        </motion.p>
      </section>

      <div className="div-line" />

      {/* THE PROBLEM */}
      <section className="sec">
        <div className="wrap">
          <div className="sec-label" style={{ marginBottom: 14 }}>The problem</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 48 }}>
            Every missed call is a lost client.
          </h2>
          <div className="prob-grid">
            {PROBLEMS.map((p, i) => (
              <div
                key={i}
                className={`prob-card${activeProb === i ? ' active' : ''}`}
                onMouseEnter={() => setActiveProb(i)}
                onMouseLeave={() => setActiveProb(null)}
                onClick={() => setActiveProb(activeProb === i ? null : i)}
              >
                {/* Default face: icon + title footer */}
                <div className="prob-face">
                  <div className="prob-icon">{p.icon}</div>
                  <div className="prob-footer">
                    <span className="prob-title">{p.title}</span>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="prob-chevron">
                      <path d="M2 9L7 4L12 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </div>
                </div>

                {/* Hover back: full text */}
                <div className="prob-back">
                  <div className="prob-back-header">
                    <span className="prob-title">{p.title}</span>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="prob-chevron">
                      <path d="M2 5L7 10L12 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </div>
                  <p className="prob-desc">{p.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="div-line" />

      {/* LIVE DEMO */}
      <div className="demo-wrap" id="demo" ref={demoSectionRef}>
        <div className="sec wrap">
          <div className="demo-grid">
            <div>
              <div className="sec-label">Live Experience</div>
              <h2 style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Hear it.<br />See it happen.</h2>
              <p className="sec-sub">Watch a real conversation play out below — or call our live AI agent yourself to hear it firsthand.</p>
              <div style={{ marginTop: 28, display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[
                  'Answers calls instantly, 24/7',
                  'Qualifies leads while they\'re on the line',
                  'Books appointments directly into your calendar',
                  'Sends you a WhatsApp summary after every call',
                ].map(f => (
                  <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: 13, color: 'var(--text-2)' }}>
                    <span style={{ color: 'var(--accent)', fontWeight: 700, fontSize: 15 }}>✓</span>
                    {f}
                  </div>
                ))}
              </div>
            </div>

            <div className="phone-card">
              <div className="phone-head">
                <span className="phone-title">Open Lines — Demo Agent</span>
                <div className="call-status">
                  <div className={`cs-dot${callStatus === 'live' ? ' live' : ''}`} />
                  <span>{callStatus === 'live' ? 'Live' : callStatus === 'ended' ? 'Call ended' : 'Ready'}</span>
                </div>
              </div>

              <div className="transcript" ref={transcriptRef}>
                {transcript.length === 0 ? (
                  <div className="t-empty">
                    <span style={{ fontSize: 12, color: 'var(--text-3)' }}>Transcript appears here</span>
                  </div>
                ) : transcript.map((line, i) => (
                  <motion.div key={i} className="t-line"
                    initial={{ opacity: 0, y: 7 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.35, ease: [0.4, 0, 0.2, 1] as [number, number, number, number] }}>
                    <span className={`t-who ${line.who === 'ai' ? 'ai' : 'u'}`}>
                      {line.who === 'ai' ? 'AI' : 'You'}
                    </span>
                    <span className="t-msg">{line.msg}</span>
                  </motion.div>
                ))}
              </div>

              <button className="call-btn" onClick={runDemo} disabled={callRunning}>
                {callStatus === 'ended' ? (
                  <span style={{ color: 'var(--accent)' }}>✓ Appointment booked · Summary sent to WhatsApp</span>
                ) : (
                  <>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.58.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1C10.29 21 3 13.71 3 4.5c0-.55.45-1 1-1H7.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.23 1.01L6.6 10.8z"/>
                    </svg>
                    {callRunning ? '⠋ Live call in progress…' : 'Replay demo'}
                  </>
                )}
              </button>

              <div style={{ textAlign: 'center', marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
                <p style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 6 }}>Want to hear it live? Call our AI agent directly:</p>
                <a href="tel:+16475581427" style={{
                  fontSize: 15, fontWeight: 600, color: 'var(--text)',
                  letterSpacing: '0.02em', textDecoration: 'none',
                }}>
                  +1 (647) 558-1427
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="div-line" />

      {/* INDUSTRIES */}
      <section className="sec" id="industries">
        <div className="wrap">
          <div className="sec-label">8 Industries</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Built for businesses<br />that can't miss a call.</h2>
          <p className="sec-sub" style={{ marginBottom: 0 }}>
            One platform, pre-configured for your industry. Click to see it in action.
          </p>

          <div className="tab-row">
            {INDUSTRIES.map(ind => (
              <button key={ind.id} className={`tab${activeInd === ind.id ? ' on' : ''}`}
                onClick={() => setActiveInd(ind.id)}>
                {ind.label}
              </button>
            ))}
          </div>

          <div className="ind-panel">
            <AnimatePresence mode="wait">
              <motion.div key={activeInd}
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
                <div className="ind-head">
                  <span className="ind-title">{IND_HEADS[activeInd].title}</span>
                  <span className="live-pill"><span className="live-dot" />{IND_HEADS[activeInd].live}</span>
                </div>
                {IND_ROWS[activeInd].map(r => (
                  <div key={r.init} className="row">
                    <div className="av">{r.init}</div>
                    <div>
                      <div className="rn">{r.name}</div>
                      <div className="rd">{r.desc}</div>
                      <span className={`pill ${r.tag}`}>{r.label}</span>
                    </div>
                  </div>
                ))}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Other industries strip */}
          <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, color: 'var(--text-3)', paddingTop: 6 }}>Also available for:</span>
            {['Plumbers', 'Restaurants', 'Builders', 'Medical Clinics', 'Custom'].map(i => (
              <span key={i} style={{
                padding: '4px 12px', border: '1px solid var(--border-2)', borderRadius: 20,
                fontSize: 11, color: 'var(--text-3)',
              }}>{i}</span>
            ))}
          </div>
        </div>
      </section>

      <div className="div-line" />

      {/* PLATFORM */}
      <div className="dash-wrap" id="platform">
        <div className="sec wrap">
          <div className="sec-label">Platform</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Everything surfaces.<br />Nothing slips.</h2>
          <p className="sec-sub">Your AI handles the call. The intelligence lands in your pocket.</p>

          <div className="dash-grid">
            <div className="card">
              <div className="card-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="#34C759">
                  <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.890-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
                </svg>
              </div>
              <div className="card-lbl">Instant Alert</div>
              <div className="card-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>WhatsApp Summary</div>
              <div className="card-sub">Delivered within seconds of every call ending — name, intent, urgency, and suggested next step.</div>
              <div className="wp-box">
                <div className="wp-hd">
                  <div className="wp-av" />
                  <span className="wp-nm">Open Lines</span>
                  <span className="wp-ts">now</span>
                </div>
                <div className="wp-msg">
                  📞 <span className="hi">New Lead: John Doe</span><br />
                  Intent: <span className="hi">Buying · Urgency: High</span><br />
                  Property: 42 Harbour Blvd · Pre-approved ✓<br />
                  <span style={{ color: 'var(--text-3)' }}>→ Suggested: Call back within 2 hrs</span>
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#34C759" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/>
                  <line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
                </svg>
              </div>
              <div className="card-lbl">Calendar Booking</div>
              <div className="card-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Books While You Sleep</div>
              <div className="card-sub">Connects to Google Calendar and confirms appointments in real time — no follow-up needed.</div>
              <div className="stats">
                <div className="stat"><div className="stat-n">24/7</div><div className="stat-l">Always available</div></div>
                <div className="stat"><div className="stat-n">&lt;1s</div><div className="stat-l">Answer latency</div></div>
                <div className="stat"><div className="stat-n">0</div><div className="stat-l">Missed calls</div></div>
                <div className="stat"><div className="stat-n" style={{ color: 'var(--accent)', fontSize: 18 }}>●</div><div className="stat-l">Live right now</div></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="div-line" />

      {/* COMPARISON */}
      <div className="cmp-wrap">
        <div className="wrap cmp-grid">

          {/* Left: copy */}
          <div className="cmp-copy">
            <div className="sec-label" style={{ marginBottom: 16 }}>The math</div>
            <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 16 }}>
              Lower cost.<br />Better coverage.
            </h2>
            <p style={{ fontSize: 15, color: 'var(--text-2)', fontWeight: 300, lineHeight: 1.75, marginBottom: 10 }}>
              <strong style={{ color: 'var(--text)', fontWeight: 700 }}>Save up to $45,000 a year.</strong> That's the difference between a full-time receptionist and Open Lines — with better availability, zero turnover, and a line that never goes to voicemail.
            </p>
            <Link href="/pricing">
              <button className="btn-ghost" style={{ marginTop: 20, fontSize: 13 }}>See pricing →</button>
            </Link>
          </div>

          {/* Right: table */}
          <div className="cmp-table-wrap">
            <table className="cmp-table">
              <thead>
                <tr>
                  <th />
                  <th>
                    <div className="cmp-col-head">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
                      Human Receptionist
                    </div>
                  </th>
                  <th>
                    <div className="cmp-col-head cmp-col-ours">
                      <svg width="16" height="16" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M15.9,3.2 A11,11 0 0,1 15.9,24.8"/><path d="M12.1,24.8 A11,11 0 0,1 12.1,3.2"/><line x1="10.5" y1="12.5" x2="10.5" y2="16.5"/><line x1="14" y1="9.5" x2="14" y2="18.5"/><line x1="17.5" y1="11.5" x2="17.5" y2="17"/></svg>
                      Open Lines AI
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                {[
                  { label: 'Availability',    human: '9–5, Mon–Fri',   ours: '24/7, every day' },
                  { label: 'Starting cost',   human: '$2,800 / mo',    ours: 'From $99 / mo' },
                  { label: 'Annual cost',     human: '$33,600+',       ours: 'From $1,188 / yr' },
                  { label: 'Setup time',      human: 'Weeks',          ours: 'Under 10 min' },
                  { label: 'Turnover risk',   human: 'High',           ours: 'None' },
                  { label: 'Scales with calls', human: 'No',           ours: 'Yes' },
                ].map((row, i) => (
                  <tr key={i} className={i % 2 === 0 ? 'cmp-row-shaded' : ''}>
                    <td className="cmp-label">{row.label}</td>
                    <td className="cmp-human">{row.human}</td>
                    <td className="cmp-ours">{row.ours}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="div-line" />

      {/* HOW IT WORKS — Process steps */}
      <div className="process-wrap">
        <div className="wrap process-grid">

          {/* Left: copy */}
          <div className="process-copy">
            <div className="sec-label" style={{ marginBottom: 16 }}>How it works</div>
            <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 16 }}>
              Live in minutes.<br />Smarter every call.
            </h2>
            <p style={{ fontSize: 15, color: 'var(--text-2)', fontWeight: 300, lineHeight: 1.75, marginBottom: 28 }}>
              Getting started takes under 10 minutes. From there, your AI handles every call — and improves with every interaction.
            </p>
            <Link href="/onboarding">
              <button className="btn-main" style={{ fontSize: 14 }}>Get started →</button>
            </Link>
          </div>

          {/* Right: staggered cards */}
          <div className="process-cards">
            {[
              {
                n: '01',
                title: 'Sign up & connect',
                body: 'Enter your business details and website. Your AI agent is trained and your dedicated phone number goes live in under 10 minutes.',
              },
              {
                n: '02',
                title: 'Calls handled from day one',
                body: 'Your AI answers every call, qualifies leads, books appointments, and sends you a WhatsApp summary after each one.',
              },
              {
                n: '03',
                title: 'It gets smarter over time',
                body: 'Update your knowledge base anytime. The AI learns from every interaction and improves with your business.',
              },
            ].map((step, i) => (
              <motion.div
                key={i}
                className="process-card"
                style={{ '--step-offset': `${i * 28}px` } as React.CSSProperties}
                initial={{ opacity: 0, y: 22 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.3 }}
                transition={{ duration: 0.5, delay: i * 0.12, ease: [0.22, 1, 0.36, 1] }}
              >
                <div className="process-num">{step.n}</div>
                <div style={{ fontFamily: 'var(--font-syne), sans-serif', fontWeight: 700, fontSize: 15, marginBottom: 8, color: 'var(--text)' }}>
                  {step.title}
                </div>
                <div style={{ fontSize: 13, color: 'var(--text-2)', fontWeight: 300, lineHeight: 1.65 }}>
                  {step.body}
                </div>
              </motion.div>
            ))}
          </div>

        </div>
      </div>

      <div className="div-line" />

      {/* BOTTOM CTA */}
      <section className="sec" style={{ textAlign: 'center' }}>
        <div className="wrap">
          <div className="sec-label">Get Started</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', maxWidth: 560, margin: '0 auto 14px' }}>
            Your receptionist.<br />Never off the clock.
          </h2>
          <p style={{ fontSize: 15, color: 'var(--text-2)', fontWeight: 300, maxWidth: 400, margin: '0 auto 36px', lineHeight: 1.7 }}>
            Not sure which plan fits? We'll walk you through it live — or you can set up your agent right now in under 10 minutes.
          </p>
          <div className="cta-row" style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <a href={DEMO_BOOKING_URL} target="_blank" rel="noopener noreferrer">
              <button className="btn-main" style={{ padding: '14px 32px', fontSize: 15 }}>Book a Demo</button>
            </a>
            <Link href="/onboarding">
              <button className="btn-ghost" style={{ padding: '14px 32px', fontSize: 15 }}>Build your own agent →</button>
            </Link>
          </div>
          <p style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 18 }}>
            Setup in under 10 minutes · No contracts · Cancel any time
          </p>
        </div>
      </section>

      {/* FOOTER */}
      <footer>
        <div className="ft-left">
          <a href="#" className="nav-logo">
            <LogoMark size={20} />
            <span className="logo-name" style={{ fontSize: 13 }}>open lines</span>
          </a>
          <p className="ft-tag">&ldquo;Open Lines was built to close the gap between businesses and the people who need them.&rdquo;</p>
          <div className="ft-links">
            <Link href="/privacy">Privacy</Link>
            <Link href="/terms">Terms</Link>
          </div>
        </div>
        <div className="ft-right">
          <div className="ft-social">
            <a href="https://x.com/openlines_ai" target="_blank" rel="noopener noreferrer" aria-label="X / Twitter">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.737-8.849L2.1 2.25h6.988l4.254 5.622 4.902-5.622zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
            </a>
            <a href="https://www.youtube.com/@Openlines_ai" target="_blank" rel="noopener noreferrer" aria-label="YouTube">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
            </a>
            <a href="https://www.linkedin.com/company/open-lines1" target="_blank" rel="noopener noreferrer" aria-label="LinkedIn">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
            </a>
          </div>
          <div className="status-bar">
            <div className="st-dot" />
            System Status: Online
          </div>
        </div>
      </footer>
    </>
  )
}
