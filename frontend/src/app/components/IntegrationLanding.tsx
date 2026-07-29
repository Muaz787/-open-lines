import Link from 'next/link'
import SiteNav from './SiteNav'
import SiteFooter from './SiteFooter'
import PageCta from './PageCta'
import { FaqJsonLd, BreadcrumbJsonLd } from './JsonLd'
import type { IntegrationContent } from '../integrations/integrations-data'

const cardBox: React.CSSProperties = {
  background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '22px 22px',
}
const gridAuto = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 } as const

export default function IntegrationLanding({ content: c }: { content: IntegrationContent }) {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)', overflowX: 'hidden' }}>
      <SiteNav />

      <FaqJsonLd faqs={c.faqs} />
      <BreadcrumbJsonLd
        trail={[
          { name: 'Home', path: '/' },
          { name: 'Integrations', path: '/integrations' },
          { name: c.name, path: `/integrations/${c.slug}` },
        ]}
      />

      {/* ── Hero ── */}
      <section className="sec" style={{ paddingBottom: 64 }}>
        <div className="wrap" style={{ maxWidth: 820 }}>
          <div className="sec-label">{c.eyebrow}</div>
          <h1 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(30px, 4.6vw, 48px)', fontWeight: 700, letterSpacing: '-0.025em', lineHeight: 1.1, marginBottom: 18 }}>
            <span style={{ fontSize: '0.9em', marginRight: 10 }}>{c.emoji}</span>{c.h1}
          </h1>
          <p style={{ fontSize: 17, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300, marginBottom: 30, maxWidth: 640 }}>
            {c.subhead}
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
            <Link href="/onboarding"><button className="btn-trial">Start 7-Day Free Trial →</button></Link>
            <Link href="/integrations" style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-2)' }}>← All integrations</Link>
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-3)', marginTop: 16 }}>No credit card required. Live in under 10 minutes.</p>
        </div>
      </section>

      <div className="div-line" />

      {/* ── What it does ── */}
      <section className="sec">
        <div className="wrap" style={{ maxWidth: 760 }}>
          <div className="sec-label">How it works</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 14 }}>{c.whatHeading}</h2>
          <p style={{ fontSize: 16, color: 'var(--text-2)', lineHeight: 1.75, fontWeight: 300, marginBottom: 32 }}>{c.what}</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {c.steps.map((s, i) => (
              <div key={s.title} style={{ ...cardBox, display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                <div style={{ flexShrink: 0, width: 32, height: 32, borderRadius: '50%', background: 'var(--accent-dim)', color: 'var(--accent-text)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 14 }}>{i + 1}</div>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>{s.title}</div>
                  <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{s.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="div-line" />

      {/* ── Benefits ── */}
      <section className="sec">
        <div className="wrap">
          <div className="sec-label">Why it helps</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 28 }}>Built to save you the busywork.</h2>
          <div style={gridAuto}>
            {c.benefits.map(b => (
              <div key={b.title} style={cardBox}>
                <div style={{ fontSize: 24, marginBottom: 10 }}>{b.icon}</div>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{b.title}</div>
                <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{b.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="div-line" />

      {/* ── FAQ ── */}
      <section className="sec">
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

      <PageCta heading={c.ctaHeading} sub={c.ctaSub} location={`integration_${c.slug}_footer`} />
      <SiteFooter />
    </div>
  )
}
