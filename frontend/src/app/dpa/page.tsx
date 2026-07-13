import Link from 'next/link'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Data Processing Agreement — Open Lines',
  description: 'How Open Lines processes personal information on behalf of its business customers.',
  alternates: { canonical: '/dpa' },
}

const LAST_UPDATED = 'July 13, 2026'
const CONTACT_EMAIL = 'privacy@openlines.ai'
const COMPANY_ADDRESS = '201-5255 Yonge St, North York, ON M2N 6P4, Canada'

const LogoMark = () => (
  <svg width="24" height="24" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

export default function DataProcessingAgreement() {
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
          Data Processing Agreement
        </h1>
        <p style={{ fontSize: 14, color: 'var(--text-3)', marginBottom: 48 }}>
          Last updated: {LAST_UPDATED}
        </p>

        <div className="div-line" style={{ marginBottom: 48 }} />

        <Section title="1. Purpose and scope">
          <P>This Data Processing Agreement (&quot;DPA&quot;) forms part of, and supplements, the <a href="/terms" style={{ color: 'var(--accent-text)' }}>Terms of Service</a> between Open Lines Technologies Inc. (&quot;Open Lines&quot;, &quot;we&quot;, &quot;our&quot;, &quot;us&quot;) and the business that subscribes to the Service (&quot;Customer&quot;, &quot;you&quot;). It governs how we process personal information on your behalf when providing the Open Lines AI-powered voice receptionist platform (the &quot;Service&quot;).</P>
          <P>This DPA applies only to personal information we process on your behalf. It does not apply to information we process for our own business purposes — such as account administration, billing, security monitoring, and fraud prevention — which is governed by our <a href="/privacy" style={{ color: 'var(--accent-text)' }}>Privacy Policy</a>.</P>
        </Section>

        <Section title="2. Definitions">
          <P><strong>&quot;Personal Information&quot;</strong> means information about an identifiable individual, as defined under applicable privacy laws.</P>
          <P><strong>&quot;Customer Data&quot;</strong> means information submitted through the Service by you or your users, including caller information, call recordings, transcripts, appointment details, lead information, and knowledge-base content.</P>
          <P><strong>&quot;Processing&quot;</strong> means any operation performed on personal information, including collection, storage, use, disclosure, retrieval, analysis, or deletion.</P>
          <P><strong>&quot;Applicable Privacy Laws&quot;</strong> means the privacy and data-protection laws that apply to the processing, including Canada&apos;s Personal Information Protection and Electronic Documents Act (PIPEDA) and applicable provincial privacy laws, and — where applicable to you — the EU General Data Protection Regulation (GDPR) and the California Consumer Privacy Act (CCPA).</P>
        </Section>

        <Section title="3. Roles of the parties">
          <P><strong>You are the controller.</strong> You determine why and what personal information is collected through your AI agent, how it is used, and the notices and consents required from your callers. You are responsible for ensuring your instructions to us comply with Applicable Privacy Laws.</P>
          <P><strong>We are the processor.</strong> We process personal information only to provide the Service, according to your instructions, as needed to maintain security, and as required by law. We do not sell Customer Data, and we do not use it for our own unrelated purposes.</P>
        </Section>

        <Section title="4. Processing instructions">
          <P>You instruct us to process personal information for the purpose of providing the Service, which includes: answering and managing inbound calls; generating transcripts and summaries; scheduling appointments through connected calendars; sending notifications; storing and retrieving records; providing analytics; troubleshooting; and maintaining the security and reliability of the Service. We process personal information only as necessary for these purposes.</P>
        </Section>

        <Section title="5. Categories of data and data subjects">
          <P>Depending on how you configure the Service, we may process names, telephone numbers, email addresses, appointment details, caller enquiries, call recordings and voice data, transcripts, preferences, and AI-generated summaries. Data subjects may include your callers, customers, prospects, employees, and representatives. You determine whether any sensitive or regulated information is submitted through the Service.</P>
        </Section>

        <Section title="6. Your responsibilities">
          <P>You are responsible for providing lawful instructions; giving your callers appropriate privacy notices; obtaining any required consent (including for call recording); complying with telecommunications and anti-spam laws; configuring your AI agent appropriately; and responding to requests from individuals about their information. We are not responsible for your failure to meet these obligations.</P>
        </Section>

        <Section title="7. Confidentiality">
          <P>Personnel authorised to process Customer Data are bound by confidentiality obligations. We will not disclose Customer Data except to provide the Service, to authorised sub-processors, as you direct, as required by law, or to protect rights, security, or property.</P>
        </Section>

        <Section title="8. Security">
          <P>We implement administrative, technical, and organisational safeguards appropriate to the personal information we process, including encryption in transit and at rest, access controls, authentication requirements, monitoring, backups, and incident-response processes. Further detail is in our <a href="/privacy" style={{ color: 'var(--accent-text)' }}>Privacy Policy</a>. No security system can guarantee absolute protection.</P>
        </Section>

        <Section title="9. Sub-processors">
          <P>You authorise us to engage third-party service providers (&quot;sub-processors&quot;) to help deliver the Service — for example, cloud hosting, telephony, AI, messaging, and payment providers. We require sub-processors to maintain appropriate confidentiality and security obligations, and we remain responsible for their performance under this DPA. A current list of our sub-processors is available at <a href="/subprocessors" style={{ color: 'var(--accent-text)' }}>openlines.ai/subprocessors</a>.</P>
        </Section>

        <Section title="10. Artificial intelligence">
          <P>The Service uses AI to perform speech recognition, conversation handling, transcription, summarisation, and appointment assistance. You acknowledge that AI output may contain errors and requires appropriate oversight, and that you remain responsible for decisions made using it. We do not use Customer Data to train publicly available AI models without your written authorisation.</P>
        </Section>

        <Section title="11. Data-subject requests">
          <P>Where required by Applicable Privacy Laws, we will provide reasonable assistance to help you respond to requests from individuals to access, correct, delete, or port their information, or to restrict its processing. You remain responsible for verifying the identity of requestors and determining whether a disclosure is legally required.</P>
        </Section>

        <Section title="12. Breach notification">
          <P>We will notify you without undue delay after confirming a security incident involving unauthorised access to Customer Data that requires notification under Applicable Privacy Laws. Our notice will describe, to the extent known, the nature of the incident, the information affected, the likely impact, and the steps we are taking. We will cooperate reasonably with your investigation and response.</P>
        </Section>

        <Section title="13. International processing">
          <P>Your primary database — the main store of tenant and caller records — is hosted in <strong>Canada</strong> (Supabase, ca-central-1 / Montreal). Some processing (for example, live call transcription, language, voice, telephony, and email) is performed by sub-processors located in the United States and other countries, so some personal information may be processed outside Canada and may be subject to the laws of those countries. We use these providers under contractual safeguards intended to provide a comparable level of protection to that required under Canadian law.</P>
        </Section>

        <Section title="14. Retention and deletion">
          <P>We retain Customer Data for as long as needed to provide the Service and as described in our <a href="/privacy" style={{ color: 'var(--accent-text)' }}>Privacy Policy</a>. You may request deletion of Customer Data at any time by contacting us. Following termination of the Service, we may delete Customer Data after thirty (30) days unless we are required by law to retain it.</P>
        </Section>

        <Section title="15. Audit and compliance">
          <P>On reasonable written request, we will provide information reasonably necessary to demonstrate compliance with this DPA. Such requests must not be disruptive, must not seek access to other customers&apos; information or confidential security details, and may be subject to reasonable notice and fees.</P>
        </Section>

        <Section title="16. Liability">
          <P>Each party&apos;s liability under this DPA is subject to the limitations and exclusions set out in the <a href="/terms" style={{ color: 'var(--accent-text)' }}>Terms of Service</a>. This DPA does not create additional liability beyond those Terms except where required by Applicable Privacy Laws.</P>
        </Section>

        <Section title="17. Term, governing law, and precedence">
          <P>This DPA remains in effect for as long as we process Customer Data on your behalf. It is governed by the laws of Ontario, Canada, and the parties submit to the exclusive jurisdiction of the courts of Ontario. If there is a conflict between this DPA and the Terms of Service regarding the processing of Customer Data, this DPA controls.</P>
        </Section>

        <Section title="18. Contact">
          <P>For questions about this DPA or our data-processing practices, contact our Privacy Officer:</P>
          <div style={{ marginTop: 12, padding: '16px 20px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 10, fontSize: 14 }}>
            <strong>Open Lines Technologies Inc.</strong><br />
            Attn: Privacy Officer<br />
            {COMPANY_ADDRESS}<br />
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
