import type { Metadata } from 'next'
import SiteNav from '../components/SiteNav'
import SiteFooter from '../components/SiteFooter'
import PageCta from '../components/PageCta'

export const metadata: Metadata = {
  title: 'Platform — Open Lines AI',
  description: 'Everything a front desk does, automated: 24/7 answering, lead qualification, calendar booking, deposits, a knowledge base, notifications, insights, and integrations — with Canadian privacy compliance.',
}

const FEATURES = [
  { icon: '📞', title: 'Answering & lead capture', body: 'A warm, human-sounding receptionist answers 24/7, recognises returning callers, and qualifies every lead.' },
  { icon: '📅', title: 'Appointment booking', body: 'Books, reschedules and cancels directly in Google Calendar, Microsoft Outlook, or Square Appointments — with named-staff booking.' },
  { icon: '💳', title: 'Deposits & payments', body: 'Collect deposits on the call via secure Stripe or Square links — including group and per-person deposits (Pro & Business).' },
  { icon: '🧠', title: 'Knowledge base', body: 'Learns from your website and uploaded documents — PDFs, Word, Excel, even scanned files via OCR — to answer confidently.' },
  { icon: '🔔', title: 'Notifications', body: 'Call summaries by email, plus optional SMS and WhatsApp alerts to you and confirmations to your callers.' },
  { icon: '📊', title: 'AI insights & dashboard', body: 'Full transcripts, AI call summaries, and operations insights that show what callers want and where you’re losing them.' },
]

const INTEGRATIONS = [
  'Google Calendar', 'Microsoft Outlook', 'Square Appointments',
  'Stripe', 'Square', 'HubSpot', 'Slack', 'Zapier',
]

const SECURITY = [
  { title: 'Canadian & PIPEDA-compliant', body: 'Built and operated in Canada, aligned with Canadian privacy law.' },
  { title: 'Transparent & recorded', body: 'Callers are told they’ve reached a virtual receptionist and that calls may be recorded.' },
  { title: 'Encrypted & PCI-safe', body: 'Data is encrypted and payments run through PCI-compliant providers — the AI never asks for card numbers.' },
  { title: 'You control your data', body: 'Retention and deletion handled on request; role-based access to your dashboard.' },
]

export default function PlatformPage() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>
      <SiteNav />

      <section className="sec" style={{ textAlign: 'center', paddingBottom: 40 }}>
        <div className="wrap">
          <div className="sec-label">Platform</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', maxWidth: 640, margin: '0 auto 14px' }}>
            Everything your front desk does — automated.
          </h2>
          <p className="sec-sub" style={{ maxWidth: 500, margin: '0 auto' }}>
            One platform that answers, qualifies, books, takes payment, and reports back — so no call and no lead is ever missed.
          </p>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0 }}>
        <div className="wrap">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
            {FEATURES.map(f => (
              <div key={f.title} style={{ background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '22px 22px' }}>
                <div style={{ fontSize: 24, marginBottom: 10 }}>{f.icon}</div>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{f.title}</div>
                <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="div-line" />

      <section className="sec" style={{ textAlign: 'center' }}>
        <div className="wrap">
          <div className="sec-label">Integrations</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 24 }}>Works with the tools you already use.</h2>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, justifyContent: 'center', maxWidth: 640, margin: '0 auto' }}>
            {INTEGRATIONS.map(t => (
              <span key={t} style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-2)', background: 'var(--bg-2)', border: '1px solid var(--border-2)', padding: '8px 16px', borderRadius: 20 }}>{t}</span>
            ))}
          </div>
        </div>
      </section>

      <div className="div-line" />

      <section className="sec">
        <div className="wrap">
          <div className="sec-label">Security & compliance</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 28 }}>Trustworthy by design.</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
            {SECURITY.map(s => (
              <div key={s.title} style={{ background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '22px 22px' }}>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{s.title}</div>
                <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <PageCta location="platform_bottom" />
      <SiteFooter />
    </div>
  )
}
