'use client'

import Link from 'next/link'
import SiteNav from './SiteNav'
import SiteFooter from './SiteFooter'
import { trackEvent, getUtmParams } from '@/lib/analytics'

/* ─────────────────────────────────────────────────────────────
   Content model — one plain, serializable object per vertical.
   The three page.tsx files pass one of these in.
   ───────────────────────────────────────────────────────────── */
export interface VerticalContent {
  slug: string
  eyebrow: string
  h1: string
  subhead: string
  trustline: string
  heroArt: 'call' | 'textback'
  painsLabel: string
  painsHeading: string
  pains: { stat: string; title: string; body: string }[]
  solutionLabel: string
  solutionHeading: string
  solutionSub: string
  features: { icon: string; title: string; body: string }[]
  demoMock: { name: string; service: string; when: string; with?: string }
  textback: { business: string; reply: string }
  integrationsHeading: string
  integrations: string[]
  faqs: { q: string; a: string }[]
  ctaHeading: string
  ctaSub: string
}

const TRIAL_HREF = '/onboarding'
const DEMO_HREF = 'https://calendly.com/open-lines/demo'

/* ── Reusable CTA cluster: the standout free-trial button + microcopy ── */
function TrialCta({ slug, location, secondary = true }: { slug: string; location: string; secondary?: boolean }) {
  return (
    <div>
      <div className="vl-cta-row">
        <Link
          href={TRIAL_HREF}
          onClick={() => trackEvent('get_started_clicked', { location, vertical: slug, ...getUtmParams() })}
        >
          <button className="btn-trial">Start 7-Day Free Trial →</button>
        </Link>
        {secondary && (
          <a
            href={DEMO_HREF}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackEvent('demo_cta_clicked', { location, vertical: slug, ...getUtmParams() })}
          >
            <button className="btn-ghost" style={{ padding: '15px 26px', fontSize: 15 }}>Book a 15-min demo</button>
          </a>
        )}
      </div>
      <p style={{ fontSize: 13, color: 'var(--text-3)', marginTop: 12 }}>
        No credit card required. Live in under 10 minutes.
      </p>
    </div>
  )
}

/* ── Illustration: an incoming call being answered live by the AI ── */
function CallMock() {
  return (
    <div style={mockCard}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)', display: 'inline-block' }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)' }}>Incoming call · answered in 1 ring</span>
        </div>
        <span style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'monospace' }}>00:14</span>
      </div>

      <Bubble who="Caller">Hi, are you taking new appointments this week?</Bubble>
      <Bubble who="Open Lines AI" ai>Absolutely — I can book you in. What day works, and is there someone you usually see?</Bubble>
      <Bubble who="Caller">Thursday afternoon if you have it.</Bubble>
      <Bubble who="Open Lines AI" ai>Thursday at 2:30 is open. I&apos;ll lock it in and text you a confirmation. 🎉</Bubble>

      <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', background: 'var(--accent-dim)', borderRadius: 10 }}>
        <span style={{ fontSize: 15 }}>✅</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent-text)' }}>Appointment booked &amp; synced to your calendar</span>
      </div>
    </div>
  )
}

/* ── Illustration: instant SMS text-back on a missed call ── */
function TextbackMock({ business, reply }: { business: string; reply: string }) {
  return (
    <div style={mockCard}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ fontSize: 15 }}>📱</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)' }}>Missed call → texted back in seconds</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={smsMissed}>Missed call · {business}</div>
        <div style={smsOut}>
          Hi, it&apos;s {business} — sorry we missed you! I&apos;m the assistant here and happy to help.
          What are you looking for, and what&apos;s the best time to reach you?
        </div>
        <div style={smsIn}>{reply}</div>
        <div style={smsOut}>Perfect — I&apos;ve got your details and the team is on it. You&apos;re all set. 👍</div>
      </div>
    </div>
  )
}

/* ── Illustration: a clean booking confirmation card ── */
function CalendarMock({ name, service, when, withWho }: { name: string; service: string; when: string; withWho?: string }) {
  const [day, ...rest] = when.split(' ')
  return (
    <div style={mockCard}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ fontSize: 15 }}>📅</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)' }}>Booking confirmed</span>
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
        <div style={{ flexShrink: 0, width: 64, height: 64, borderRadius: 12, background: 'var(--accent-dim)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent-text)', textTransform: 'uppercase' }}>{day}</span>
          <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--accent-text)', lineHeight: 1 }}>{rest[0] || ''}</span>
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)' }}>{service}</div>
          <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 2 }}>{rest.slice(1).join(' ')}{withWho ? ` · with ${withWho}` : ''}</div>
          <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 2 }}>{name}</div>
        </div>
      </div>
    </div>
  )
}

function Bubble({ who, ai, children }: { who: string; ai?: boolean; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: ai ? 'var(--accent-text)' : 'var(--text-3)', marginBottom: 3 }}>{who}</div>
      <div style={{ fontSize: 13.5, lineHeight: 1.55, color: 'var(--text)', fontWeight: 300, background: ai ? 'var(--accent-dim)' : 'var(--bg-3)', padding: '9px 13px', borderRadius: 12, display: 'inline-block', maxWidth: '92%' }}>{children}</div>
    </div>
  )
}

