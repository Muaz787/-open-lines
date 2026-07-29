import Link from 'next/link'
import SiteNav from './SiteNav'
import SiteFooter from './SiteFooter'
import PageCta from './PageCta'
import { FaqJsonLd, BreadcrumbJsonLd } from './JsonLd'
import type { LearnArticle as Article } from '../learn/learn-data'

const SITE_URL = 'https://www.openlines.ai'

const cardBox: React.CSSProperties = {
  background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '20px 22px',
}

export default function LearnArticle({ content: c }: { content: Article }) {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)', overflowX: 'hidden' }}>
      <SiteNav />

      <FaqJsonLd faqs={c.faqs} />
      <BreadcrumbJsonLd
        trail={[
          { name: 'Home', path: '/' },
          { name: 'Learn', path: '/learn' },
          { name: c.shortTitle, path: `/learn/${c.slug}` },
        ]}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            '@context': 'https://schema.org',
            '@type': 'Article',
            headline: c.h1,
            description: c.metaDescription,
            author: { '@type': 'Organization', name: 'Open Lines' },
            publisher: { '@type': 'Organization', name: 'Open Lines Technologies Inc.' },
            mainEntityOfPage: `${SITE_URL}/learn/${c.slug}`,
          }),
        }}
      />

      <article className="legal-body">
        <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--accent-text)', marginBottom: 12 }}>
          {c.category} · Updated {c.updated}
        </div>
        <h1 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(28px, 4.4vw, 44px)', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1.12, marginBottom: 20 }}>
          {c.h1}
        </h1>
        <p style={{ fontSize: 18, color: 'var(--text-2)', lineHeight: 1.75, fontWeight: 300, marginBottom: 8 }}>{c.intro}</p>

        {c.sections.map(s => (
          <section key={s.heading} style={{ marginTop: 40 }}>
            <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(21px, 3vw, 28px)', fontWeight: 700, letterSpacing: '-0.015em', marginBottom: 14 }}>
              {s.heading}
            </h2>
            {s.paras?.map((p, i) => (
              <p key={i} style={{ fontSize: 16, color: 'var(--text-2)', lineHeight: 1.8, fontWeight: 300, marginBottom: 16 }}>{p}</p>
            ))}
            {s.bullets && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 6 }}>
                {s.bullets.map(b => (
                  <div key={b.title} style={cardBox}>
                    <div style={{ fontSize: 15.5, fontWeight: 600, marginBottom: 5 }}>{b.title}</div>
                    <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.65, margin: 0, fontWeight: 300 }}>{b.body}</p>
                  </div>
                ))}
              </div>
            )}
          </section>
        ))}

        {/* ── FAQ ── */}
        <section style={{ marginTop: 48 }}>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(21px, 3vw, 28px)', fontWeight: 700, letterSpacing: '-0.015em', marginBottom: 18 }}>
            Frequently asked
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {c.faqs.map(f => (
              <div key={f.q} style={cardBox}>
                <div style={{ fontSize: 15.5, fontWeight: 600, marginBottom: 6 }}>{f.q}</div>
                <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.65, margin: 0, fontWeight: 300 }}>{f.a}</p>
              </div>
            ))}
          </div>
        </section>

        <div style={{ marginTop: 44, display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          <Link href="/onboarding"><button className="btn-trial">Start 7-Day Free Trial →</button></Link>
          <Link href="/learn" style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-2)', alignSelf: 'center' }}>← More guides</Link>
        </div>
      </article>

      <PageCta heading={c.ctaHeading} sub={c.ctaSub} location={`learn_${c.slug}_footer`} />
      <SiteFooter />
    </div>
  )
}
