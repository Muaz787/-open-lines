import type { Metadata } from 'next'
import Link from 'next/link'
import SiteNav from '../components/SiteNav'
import SiteFooter from '../components/SiteFooter'
import PageCta from '../components/PageCta'
import { BreadcrumbJsonLd } from '../components/JsonLd'
import { ARTICLES } from './learn-data'
import { ogImageUrl } from '@/lib/og-card'

export const metadata: Metadata = {
  title: 'Learn: AI Receptionist & Automation Guides | Open Lines',
  description: 'Practical guides on AI receptionists, answering-service costs, missed-call recovery, and automating your business workflow with AI in 2026.',
  alternates: { canonical: '/learn' },
  openGraph: {
    title: 'Open Lines guides',
    description: 'Plain-English guides on AI receptionists, phone costs, and automating the busywork.',
    url: 'https://www.openlines.ai/learn',
    images: [ogImageUrl({ eyebrow: 'Learn', title: 'Guides for busy businesses.', benefit: 'AI receptionists · costs · automation' })],
  },
}

export default function LearnHub() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)', overflowX: 'hidden' }}>
      <SiteNav />
      <BreadcrumbJsonLd trail={[{ name: 'Home', path: '/' }, { name: 'Learn', path: '/learn' }]} />

      <section className="sec" style={{ textAlign: 'center', paddingBottom: 40 }}>
        <div className="wrap">
          <div className="sec-label">Learn</div>
          <h1 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(30px, 4.6vw, 46px)', fontWeight: 700, letterSpacing: '-0.025em', maxWidth: 680, margin: '0 auto 14px' }}>
            Guides for busy businesses.
          </h1>
          <p className="sec-sub" style={{ maxWidth: 540, margin: '0 auto' }}>
            Plain-English guides on AI receptionists, the real cost of answering your phone, and automating the
            busywork out of your day.
          </p>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0 }}>
        <div className="wrap">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
            {ARTICLES.map(a => (
              <Link
                key={a.slug}
                href={`/learn/${a.slug}`}
                style={{ display: 'flex', flexDirection: 'column', background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '24px 24px', color: 'inherit' }}
              >
                <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--accent-text)', marginBottom: 10 }}>{a.category}</div>
                <div style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 19, fontWeight: 700, letterSpacing: '-0.01em', lineHeight: 1.25, color: 'var(--text)', marginBottom: 10 }}>{a.h1}</div>
                <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300, flexGrow: 1 }}>{a.metaDescription}</p>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent-text)', marginTop: 16 }}>Read the guide →</div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <PageCta
        heading="Ready to stop missing calls?"
        sub="Set up your AI receptionist in under 10 minutes. Free for 7 days."
        location="learn_hub_bottom"
      />
      <SiteFooter />
    </div>
  )
}
