import type { Metadata } from 'next'
import Link from 'next/link'
import SiteNav from '../components/SiteNav'
import SiteFooter from '../components/SiteFooter'
import PageCta from '../components/PageCta'
import { BreadcrumbJsonLd } from '../components/JsonLd'
import { INTEGRATIONS } from './integrations-data'

export const metadata: Metadata = {
  title: 'Integrations — Open Lines AI',
  description: 'Open Lines works with the calendar, CRM, payment, and notification tools you already run — Google Calendar, Outlook, Square Appointments, HubSpot, Slack, and Stripe.',
  alternates: { canonical: '/integrations' },
}

export default function IntegrationsHub() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)', overflowX: 'hidden' }}>
      <SiteNav />
      <BreadcrumbJsonLd trail={[{ name: 'Home', path: '/' }, { name: 'Integrations', path: '/integrations' }]} />

      <section className="sec" style={{ textAlign: 'center', paddingBottom: 40 }}>
        <div className="wrap">
          <div className="sec-label">Integrations</div>
          <h1 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(30px, 4.6vw, 46px)', fontWeight: 700, letterSpacing: '-0.025em', maxWidth: 680, margin: '0 auto 14px' }}>
            Plugs into the tools you already run.
          </h1>
          <p className="sec-sub" style={{ maxWidth: 540, margin: '0 auto' }}>
            No rip-and-replace. Open Lines answers your phone and books, logs, notifies, and collects payments through
            the software your business already uses.
          </p>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0 }}>
        <div className="wrap">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
            {INTEGRATIONS.map(i => (
              <Link
                key={i.slug}
                href={`/integrations/${i.slug}`}
                style={{ display: 'block', background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '22px 22px', color: 'inherit' }}
              >
                <div style={{ fontSize: 26, marginBottom: 10 }}>{i.emoji}</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{i.name}</div>
                <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--accent-text)', marginBottom: 8 }}>{i.eyebrow}</div>
                <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{i.subhead}</p>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent-text)', marginTop: 14 }}>Learn more →</div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <PageCta
        heading="Answer every call — inside the tools you already use."
        sub="Set up your AI receptionist in under 10 minutes and connect your calendar, CRM, and payments."
        location="integrations_hub_bottom"
      />
      <SiteFooter />
    </div>
  )
}
