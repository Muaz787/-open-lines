'use client'

import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'

const INDUSTRIES = [
  { id: 're',  label: 'Realtors' },
  { id: 'med', label: 'Medical Clinics' },
  { id: 'mp',  label: 'Members of Parliament' },
]

const DEMO_SCRIPT = [
  { who: 'ai',  msg: "Hi, you've reached Sarah Chen Real Estate. I'm your AI assistant — how can I help you today?" },
  { who: 'you', msg: "Hi, I'm calling about the property on 42 Harbour Boulevard." },
  { who: 'ai',  msg: "42 Harbour Blvd is a 4-bed, 2-bath home listed at $1.15M — pool and double garage included. Are you pre-approved for finance?" },
  { who: 'you', msg: "Yes, we're pre-approved up to $1.3 million." },
  { who: 'ai',  msg: "Perfect. Sarah has availability Thursday at 2pm or Saturday at 10am. Which works better?" },
  { who: 'you', msg: "Saturday morning sounds great." },
  { who: 'ai',  msg: "Confirmed — Saturday at 10am. Sarah will receive a full summary of this call. Anything else I can help with?" },
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
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

export default function Home() {
  const [isDark, setIsDark]       = useState(false)
  const [activeInd, setActiveInd] = useState('re')
  const [transcript, setTranscript]   = useState<{ who: string; msg: string }[]>([])
  const [callRunning, setCallRunning] = useState(false)
  const [callStatus, setCallStatus]   = useState<'ready' | 'live' | 'ended'>('ready')
  const transcriptRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = isDark ? 'dark' : 'light'
  }, [isDark])

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
    { init: 'JD', name: 'John Doe · +1 (555) 019‑2847',     desc: 'Asking about 42 Harbour Blvd. Budget $1.2M. Pre-approved.', tag: 'hot',  label: '🔥 Hot Lead' },
    { init: 'MR', name: 'Maria Rodriguez · +1 (555) 034‑1190', desc: 'First-time buyer. 3BR in Eastside. Budget $750K.',          tag: 'warm', label: 'Warm' },
    { init: 'TC', name: 'Thomas Clark · +1 (555) 088‑7312',  desc: 'Seller inquiry. 5BR property. Wants valuation call-back.',   tag: 'ok',   label: 'Seller' },
  ]
  const ClinicRows = [
    { init: 'AL', name: 'Ahmed Lamine · New Patient',   desc: 'GP appointment request. Chest pain symptoms. Flagged for priority booking.', tag: 'urg',  label: 'Urgent' },
    { init: 'SF', name: 'Sophie Farley · Existing Patient', desc: 'Prescription renewal — recurring medication. Identity verified.',         tag: 'pend', label: 'Pending Approval' },
    { init: 'RK', name: 'Rachel Kim · Follow-up',       desc: 'Post-procedure check-in. All clear. 6-month review booked.',                  tag: 'res',  label: 'Resolved' },
  ]
  const ParliamentRows = [
    { init: 'NP', name: 'Nancy Patel · Constituent',   desc: 'Flooding on Elmwood St. Requesting urgent council escalation.', tag: 'urg',   label: 'Infrastructure' },
    { init: 'BT', name: 'Ben Turner · Constituent',     desc: 'Visa delay for family member. Referred to immigration case officer.', tag: 'new', label: 'Referred' },
    { init: 'CW', name: 'Claire Wong · School Principal', desc: 'Requesting meeting re: school funding. Confirmed Tuesday 10am.', tag: 'sched', label: 'Scheduled' },
  ]
  const IND_ROWS: Record<string, typeof RealtorRows> = { re: RealtorRows, med: ClinicRows, mp: ParliamentRows }
  const IND_HEADS: Record<string, { title: string; live: string }> = {
    re:  { title: 'Active Lead Queue — Sarah Chen Real Estate', live: 'Live · 3 new today' },
    med: { title: 'Patient Inquiry Queue — Northside Family Clinic', live: 'Live · 5 calls today' },
    mp:  { title: 'Constituent Casework — Office of Hon. James Whitfield MP', live: 'Live · 12 this week' },
  }

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
        </div>
        <div className="nav-right">
          <div className="toggle" onClick={() => setIsDark(d => !d)}>
            <div className="toggle-knob" />
          </div>
          <Link href="/onboarding">
            <button className="btn-nav">Get a Demo</button>
          </Link>
        </div>
      </nav>

      {/* HERO */}
      <section className="hero">
        <div className="hero-grid" />

        <motion.div {...up(0.1)} className="badge">
          <span className="badge-dot" />
          Now live — Realtors &amp; Public Offices
        </motion.div>

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
          the line is<br /><em>always open.</em>
        </motion.h1>
        <motion.p className="hero-sub" {...up(0.5)}>
          AI-powered phone handling for Realtors, Clinics, and Public Offices. Instant responses. Zero missed leads.
        </motion.p>
        <motion.div className="hero-cta" {...up(0.7)}>
          <Link href="/onboarding#onboarding">
            <button className="btn-main">Get a Demo Number</button>
          </Link>
          <a href="#demo"><button className="btn-ghost">See it live →</button></a>
        </motion.div>
      </section>

      <div className="div-line" />

      {/* LIVE DEMO */}
      <div className="demo-wrap" id="demo">
        <div className="sec wrap">
          <div className="demo-grid">
            <div>
              <div className="sec-label">Live Experience</div>
              <h2 style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Hear it.<br />See it happen.</h2>
              <p className="sec-sub">Simulate a call with our demo agent. Watch the real-time transcript — exactly what your clients experience.</p>
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
                  <span style={{ color: 'var(--accent)' }}>✓ Summary sent to WhatsApp</span>
                ) : (
                  <>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.58.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1C10.29 21 3 13.71 3 4.5c0-.55.45-1 1-1H7.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.23 1.01L6.6 10.8z"/>
                    </svg>
                    {callRunning ? '⠋ Connecting…' : 'Click to simulate a call'}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="div-line" />

      {/* INDUSTRIES */}
      <section className="sec" id="industries">
        <div className="wrap">
          <div className="sec-label">One Platform</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Built for every<br />high-stakes office.</h2>
          <p className="sec-sub" style={{ marginBottom: 0 }}>
            One agent. Infinite configurations. Click an industry to see it adapt.
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
              <div className="card-sub">Delivered within 8 seconds of every call ending.</div>
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
                  <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                </svg>
              </div>
              <div className="card-lbl">Knowledge Base</div>
              <div className="card-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>Live Data Sync</div>
              <div className="card-sub">Listings, policies, and FAQs — updated every 24 hours automatically.</div>
              <div className="stats">
                <div className="stat"><div className="stat-n">42</div><div className="stat-l">Listings synced</div></div>
                <div className="stat"><div className="stat-n">&lt;1s</div><div className="stat-l">Answer latency</div></div>
                <div className="stat"><div className="stat-n">99.9%</div><div className="stat-l">Uptime</div></div>
                <div className="stat">
                  <div className="stat-n" style={{ color: 'var(--accent)', fontSize: 18 }}>●</div>
                  <div className="stat-l">Last crawl: 2h ago</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* FOOTER */}
      <footer>
        <div className="ft-left">
          <a href="#" className="nav-logo">
            <LogoMark size={20} />
            <span className="logo-name" style={{ fontSize: 13 }}>open lines</span>
          </a>
          <p className="ft-tag">"Open Lines was built to close the gap between businesses and the people who need them."</p>
          <div className="ft-links">
            <a href="#">Privacy</a>
            <a href="#">Terms</a>
            <a href="#">Contact</a>
          </div>
        </div>
        <div className="status-bar">
          <div className="st-dot" />
          System Status: Online
        </div>
      </footer>
    </>
  )
}
