import Link from 'next/link'
import type { Metadata } from 'next'
import PricingCards from './PricingCards'
import BookDemoButton from './BookDemoButton'
import SiteNav from '../components/SiteNav'
import SiteFooter from '../components/SiteFooter'

export const metadata: Metadata = {
  title: 'Pricing — Open Lines AI',
  description: 'Simple, transparent pricing for AI phone handling. From $99/month — no setup fees, no contracts.',
}


const ALL_INCLUDED = [
  { icon: '📞', label: 'Answers every call, 24/7', sub: 'No voicemail, no missed leads' },
  { icon: '🧠', label: 'Trained on your business', sub: 'Website, files, and custom FAQs' },
  { icon: '👤', label: 'Recognises returning callers', sub: 'Greets by name and recalls history' },
  { icon: '📋', label: 'Qualifies every lead', sub: 'Custom questions for your industry' },
  { icon: '📧', label: 'Email summary after each call', sub: 'Name, intent, urgency & next step' },
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
      <SiteNav />

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
      <PricingCards />

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
            <BookDemoButton />
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 20 }}>
            No credit card required to explore.
          </p>
        </div>
      </div>

      {/* ── Footer ── */}
      <SiteFooter />

    </div>
  )
}
