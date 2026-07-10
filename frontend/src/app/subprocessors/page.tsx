import Link from 'next/link'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Sub-processors — Open Lines',
  description: 'The third-party service providers (sub-processors) Open Lines uses to operate its AI receptionist platform, with their purpose and location.',
  alternates: { canonical: '/subprocessors' },
}

const LAST_UPDATED = 'July 10, 2026'

// Keep this list current. It is referenced from the Privacy Policy.
const SUBPROCESSORS: { name: string; purpose: string; location: string }[] = [
  { name: 'Twilio',      purpose: 'Phone number provisioning and SMS delivery', location: 'United States' },
  { name: 'Vapi',        purpose: 'AI voice call orchestration and transcription', location: 'United States' },
  { name: 'Deepgram',    purpose: 'Speech-to-text (via Vapi)', location: 'United States' },
  { name: 'OpenAI',      purpose: 'Language model — call summaries, lead extraction, and responses', location: 'United States' },
  { name: 'ElevenLabs',  purpose: 'Text-to-speech voice (via Vapi)', location: 'United States' },
  { name: 'Supabase',    purpose: 'Database storage and authentication', location: 'United States' },
  { name: 'Pinecone',    purpose: 'Vector storage for each agent’s knowledge base', location: 'United States' },
  { name: 'Firecrawl',   purpose: 'Website content extraction to build the knowledge base', location: 'United States' },
  { name: 'Mistral',     purpose: 'OCR for scanned/image documents uploaded to the knowledge base', location: 'European Union (France)' },
  { name: 'Stripe',      purpose: 'Subscription billing and appointment-deposit payments', location: 'United States / Ireland' },
  { name: 'Square',      purpose: 'Appointment-deposit payments (alternative provider)', location: 'United States / Canada' },
  { name: 'Resend',      purpose: 'Transactional email (call summaries and account notices)', location: 'United States' },
  { name: 'Google',      purpose: 'Calendar booking, where the tenant connects their account', location: 'United States' },
  { name: 'Microsoft',   purpose: 'Outlook calendar booking, where the tenant connects their account', location: 'United States' },
  { name: 'HubSpot',     purpose: 'CRM sync (optional integration a tenant may enable)', location: 'United States' },
  { name: 'Slack',       purpose: 'Notifications (optional integration a tenant may enable)', location: 'United States' },
  { name: 'PostHog',     purpose: 'Privacy-conscious product analytics', location: 'United States' },
  { name: 'Railway',     purpose: 'Backend application hosting', location: 'United States' },
  { name: 'Vercel',      purpose: 'Frontend application hosting', location: 'United States' },
]

const LogoMark = () => (
  <svg width="24" height="24" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

export default function Subprocessors() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>

      <nav>
        <Link href="/" className="nav-logo">
          <LogoMark />
          <span className="logo-name">open lines</span>
        </Link>
        <div className="nav-right">
          <Link href="/privacy">
            <button className="btn-nav" style={{ background: 'transparent', color: 'var(--text-2)', border: '1px solid var(--border-2)' }}>
              ← Privacy Policy
            </button>
          </Link>
        </div>
      </nav>

      <div className="legal-body">
        <div className="sec-label" style={{ marginBottom: 16 }}>Legal</div>
        <h1 style={{ fontSize: 'clamp(28px, 4vw, 42px)', fontWeight: 700, letterSpacing: '-0.025em', lineHeight: 1.1, marginBottom: 12 }}>
          Sub-processors
        </h1>
        <p style={{ fontSize: 14, color: 'var(--text-3)', marginBottom: 32 }}>
          Last updated: {LAST_UPDATED}
        </p>

        <p style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.7, marginBottom: 32 }}>
          Open Lines uses the third-party service providers below to operate its AI receptionist
          platform. Each processes personal information only as needed to provide its function,
          under contractual confidentiality and security obligations. See our{' '}
          <Link href="/privacy" style={{ color: 'var(--accent-text)' }}>Privacy Policy</Link> for how we handle personal information.
        </p>

        <div className="div-line" style={{ marginBottom: 24 }} />

        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--text-3)', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                <th style={{ padding: '10px 12px 10px 0', borderBottom: '1px solid var(--border)' }}>Provider</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>Purpose</th>
                <th style={{ padding: '10px 0 10px 12px', borderBottom: '1px solid var(--border)' }}>Location</th>
              </tr>
            </thead>
            <tbody>
              {SUBPROCESSORS.map(s => (
                <tr key={s.name}>
                  <td style={{ padding: '12px 12px 12px 0', borderBottom: '1px solid var(--border)', fontWeight: 600, whiteSpace: 'nowrap', verticalAlign: 'top' }}>{s.name}</td>
                  <td style={{ padding: '12px', borderBottom: '1px solid var(--border)', color: 'var(--text-2)', lineHeight: 1.5 }}>{s.purpose}</td>
                  <td style={{ padding: '12px 0 12px 12px', borderBottom: '1px solid var(--border)', color: 'var(--text-2)', whiteSpace: 'nowrap', verticalAlign: 'top' }}>{s.location}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p style={{ fontSize: 13, color: 'var(--text-3)', lineHeight: 1.7, margin: '28px 0 0' }}>
          Because several providers are located outside Canada, personal information may be stored or
          processed abroad and subject to the laws of those countries. Questions about a specific
          provider can be sent to <a href="mailto:privacy@openlines.ai" style={{ color: 'var(--accent-text)' }}>privacy@openlines.ai</a>.
        </p>

        <div className="div-line" style={{ margin: '48px 0 32px' }} />
        <p style={{ fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>
          © {new Date().getFullYear()} Open Lines Technologies Inc. All rights reserved.
        </p>
      </div>
    </div>
  )
}
