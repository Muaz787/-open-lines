import Link from 'next/link'
import SiteNav from './SiteNav'
import SiteFooter from './SiteFooter'
import PageCta from './PageCta'
import Breadcrumbs from './Breadcrumbs'
import RelatedLinks from './RelatedLinks'
import { FaqJsonLd, BreadcrumbJsonLd } from './JsonLd'
import type { LearnArticle as Article } from '../learn/learn-data'

const SITE_URL = 'https://www.openlines.ai'

const cardBox: React.CSSProperties = {
  background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '20px 22px',
}

const slugify = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
const fmtDate = (iso: string) => new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })

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
            datePublished: c.published,
            dateModified: c.updated,
            author: { '@type': 'Organization', name: 'Open Lines', url: SITE_URL },
            publisher: {
              '@type': 'Organization',
              name: 'Open Lines Technologies Inc.',
              url: SITE_URL,
              logo: { '@type': 'ImageObject', url: `${SITE_URL}/apple-icon.png` },
            },
            mainEntityOfPage: `${SITE_URL}/learn/${c.slug}`,
            ...(c.sources?.length ? { citation: c.sources.map(s => s.url) } : {}),
          }),
        }}
      />

      <article className="legal-body">
        <Breadcrumbs trail={[{ name: 'Home', path: '/' }, { name: 'Learn', path: '/learn' }, { name: c.shortTitle, path: `/learn/${c.slug}` }]} />

        <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--accent-text)', marginBottom: 12 }}>
          {c.category}
        </div>
        <h1 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(28px, 4.4vw, 44px)', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1.12, marginBottom: 16 }}>
          {c.h1}
        </h1>

        {/* ── Byline / authorship (E-E-A-T) ── */}
        <div style={{ fontSize: 13.5, color: 'var(--text-2)', fontWeight: 300, lineHeight: 1.6, marginBottom: 28, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
          <span style={{ fontWeight: 600, color: 'var(--text)' }}>Reviewed by the Open Lines product team</span>
          {' · '}Published <time dateTime={c.published}>{fmtDate(c.published)}</time>
          {c.updated !== c.published && <> · Updated <time dateTime={c.updated}>{fmtDate(c.updated)}</time></>}
        </div>

        <p style={{ fontSize: 18, color: 'var(--text-2)', lineHeight: 1.75, fontWeight: 300, marginBottom: 8 }}>{c.intro}</p>

        {c.methodology && (
          <div style={{ ...cardBox, marginTop: 20, background: 'var(--bg-3)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--accent-text)', marginBottom: 6 }}>How we researched this</div>
            <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.65, margin: 0, fontWeight: 300 }}>{c.methodology}</p>
          </div>
        )}

        {/* ── Table of contents ── */}
        {c.sections.length > 2 && (
          <nav aria-label="On this page" style={{ ...cardBox, marginTop: 24 }}>
            <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 10 }}>On this page</div>
            <ol style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 7 }}>
              {c.sections.map(s => (
                <li key={s.heading} style={{ fontSize: 14.5, lineHeight: 1.4 }}>
                  <a href={`#${slugify(s.heading)}`} style={{ color: 'var(--accent-text)' }}>{s.heading}</a>
                </li>
              ))}
            </ol>
          </nav>
        )}

        {c.sections.map((s, idx) => (
          <div key={s.heading}>
            <section style={{ marginTop: 40, scrollMarginTop: 24 }} id={slugify(s.heading)}>
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

            {/* ── Soft mid-article CTA (after the 2nd section) ── */}
            {idx === 1 && (
              <div style={{ marginTop: 32, background: 'var(--accent-dim)', borderRadius: 14, padding: '18px 22px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <div style={{ fontSize: 15, color: 'var(--accent-text)', fontWeight: 500 }}>Curious how it sounds on your line?</div>
                <Link href="/how-it-works" style={{ fontSize: 14, fontWeight: 600, color: 'var(--accent-text)' }}>See how Open Lines works →</Link>
              </div>
            )}
          </div>
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

        {/* ── Sources / references ── */}
        {c.sources?.length ? (
          <section style={{ marginTop: 44 }}>
            <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(19px, 2.6vw, 24px)', fontWeight: 700, letterSpacing: '-0.015em', marginBottom: 14 }}>
              Sources
            </h2>
            <ol style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {c.sources.map(s => (
                <li key={s.url} style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.55, fontWeight: 300 }}>
                  <a href={s.url} target="_blank" rel="noopener noreferrer nofollow" style={{ color: 'var(--accent-text)' }}>{s.label}</a>
                </li>
              ))}
            </ol>
          </section>
        ) : null}

        <div style={{ marginTop: 44, display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          <Link href="/onboarding"><button className="btn-trial">Start 7-Day Free Trial →</button></Link>
          <Link href="/learn" style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-2)', alignSelf: 'center' }}>← More guides</Link>
        </div>
      </article>

      <div className="div-line" />

      <RelatedLinks heading="Related reading" links={c.related} />

      <PageCta heading={c.ctaHeading} sub={c.ctaSub} location={`learn_${c.slug}_footer`} />
      <SiteFooter />
    </div>
  )
}
