import Link from 'next/link'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Acceptable Use Policy — Open Lines',
  description: 'Rules governing acceptable use of the Open Lines AI voice receptionist platform.',
  alternates: { canonical: '/acceptable-use' },
}

const LAST_UPDATED = 'July 13, 2026'
const CONTACT_EMAIL = 'support@openlines.ai'

const LogoMark = () => (
  <svg width="24" height="24" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

export default function AcceptableUsePolicy() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>

      {/* Nav */}
      <nav className="site-nav">
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
          Acceptable Use Policy
        </h1>
        <p style={{ fontSize: 14, color: 'var(--text-3)', marginBottom: 48 }}>
          Last updated: {LAST_UPDATED}
        </p>

        <div className="div-line" style={{ marginBottom: 48 }} />

        <Section title="1. About this policy">
          <P>This Acceptable Use Policy (&quot;AUP&quot;) sets out the rules for using the Open Lines AI-powered voice receptionist platform (the &quot;Service&quot;), operated by Open Lines Technologies Inc. (&quot;we&quot;, &quot;our&quot;, &quot;us&quot;). It forms part of, and is incorporated into, our <a href="/terms" style={{ color: 'var(--accent-text)' }}>Terms of Service</a>. By using the Service, you agree to comply with this AUP.</P>
          <P>You are responsible for all activity conducted through your account, including by your employees, contractors, and authorised users.</P>
        </Section>

        <Section title="2. Permitted use">
          <P>You may use the Service only for legitimate business purposes, such as answering inbound customer calls, providing business information, capturing leads, scheduling appointments, and managing customer communications. All use must comply with applicable laws, telecommunications and consumer-protection rules, and your privacy obligations.</P>
        </Section>

        <Section title="3. Prohibited activities">
          <P>You must not use the Service to engage in, facilitate, or support any unlawful, harmful, fraudulent, abusive, or deceptive activity. This includes, but is not limited to:</P>
          <ul style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
            <Li>Committing fraud, impersonating a person or organisation, or misrepresenting your identity or affiliation.</Li>
            <Li>Deceiving callers, running scams, or collecting information under false pretenses.</Li>
            <Li>Threatening, harassing, or intimidating individuals, or generating abusive communications.</Li>
            <Li>Transmitting malicious code, or interfering with or disrupting the Service or related systems.</Li>
            <Li>Attempting to gain unauthorised access to any account, system, or network.</Li>
          </ul>
        </Section>

        <Section title="4. Anti-spam and calling rules">
          <P>You are responsible for complying with all applicable anti-spam, telemarketing, and telecommunications laws, including where applicable Canada&apos;s Anti-Spam Legislation (CASL), the U.S. Telephone Consumer Protection Act (TCPA), and Do-Not-Call rules. You must not use the Service to make unauthorised outbound calls, send unsolicited messages, bypass consent requirements, or contact individuals who have opted out.</P>
        </Section>

        <Section title="5. Responsible AI use and disclosure">
          <P>Because the Service uses artificial intelligence, you agree to use it responsibly. You must configure your AI agent accurately, keep its knowledge sources up to date, and maintain human oversight where appropriate. You acknowledge that AI-generated responses may contain errors, and you remain responsible for the communications and business decisions made through your account.</P>
          <P>You must not configure the Service to mislead callers about the identity of the AI agent, the identity of your business, or the purpose of the call. Where required by law, you must ensure callers receive appropriate disclosures about AI interaction, call recording, and data collection, as described in our <a href="/terms" style={{ color: 'var(--accent-text)' }}>Terms of Service</a>.</P>
        </Section>

        <Section title="6. Impersonation and synthetic voice">
          <P>You must not use the Service to clone a person&apos;s voice without authorisation, impersonate public figures or third parties, create deceptive synthetic identities, or generate fraudulent voice communications. Any use of synthetic-voice technology must comply with applicable laws and have appropriate authorisation.</P>
        </Section>

        <Section title="7. Privacy and sensitive information">
          <P>You are responsible for handling caller and customer information lawfully — collecting it fairly, providing required privacy notices, obtaining necessary consent, and respecting individuals&apos; privacy rights. You must not upload or process information you do not have the legal right to use. We process caller information on your behalf as described in our <a href="/privacy" style={{ color: 'var(--accent-text)' }}>Privacy Policy</a> and <a href="/dpa" style={{ color: 'var(--accent-text)' }}>Data Processing Agreement</a>.</P>
          <P>You should avoid configuring the Service to collect highly sensitive information — such as government identification numbers, financial account credentials, passwords, or medical records — unless you have appropriate authorisation and safeguards in place.</P>
        </Section>

        <Section title="8. Security">
          <P>You must not share account credentials, permit unauthorised access, attempt to bypass security controls, probe or test our systems without authorisation, introduce malicious code, access another customer&apos;s data, or reverse-engineer any part of the platform. Notify us promptly at <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent-text)' }}>{CONTACT_EMAIL}</a> if you become aware of a security issue.</P>
        </Section>

        <Section title="9. Restricted use cases">
          <P>We may restrict or prohibit use cases that create legal, regulatory, security, or reputational risk — including unlawful financial schemes, fraud, unlawful gambling, illegal goods or services, deceptive lead generation, unauthorised surveillance, and any use prohibited by applicable law. We may evaluate additional restricted uses as legal and industry standards evolve.</P>
        </Section>

        <Section title="10. Enforcement">
          <P>We may monitor use of the Service to maintain security, prevent abuse, and comply with legal obligations, but we are not obligated to review all activity. If you violate this AUP, create security risks, or cause harm to others, we may suspend or terminate your access, with or without notice, as described in our <a href="/terms" style={{ color: 'var(--accent-text)' }}>Terms of Service</a>.</P>
        </Section>

        <Section title="11. Reporting a violation">
          <P>If you become aware of misuse of the Service or a violation of this AUP, please report it to us at <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: 'var(--accent-text)' }}>{CONTACT_EMAIL}</a> with as much detail as you can provide.</P>
        </Section>

        <Section title="12. Changes and contact">
          <P>We may update this AUP from time to time. The &quot;Last updated&quot; date reflects the latest version, and continued use of the Service constitutes acceptance of the updated policy.</P>
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

function Li({ children }: { children: React.ReactNode }) {
  return (
    <li style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300 }}>
      {children}
    </li>
  )
}
