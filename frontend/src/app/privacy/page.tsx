import Link from 'next/link'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Privacy Policy — Open Lines',
  description: 'How Open Lines collects, uses, and protects your data.',
}

const LAST_UPDATED = 'May 8, 2026'
const CONTACT_EMAIL = 'muaz91@hotmail.com'

const LogoMark = () => (
  <svg width="24" height="24" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

export default function PrivacyPolicy() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>

      {/* Nav */}
      <nav>
        <Link href="/" className="nav-logo">
          <LogoMark />
          <span className="logo-name">open lines</span>
        </Link>
        <div className="nav-right">
          <Link href="/">
            <button className="btn-nav" style={{ background: 'transparent', color: 'var(--text-2)', border: '1px solid var(--border-2)' }}>
              ← Back to home
            </button>
          </Link>
        </div>
      </nav>

      {/* Content */}
      <div className="legal-body">

        <div className="sec-label" style={{ marginBottom: 16 }}>Legal</div>
        <h1 style={{ fontSize: 'clamp(28px, 4vw, 42px)', fontWeight: 700, letterSpacing: '-0.025em', lineHeight: 1.1, marginBottom: 12 }}>
          Privacy Policy
        </h1>
        <p style={{ fontSize: 14, color: 'var(--text-3)', marginBottom: 48 }}>
          Last updated: {LAST_UPDATED}
        </p>

        <div className="div-line" style={{ marginBottom: 48 }} />

        <Section title="1. Who we are">
          <P>Open Lines Technologies Inc. (&quot;we&quot;, &quot;our&quot;, &quot;us&quot;) provides an AI-powered voice receptionist platform that answers phone calls, captures lead information, and books appointments on behalf of businesses (&quot;tenants&quot;). This policy explains how we collect, use, and protect personal data when you interact with our platform — whether as a business that signs up to use Open Lines, or as a caller who speaks with an Open Lines AI agent.</P>
          <P>Questions or requests regarding this policy can be sent to <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent-text)' }}>{CONTACT_EMAIL}</a>.</P>
        </Section>

        <Section title="2. Data we collect">
          <SubHeading>From callers (people who call a business using Open Lines)</SubHeading>
          <ul style={{ paddingLeft: 20, marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Li><strong>Name and phone number</strong> — captured during the call to create a lead record for the business.</Li>
            <Li><strong>Call transcript</strong> — a text record of the conversation, used to generate a summary and identify the caller&apos;s intent.</Li>
            <Li><strong>Appointment details</strong> — date, time, and service type when a booking is made.</Li>
            <Li><strong>Call metadata</strong> — call duration and timestamp.</Li>
          </ul>

          <SubHeading>From businesses (tenants)</SubHeading>
          <ul style={{ paddingLeft: 20, marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Li><strong>Business information</strong> — name, industry, phone number, and configuration preferences provided during onboarding.</Li>
            <Li><strong>Google Calendar credentials</strong> — an OAuth refresh token, stored securely, used solely to check availability and manage appointments on your behalf.</Li>
            <Li><strong>Knowledge base content</strong> — website content or uploaded documents used to train your AI agent.</Li>
          </ul>
        </Section>

        <Section title="3. How we use your data">
          <P>We use the data we collect only to operate and improve the Open Lines service:</P>
          <ul style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Li>Answer inbound phone calls and conduct AI-assisted conversations.</Li>
            <Li>Create and manage lead records in the tenant&apos;s dashboard.</Li>
            <Li>Check calendar availability and create, update, or cancel appointments in Google Calendar on the tenant&apos;s behalf.</Li>
            <Li>Send post-call summaries to the business by email.</Li>
            <Li>Send appointment confirmation messages to callers by SMS.</Li>
            <Li>Generate and display call analytics in the tenant dashboard.</Li>
          </ul>
          <P style={{ marginTop: 16 }}>We do not sell personal data to third parties. We do not use caller data for advertising.</P>
        </Section>

        <Section title="4. Google Calendar API">
          <P>Open Lines integrates with the Google Calendar API to check a tenant&apos;s availability and create, modify, or delete calendar events on their behalf. Our use of Google Calendar data complies with the <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-text)' }}>Google API Services User Data Policy</a>, including the Limited Use requirements.</P>
          <P>Specifically:</P>
          <ul style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Li>We access Google Calendar data only to perform booking operations requested by the tenant.</Li>
            <Li>We do not store the content of existing calendar events — only the event IDs needed to cancel them during reschedules.</Li>
            <Li>We do not share calendar data with any third party.</Li>
            <Li>We do not use calendar data to serve advertisements.</Li>
            <Li>Tenants can disconnect their Google Calendar at any time, which invalidates our access.</Li>
          </ul>
        </Section>

        <Section title="5. Third-party services">
          <P>We use the following services to operate the platform. Each processes data only as necessary to provide their function:</P>
          <ul style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Li><strong>Twilio</strong> — phone number provisioning and SMS delivery.</Li>
            <Li><strong>Vapi</strong> — AI voice call processing and transcription.</Li>
            <Li><strong>OpenAI</strong> — natural language processing for call summaries and lead extraction.</Li>
            <Li><strong>Supabase</strong> — secure database storage for tenant and caller data.</Li>
            <Li><strong>Pinecone</strong> — vector storage for the knowledge base powering each AI agent.</Li>
            <Li><strong>Firecrawl</strong> — website scraping to build the initial knowledge base for each tenant.</Li>
          </ul>
        </Section>

        <Section title="6. Data retention">
          <P>Call transcripts and lead records are retained for as long as the business account is active. Tenants can request deletion of their data and associated caller records at any time by contacting us at <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent-text)' }}>{CONTACT_EMAIL}</a>.</P>
          <P>When a tenant disconnects Google Calendar, the OAuth refresh token is deleted from our database immediately.</P>
        </Section>

        <Section title="7. Data security">
          <P>All data is stored in Supabase, which uses row-level security and encrypts data at rest. All communication between services uses HTTPS/TLS. Google OAuth tokens are stored encrypted and are never exposed to frontend clients. Access to production data is restricted to authorised personnel only.</P>
        </Section>

        <Section title="8. Your rights">
          <P>Depending on where you are located, you may have the right to access, correct, or delete personal data we hold about you. To exercise any of these rights, contact us at <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent-text)' }}>{CONTACT_EMAIL}</a> and we will respond within 30 days.</P>
        </Section>

        <Section title="9. Changes to this policy">
          <P>We may update this policy from time to time. The &quot;Last updated&quot; date at the top of this page will reflect any changes. Continued use of the platform after changes constitutes acceptance of the revised policy.</P>
        </Section>

        <Section title="10. Contact">
          <P>For any privacy-related questions or requests:</P>
          <div style={{ marginTop: 12, padding: '16px 20px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 10, fontSize: 14 }}>
            <strong>Open Lines Technologies Inc.</strong><br />
            <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent-text)' }}>{CONTACT_EMAIL}</a>
          </div>
        </Section>

        <div className="div-line" style={{ margin: '48px 0 32px' }} />

        <p style={{ fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>
          © {new Date().getFullYear()} Open Lines Technologies Inc. All rights reserved.
        </p>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 44 }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em', marginBottom: 14, lineHeight: 1.3 }}>
        {title}
      </h2>
      {children}
    </section>
  )
}

function P({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <p style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.75, marginBottom: 12, fontWeight: 300, ...style }}>
      {children}
    </p>
  )
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 8, marginTop: 16 }}>
      {children}
    </p>
  )
}

function Li({ children }: { children: React.ReactNode }) {
  return (
    <li style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300 }}>
      {children}
    </li>
  )
}
