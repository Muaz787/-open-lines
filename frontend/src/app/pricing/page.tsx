import Link from 'next/link'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Pricing — Open Lines AI',
  description: 'Simple, transparent pricing for AI phone handling. From $99/month — no setup fees, no contracts.',
}

const LogoMark = () => (
  <svg width="24" height="24" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

const Check = () => (
  <svg width="15" height="15" viewBox="0 0 15 15" fill="none" style={{ flexShrink: 0, marginTop: 1 }}>
    <circle cx="7.5" cy="7.5" r="7.5" fill="var(--accent-dim)"/>
    <path d="M4.5 7.5L6.5 9.5L10.5 5.5" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const PLANS = [
  {
    name: 'Starter',
    price: 99,
    minutes: 150,
    overage: '0.35',
    popular: false,
    accent: 'var(--border-2)',
    features: [
      '150 minutes / month',
      '1 dedicated AI phone line',
      '24/7 call answering',
      'Lead capture & qualification',
      'Call transcripts & summaries',
      'WhatsApp & SMS notifications',
      'Caller recognition',
      'Dashboard & analytics',
    ],
    cta: 'Get started',
    ctaHref: '/onboarding',
    note: '$0.35 / min overage',
  },
  {
    name: 'Pro',
    price: 199,
    minutes: 400,
    overage: '0.35',
    popular: true,
    accent: 'var(--accent)',
    features: [
      '400 minutes / month',
      '1 dedicated AI phone line',
      'Everything in Starter',
      'Live calendar booking',
      'Google Calendar integration',
      'AI call insights',
      'Knowledge base management',
      'Appointment SMS confirmations',
    ],
    cta: 'Get started',
    ctaHref: '/onboarding',
    note: '$0.35 / min overage',
  },
  {
    name: 'Business',
    price: 379,
    minutes: 900,
    overage: '0.35',
    popular: false,
    accent: '#3B7EF6',
    features: [
      '900 minutes / month',
      '1 dedicated AI phone line',
      'Everything in Pro',
      'Custom AI personality & name',
      'Priority support',
      'Early access to new features',
    ],
    cta: 'Get started',
    ctaHref: '/onboarding',
    note: '$0.35 / min overage',
  },
]

const ALL_INCLUDED = [
  { icon: '📞', label: 'Answers every call, 24/7', sub: 'No voicemail, no missed leads' },
  { icon: '🧠', label: 'Trained on your business', sub: 'Website, files, and custom FAQs' },
  { icon: '👤', label: 'Recognises returning callers', sub: 'Greets by name and recalls history' },
  { icon: '📋', label: 'Qualifies every lead', sub: 'Custom questions for your industry' },
  { icon: '💬', label: 'WhatsApp summary after each call', sub: 'Sent instantly to your phone' },
  { icon: '🔒', label: 'Your own Twilio number', sub: 'Dedicated line, never shared' },
]

const FAQS = [
  {
    q: 'Is there a setup fee or contract?',
    a: 'No setup fee, no long-term contract. All plans are month-to-month. Cancel any time from your dashboard.',
  },
  {
    q: 'What counts as a "minute"?',
    a: 'One minute = one minute of live call time. Time waiting for the caller to connect, or after the call ends, does not count. Minutes reset on your billing date each month.',
  },
  {
    q: 'What happens if I go over my included minutes?',
    a: 'Calls keep going — we never cut off a live conversation. Overage minutes are billed at your plan\'s per-minute rate and appear on your next invoice.',
  },
  {
    q: 'Can the AI really book appointments?',
    a: 'Yes. Connect your Google Calendar in one click and the AI will check real-time availability, offer slots, and confirm bookings live during the call — no follow-up needed.',
  },
  {
    q: 'What industries does Open Lines support?',
    a: 'Realtors, medical and dental clinics, law firms, plumbers, builders, restaurants, beauty salons, and any custom business type. Each gets an industry-specific AI trained on your workflow.',
  },
  {
    q: 'Can I try it before paying?',
    a: 'Book a demo and we\'ll walk you through a live call on your industry. We\'re also adding a free-trial option — join the waitlist and you\'ll be first to know.',
  },
]

export default function PricingPage() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>

      {/* ── Nav ── */}
      <nav>
        <Link href="/" className="nav-logo">
          <LogoMark />
          <span className="logo-name">Open Lines</span>
        </Link>
        <div className="nav-right">
          <Link href="/onboarding">
            <button className="btn-nav">Get started</button>
          </Link>
        </div>
      </nav>

      {/* ── Hero ── */}
      <div className="pricing-hero">
        <div className="sec-label" style={{ marginBottom: 16 }}>Pricing</div>
        <h1 style={{
          fontSize: 'clamp(28px, 4vw, 48px)', fontWeight: 700,
          letterSpacing: '-0.03em', lineHeight: 1.05, marginBottom: 18,
          fontFamily: 'var(--font-syne), sans-serif',
        }}>
          Cheaper than a missed call.
        </h1>
        <p style={{ fontSize: 16, color: 'var(--text-2)', maxWidth: 460, margin: '0 auto 12px', lineHeight: 1.7, fontWeight: 300 }}>
          No setup fees. No contracts. Cancel any time.
        </p>
        <p style={{ fontSize: 13, color: 'var(--text-3)', fontStyle: 'italic' }}>
          A full-time human receptionist costs $2,800 – $4,000 / month.
        </p>
      </div>

      {/* ── Pricing cards ── */}
      <div className="pricing-cards-wrap">
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 20,
          alignItems: 'start',
        }}>
          {PLANS.map(plan => (
            <div
              key={plan.name}
              className={plan.popular ? 'plan-popular-card' : undefined}
              style={{
                background: 'var(--bg-2)',
                border: plan.popular ? `2px solid var(--accent)` : '1px solid var(--border-2)',
                borderRadius: 16,
                overflow: 'hidden',
                position: 'relative',
                transform: plan.popular ? 'translateY(-8px)' : 'none',
                boxShadow: plan.popular ? '0 20px 60px rgba(52,199,89,0.12)' : 'var(--shadow)',
              }}
            >
              {/* Top accent bar */}
              <div style={{ height: 3, background: plan.accent }} />

              {/* Popular badge */}
              {plan.popular && (
                <div style={{
                  position: 'absolute', top: 18, right: 18,
                  background: 'var(--accent)', color: 'var(--bg)',
                  fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
                  textTransform: 'uppercase', padding: '3px 10px', borderRadius: 20,
                }}>
                  Most Popular
                </div>
              )}

              <div style={{ padding: '28px 28px 32px' }}>
                {/* Plan name */}
                <div style={{
                  fontSize: 13, fontWeight: 700, letterSpacing: '0.06em',
                  textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 16,
                }}>
                  {plan.name}
                </div>

                {/* Price */}
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, marginBottom: 4 }}>
                  <span style={{
                    fontSize: 40, fontWeight: 800, letterSpacing: '-0.03em', lineHeight: 1,
                    color: 'var(--text)', fontFamily: 'var(--font-syne), sans-serif',
                  }}>
                    ${plan.price}
                  </span>
                  <span style={{ fontSize: 14, color: 'var(--text-3)', marginBottom: 8 }}>/mo</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 28 }}>
                  {plan.minutes} minutes included · {plan.note}
                </div>

                {/* CTA */}
                <Link href={plan.ctaHref} style={{ display: 'block', textDecoration: 'none' }}>
                  <button style={{
                    width: '100%', padding: '13px',
                    background: plan.popular ? 'var(--accent)' : 'var(--text)',
                    color: 'var(--bg)',
                    border: 'none', borderRadius: 9,
                    fontSize: 14, fontWeight: 600, cursor: 'pointer',
                    letterSpacing: '-0.01em',
                    transition: 'opacity 0.2s, transform 0.2s',
                  }}>
                    {plan.cta} →
                  </button>
                </Link>

                {/* Divider */}
                <div style={{ height: 1, background: 'var(--border)', margin: '28px 0' }} />

                {/* Features */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {plan.features.map(f => (
                    <div key={f} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                      <Check />
                      <span style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.4 }}>{f}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Overage note */}
        <p style={{ textAlign: 'center', fontSize: 12, color: 'var(--text-3)', marginTop: 28 }}>
          Overage minutes are billed at your plan rate. Calls are never cut off mid-conversation.
        </p>
      </div>

      {/* ── What's always included ── */}
      <div style={{ background: 'var(--bg-2)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}>
        <div className="pricing-inner">
          <div style={{ textAlign: 'center', marginBottom: 52 }}>
            <div className="sec-label" style={{ marginBottom: 14 }}>Every plan</div>
            <h2 style={{ margin: 0 }}>Everything you need, out of the box.</h2>
          </div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: 28,
          }}>
            {ALL_INCLUDED.map(item => (
              <div key={item.label} style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                <div style={{
                  width: 42, height: 42, borderRadius: 10,
                  background: 'var(--bg)', border: '1px solid var(--border)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 20, flexShrink: 0,
                }}>
                  {item.icon}
                </div>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 3 }}>
                    {item.label}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-3)', lineHeight: 1.5 }}>
                    {item.sub}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── FAQ ── */}
      <div className="pricing-faq-inner">
        <div style={{ textAlign: 'center', marginBottom: 52 }}>
          <div className="sec-label" style={{ marginBottom: 14 }}>FAQ</div>
          <h2 style={{ margin: 0 }}>Common questions.</h2>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {FAQS.map((faq, i) => (
            <div
              key={i}
              style={{
                padding: '24px 0',
                borderBottom: i < FAQS.length - 1 ? '1px solid var(--border)' : 'none',
              }}
            >
              <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)', marginBottom: 10 }}>
                {faq.q}
              </div>
              <div style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300 }}>
                {faq.a}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Bottom CTA ── */}
      <div style={{ background: 'var(--bg-2)', borderTop: '1px solid var(--border)' }}>
        <div className="pricing-cta-inner">
          <h2 style={{ marginBottom: 16 }}>Your line is waiting.</h2>
          <p style={{ fontSize: 16, color: 'var(--text-2)', marginBottom: 36, lineHeight: 1.7, fontWeight: 300 }}>
            Set up your AI receptionist in under 10 minutes. No engineers needed.
          </p>
          <div className="pricing-cta-btns">
            <Link href="/onboarding">
              <button className="btn-main">Start for free →</button>
            </Link>
            <Link href="/">
              <button className="btn-ghost">See how it works</button>
            </Link>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 20 }}>
            No credit card required to explore.
          </p>
        </div>
      </div>

      {/* ── Footer ── */}
      <footer>
        <div className="ft-left">
          <div className="nav-logo">
            <LogoMark />
            <span className="logo-name">Open Lines</span>
          </div>
          <div className="ft-tag">
            AI voice receptionist — answers every call, captures every lead, books every appointment.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
          <div className="ft-links">
            <Link href="/">Home</Link>
            <Link href="/pricing">Pricing</Link>
            <Link href="/privacy">Privacy</Link>
            <Link href="/terms">Terms</Link>
          </div>
          <div className="status-bar">
            <div className="st-dot" />
            All systems operational
          </div>
        </div>
      </footer>

    </div>
  )
}
