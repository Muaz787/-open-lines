import Link from 'next/link'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Terms of Service — Open Lines',
  description: 'Terms and conditions for using the Open Lines platform.',
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

export default function TermsOfService() {
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
          Terms of Service
        </h1>
        <p style={{ fontSize: 14, color: 'var(--text-3)', marginBottom: 48 }}>
          Last updated: {LAST_UPDATED}
        </p>

        <div className="div-line" style={{ marginBottom: 48 }} />

        <Section title="1. Agreement to these terms">
          <P>By accessing or using Open Lines (the &quot;Service&quot;), you agree to be bound by these Terms of Service (&quot;Terms&quot;). If you are using the Service on behalf of a business, you represent that you have the authority to bind that business to these Terms. If you do not agree, do not use the Service.</P>
          <P>Open Lines is operated by Open Lines Technologies Inc. (&quot;we&quot;, &quot;our&quot;, &quot;us&quot;). Contact: <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent)' }}>{CONTACT_EMAIL}</a>.</P>
        </Section>

        <Section title="2. Description of the service">
          <P>Open Lines provides an AI-powered voice receptionist platform that enables businesses (&quot;tenants&quot;) to:</P>
          <ul style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
            <Li>Receive and handle inbound phone calls using an AI voice agent.</Li>
            <Li>Capture and manage lead information from callers.</Li>
            <Li>Book, reschedule, and cancel appointments via Google Calendar integration.</Li>
            <Li>Receive post-call summaries via WhatsApp and SMS.</Li>
            <Li>View call analytics and lead records through a web dashboard.</Li>
          </ul>
          <P>The Service is intended for businesses and is not directed at consumers for personal use.</P>
        </Section>

        <Section title="3. Account registration and onboarding">
          <P>To use the Service, you must complete the onboarding process and provide accurate business information. You are responsible for maintaining the confidentiality of any credentials associated with your account and for all activity that occurs under it. Notify us immediately at <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent)' }}>{CONTACT_EMAIL}</a> if you suspect unauthorised access.</P>
          <P>We reserve the right to suspend or terminate accounts that provide false information or violate these Terms.</P>
        </Section>

        <Section title="4. Acceptable use">
          <P>You agree not to use the Service to:</P>
          <ul style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
            <Li>Make or facilitate calls that are deceptive, fraudulent, or illegal.</Li>
            <Li>Harass, threaten, or deceive callers.</Li>
            <Li>Violate any applicable telemarketing, TCPA, CASL, or equivalent regulations in your jurisdiction.</Li>
            <Li>Collect personal data from callers beyond what is necessary to handle their enquiry.</Li>
            <Li>Attempt to reverse-engineer, copy, or resell any part of the platform.</Li>
            <Li>Introduce malicious code or attempt to gain unauthorised access to our systems.</Li>
          </ul>
          <P>You are solely responsible for ensuring your use of the Service complies with all applicable laws in your jurisdiction, including laws governing AI-assisted communications, call recording, and data privacy.</P>
        </Section>

        <Section title="5. Call recording and AI disclosure">
          <P>Open Lines AI agents conduct and transcribe phone calls on your behalf. You are responsible for complying with all applicable laws regarding call recording and AI disclosure in your jurisdiction. In many regions, this requires informing callers that they are speaking with an AI and/or that the call is being recorded. It is your responsibility to configure your agent&apos;s greeting accordingly.</P>
          <P>We are not liable for any regulatory penalties arising from your failure to make required disclosures to callers.</P>
        </Section>

        <Section title="6. Google Calendar integration">
          <P>By connecting your Google Calendar, you authorise Open Lines to read your availability and create, modify, or delete calendar events solely for the purpose of managing appointments booked through the Service. You can revoke this access at any time. Revoking access will disable appointment booking features but will not affect your other account functionality.</P>
        </Section>

        <Section title="7. Intellectual property">
          <P>All software, design, branding, and content comprising the Open Lines platform is owned by or licensed to us and is protected by applicable intellectual property laws. These Terms do not grant you any ownership rights in the platform.</P>
          <P>You retain ownership of your business data, call records, and knowledge base content. By uploading content to Open Lines, you grant us a limited licence to process and store that content solely to operate the Service for you.</P>
        </Section>

        <Section title="8. Availability and modifications">
          <P>We aim to keep the Service available at all times but do not guarantee uninterrupted access. We may modify, suspend, or discontinue any feature of the Service at any time. For significant changes, we will endeavour to provide reasonable notice via email.</P>
          <P>We reserve the right to update these Terms at any time. The &quot;Last updated&quot; date will reflect changes. Continued use of the Service after changes constitutes your acceptance of the revised Terms.</P>
        </Section>

        <Section title="9. Payment and cancellation">
          <P>Pricing and billing terms are agreed at the time of subscription. You may cancel your account at any time by contacting us at <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent)' }}>{CONTACT_EMAIL}</a>. Upon cancellation, your AI agent and phone number will be deprovisioned. We do not offer prorated refunds for partial billing periods unless required by law.</P>
        </Section>

        <Section title="10. Disclaimer of warranties">
          <P>The Service is provided &quot;as is&quot; and &quot;as available&quot; without warranties of any kind, express or implied. We do not warrant that the AI agent will handle every call correctly, that transcriptions will be error-free, or that the Service will meet all of your specific business requirements. Use of AI-generated responses is at your own discretion.</P>
        </Section>

        <Section title="11. Limitation of liability">
          <P>To the maximum extent permitted by applicable law, Open Lines and its operators shall not be liable for any indirect, incidental, consequential, or punitive damages arising from your use of the Service, including missed calls, incorrect bookings, lost leads, or regulatory fines. Our total liability for any claim related to the Service shall not exceed the amount you paid us in the 30 days prior to the claim.</P>
        </Section>

        <Section title="12. Indemnification">
          <P>You agree to indemnify and hold harmless Open Lines and its operators from any claims, losses, or damages (including legal fees) arising from your use of the Service, your violation of these Terms, or your violation of any applicable law or third-party right.</P>
        </Section>

        <Section title="13. Governing law">
          <P>These Terms are governed by the laws of Ontario, Canada, without regard to conflict of law principles. Any disputes shall be resolved in the courts of Ontario, and you consent to exclusive jurisdiction and venue in those courts.</P>
        </Section>

        <Section title="14. Contact">
          <P>For questions about these Terms:</P>
          <div style={{ marginTop: 12, padding: '16px 20px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 10, fontSize: 14 }}>
            <strong>Open Lines Technologies Inc.</strong><br />
            <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent)' }}>{CONTACT_EMAIL}</a>
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

function Li({ children }: { children: React.ReactNode }) {
  return (
    <li style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300 }}>
      {children}
    </li>
  )
}