/* ── Shared inline styles ── */
const mockCard: React.CSSProperties = {
  background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 18,
  padding: '22px 22px', boxShadow: 'var(--shadow-lg)', maxWidth: 440, width: '100%',
}
const smsBase: React.CSSProperties = { fontSize: 13.5, lineHeight: 1.5, padding: '10px 14px', borderRadius: 14, maxWidth: '85%', fontWeight: 300 }
const smsMissed: React.CSSProperties = { ...smsBase, alignSelf: 'center', maxWidth: '100%', textAlign: 'center', fontSize: 11.5, color: 'var(--text-3)', background: 'transparent', fontWeight: 500 }
const smsOut: React.CSSProperties = { ...smsBase, alignSelf: 'flex-start', background: 'var(--bg-3)', color: 'var(--text)' }
const smsIn: React.CSSProperties = { ...smsBase, alignSelf: 'flex-end', background: 'var(--accent)', color: '#fff' }
const cardBox: React.CSSProperties = { background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '22px 22px' }
const gridAuto = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 } as const

/* ─────────────────────────────────────────────────────────────
   The page
   ───────────────────────────────────────────────────────────── */
export default function VerticalLanding({ content: c }: { content: VerticalContent }) {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>
      <SiteNav />

      {/* ── Hero ── */}
      <section className="sec" style={{ paddingBottom: 72 }}>
        <div className="wrap">
          <div className="vl-hero-grid">
            <div>
              <div className="sec-label">{c.eyebrow}</div>
              <h1 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(30px, 4.6vw, 50px)', fontWeight: 700, letterSpacing: '-0.025em', lineHeight: 1.08, marginBottom: 18 }}>
                {c.h1}
              </h1>
              <p style={{ fontSize: 17, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300, marginBottom: 30, maxWidth: 520 }}>
                {c.subhead}
              </p>
              <TrialCta slug={c.slug} location={`${c.slug}_hero`} />
              <p style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 22, fontWeight: 300 }}>{c.trustline}</p>
            </div>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              {c.heroArt === 'textback'
                ? <TextbackMock business={c.textback.business} reply={c.textback.reply} />
                : <CallMock />}
            </div>
          </div>
        </div>
      </section>

      <div className="div-line" />

      {/* ── Pain points ── */}
      <section className="sec">
        <div className="wrap">
          <div className="sec-label">{c.painsLabel}</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 28, maxWidth: 620 }}>{c.painsHeading}</h2>
          <div style={gridAuto}>
            {c.pains.map(p => (
              <div key={p.title} style={cardBox}>
                <div style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 26, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>{p.stat}</div>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{p.title}</div>
                <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{p.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="div-line" />

      {/* ── Solution / features ── */}
      <section className="sec">
        <div className="wrap">
          <div className="sec-label">{c.solutionLabel}</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 10 }}>{c.solutionHeading}</h2>
          <p className="sec-sub" style={{ maxWidth: 560, marginBottom: 30 }}>{c.solutionSub}</p>
          <div style={gridAuto}>
            {c.features.map(f => (
              <div key={f.title} style={cardBox}>
                <div style={{ fontSize: 24, marginBottom: 10 }}>{f.icon}</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{f.title}</div>
                <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── See it in action (proof band) ── */}
      <div style={{ background: 'var(--bg-2)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}>
        <section className="sec">
          <div className="wrap">
            <div className="sec-label" style={{ textAlign: 'center' }}>See it in action</div>
            <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', textAlign: 'center', marginBottom: 36 }}>Booked, confirmed, and texted back — automatically.</h2>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, justifyContent: 'center', alignItems: 'flex-start' }}>
              <CalendarMock name={c.demoMock.name} service={c.demoMock.service} when={c.demoMock.when} withWho={c.demoMock.with} />
              <TextbackMock business={c.textback.business} reply={c.textback.reply} />
            </div>
          </div>
        </section>
      </div>

      {/* ── Integrations ── */}
      <section className="sec">
        <div className="wrap" style={{ textAlign: 'center' }}>
          <div className="sec-label">Works with your stack</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 10 }}>{c.integrationsHeading}</h2>
          <p className="sec-sub" style={{ maxWidth: 520, margin: '0 auto 28px' }}>
            No rip-and-replace. Open Lines books into the calendar and tools you already run.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, justifyContent: 'center' }}>
            {c.integrations.map(name => (
              <span key={name} style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-2)', background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 999, padding: '9px 18px' }}>{name}</span>
            ))}
          </div>
        </div>
      </section>

      <div className="div-line" />

      {/* ── FAQ ── */}
      <section className="sec" style={{ paddingTop: 72 }}>
        <div className="wrap" style={{ maxWidth: 760 }}>
          <div className="sec-label">Questions</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 28 }}>Good to know.</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {c.faqs.map(f => (
              <div key={f.q} style={cardBox}>
                <div style={{ fontSize: 15.5, fontWeight: 600, marginBottom: 6 }}>{f.q}</div>
                <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.65, margin: 0, fontWeight: 300 }}>{f.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ── */}
      <div style={{ background: 'var(--bg-2)', borderTop: '1px solid var(--border)' }}>
        <div className="pricing-cta-inner" style={{ textAlign: 'center' }}>
          <h2 style={{ marginBottom: 16 }}>{c.ctaHeading}</h2>
          <p style={{ fontSize: 16, color: 'var(--text-2)', marginBottom: 32, lineHeight: 1.7, fontWeight: 300, maxWidth: 520, marginLeft: 'auto', marginRight: 'auto' }}>
            {c.ctaSub}
          </p>
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <TrialCta slug={c.slug} location={`${c.slug}_footer`} secondary={false} />
          </div>
        </div>
      </div>

      <SiteFooter />
    </div>
  )
}
