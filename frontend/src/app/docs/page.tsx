import Link from 'next/link'
import ElevenLabsGrantBadge from '../components/ElevenLabsGrantBadge'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Documentation — Open Lines AI',
  description: 'Learn how to set up your AI phone receptionist, connect calendars, sync HubSpot CRM, and configure your Open Lines account.',
  alternates: { canonical: '/docs' },
}

const LogoMark = () => (
  <svg width="24" height="24" viewBox="0 0 28 28" fill="none" style={{ color: 'var(--text)', flexShrink: 0 }}>
    <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="14"   y1="9.5"  x2="14"   y2="18.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    <line x1="17.5" y1="11.5" x2="17.5" y2="17"   stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
)

const QUICK_STEPS = [
  { n: '01', title: 'Create your account',        body: 'Sign up at openlines.ai and complete your business profile — name, industry, and contact preferences.' },
  { n: '02', title: 'Connect a phone number',     body: 'Provision a local or toll-free number. Your AI receptionist answers every call made to this number.' },
  { n: '03', title: 'Upload your business info',  body: 'Add services, pricing, FAQs, and team details to the Knowledge Base. The AI uses this to answer questions accurately.' },
  { n: '04', title: 'Connect your calendar',      body: 'Link Google Calendar or Outlook. The AI checks availability in real time and books appointments automatically.' },
  { n: '05', title: 'Test your AI receptionist', body: 'Call your number and speak with the AI. Adjust tone, knowledge, and booking logic in Settings until it feels right.' },
]

const HUBSPOT_STEPS = [
  { title: 'Navigate to Integrations',    body: 'In your dashboard go to Account → Integrations. Available on Pro and Business plans.' },
  { title: 'Connect HubSpot',             body: 'Click "Connect HubSpot" and authorize Open Lines to access your portal via OAuth.' },
  { title: 'Automatic contact sync',      body: "After every call, Open Lines searches HubSpot for the caller's phone number and creates or updates the contact." },
  { title: 'AI summaries as notes',       body: 'A structured note is added: urgency, appointment status, key details, and suggested next steps. No full transcript.' },
]

const ROUTING_STEPS = [
  { title: 'Open Call Handling',            body: 'In your dashboard go to Call Handling. Available on Pro and Business plans.' },
  { title: 'Add transfer destinations',     body: 'Add the phone numbers to hand callers to — front desk, on-call, a specific team. Domestic numbers only, stored encrypted and shown masked.' },
  { title: 'Choose where calls go',         body: 'Pick a default destination for anyone who needs a person, and an urgent / on-call destination for time-sensitive callers.' },
  { title: 'Add routing rules (optional)',  body: 'Send specific reasons to specific destinations — e.g. "billing → accounts". Rules are checked in order, and urgent always wins.' },
  { title: 'Turn it on',                    body: 'Flip the toggle — nothing changes on your calls until you do. Preview how a caller routes with the built-in "Test it" simulator; no call is placed.' },
]

const SCOPES = [
  { scope: 'crm.objects.contacts.read',  why: 'Search for existing contacts by caller phone number to avoid duplicates.' },
  { scope: 'crm.objects.contacts.write', why: 'Create new contacts and update names when identified from the call.' },
  { scope: 'oauth',                      why: 'Required by HubSpot to establish and maintain the OAuth connection.' },
]

const TROUBLESHOOTING = [
  { title: 'AI not answering calls',     steps: ['Verify your Twilio number is active in Settings → Phone Number', 'Check that your Vapi assistant is connected under Settings', 'Ensure your account is on an active plan'] },
  { title: 'Calendar not booking',       steps: ['Re-connect your calendar under Account → Calendar', 'Confirm business hours are set correctly', 'Check that the calendar token hasn\'t expired — a reconnect fixes it'] },
  { title: 'HubSpot not syncing',        steps: ['Go to Account → Integrations and verify HubSpot shows Connected', 'Disconnect and reconnect to refresh the OAuth token', 'Confirm your HubSpot portal has contacts permissions enabled'] },
  { title: 'AI giving wrong answers',    steps: ['Update your Knowledge Base with more specific information', 'Add explicit FAQs for topics the AI is getting wrong', 'Review recent calls to identify gaps in your knowledge entries'] },
  { title: 'Calls not transferring',     steps: ['Open Call Handling and make sure routing is turned On', 'Add at least one destination and set a default', 'Double-check the destination\'s area code — re-add it if unsure', 'Use "Test it" to preview how a caller routes'] },
]

const FAQS = [
  { q: 'What happens if the AI can\'t answer a question?', a: 'The AI politely lets the caller know it will pass the message on, and captures their contact details for follow-up.' },
  { q: 'Can I use my existing phone number?', a: 'Yes — you can port your existing number to Open Lines, or use call forwarding from your current number.' },
  { q: 'How does calendar booking work?', a: 'The AI checks your connected calendar for available slots, offers times to the caller, and creates the event automatically. Reschedule and cancel are also handled.' },
  { q: 'Is the call transcript stored?', a: 'Transcripts are processed to generate a structured summary, then discarded. Only the summary, urgency, and key details are retained.' },
  { q: 'Can Open Lines transfer callers to my team?', a: 'Yes — on Pro and Business, AI call routing answers routine calls and warm-transfers anyone who needs a person to the right number. It briefs whoever picks up with a one-line summary of who\'s calling and why, then connects the caller. If no one answers, it takes a callback so nothing is lost. Set it up under Call Handling in your dashboard.' },
  { q: 'What\'s the difference between plans?', a: 'Starter covers AI calling, calendar booking, and lead capture. Pro adds deposit collection, HubSpot CRM sync, and AI call routing. Business adds routing at scale, priority support, and higher call volume.' },
  { q: 'How do I change what the AI says?', a: 'Go to Settings in your dashboard to update your AI\'s name, greeting, tone, and the qualification questions it asks callers.' },
]

export default function DocsPage() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>

      <nav className="site-nav">
        <Link href="/" className="nav-logo">
          <LogoMark />
          <span className="logo-name">open lines</span>
        </Link>
        <div className="nav-mid">
          <Link href="/docs">Docs</Link>
          <Link href="/support">Support</Link>
          <Link href="/pricing">Pricing</Link>
        </div>
        <div className="nav-right">
          <Link href="/login">
            <button className="btn-nav" style={{ background: 'transparent', color: 'var(--text-2)', border: '1px solid var(--border-2)' }}>Sign in</button>
          </Link>
          <Link href="/onboarding">
            <button className="btn-nav" style={{ background: 'var(--text)', color: 'var(--bg)' }}>Get started</button>
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <div className="pricing-hero">
        <div className="sec-label" style={{ marginBottom: 14 }}>Documentation</div>
        <h1 style={{ fontSize: 'clamp(28px, 4vw, 48px)', fontWeight: 700, letterSpacing: '-0.03em', lineHeight: 1.1, marginBottom: 16, fontFamily: 'var(--font-syne), sans-serif' }}>
          Everything you need to get started
        </h1>
        <p style={{ fontSize: 16, color: 'var(--text-2)', maxWidth: 480, margin: '0 auto 28px', lineHeight: 1.7, fontWeight: 300 }}>
          Set up your AI phone receptionist, connect your calendar, sync your CRM, and start capturing leads.
        </p>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
          <a href="#quickstart" className="btn-main" style={{ fontSize: 14, padding: '10px 22px' }}>Quick start</a>
          <a href="#faq" className="btn-ghost" style={{ fontSize: 14, padding: '10px 22px' }}>View FAQ</a>
        </div>
      </div>

      <div className="legal-body" style={{ paddingTop: 0 }}>

        {/* Quick Start */}
        <Section id="quickstart" label="Quick Start" title="Up and running in 5 steps" subtitle="Follow these steps in order to configure your AI receptionist from scratch.">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {QUICK_STEPS.map(({ n, title, body }) => (
              <div key={n} style={{ display: 'flex', gap: 16, padding: '16px 18px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 12 }}>
                <div style={{ flexShrink: 0, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)', paddingTop: 2, minWidth: 24 }}>{n}</div>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{title}</div>
                  <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>{body}</div>
                </div>
              </div>
            ))}
          </div>
        </Section>

        <div className="div-line" style={{ margin: '48px 0' }} />

        {/* HubSpot */}
        <Section id="hubspot" label="HubSpot Integration" title="How HubSpot CRM sync works" subtitle="Open Lines automatically creates and updates contacts after every call. Available on Pro and Business plans.">
          <div style={{ padding: '14px 16px', background: 'var(--accent-dim)', border: '1px solid rgba(52,199,89,0.2)', borderRadius: 10, marginBottom: 20, fontSize: 13, color: 'var(--text)', lineHeight: 1.6 }}>
            <strong>Privacy by default:</strong> Open Lines never sends full call transcripts to HubSpot. Only structured summaries are synced.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
            {HUBSPOT_STEPS.map(({ title, body }, i) => (
              <div key={i} style={{ display: 'flex', gap: 14, padding: '14px 16px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 10 }}>
                <div style={{ flexShrink: 0, width: 22, height: 22, borderRadius: '50%', background: 'var(--text)', color: 'var(--bg)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>{i + 1}</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 3 }}>{title}</div>
                  <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>{body}</div>
                </div>
              </div>
            ))}
          </div>
          <InfoBox label="What gets synced to each contact note">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 16px' }}>
              {['Call date & time', 'Caller phone number', 'Urgency (Hot / Warm / Cold)', 'Appointment booked (Yes / No)', '2-sentence AI summary', 'Suggested next step', 'Key qualification details'].map(item => (
                <div key={item} style={{ fontSize: 13, color: 'var(--text-2)', display: 'flex', gap: 7 }}>
                  <span style={{ color: 'var(--accent-text)', flexShrink: 0 }}>✓</span>{item}
                </div>
              ))}
            </div>
          </InfoBox>
          <div style={{ marginTop: 12 }}>
            <InfoBox label="Required HubSpot permissions">
              <p style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6, marginBottom: 14 }}>
                Open Lines requests the minimum scopes needed to create and update contacts. No other HubSpot data is accessed.
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {SCOPES.map(({ scope, why }) => (
                  <div key={scope} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                    <code style={{ flexShrink: 0, fontSize: 11, padding: '2px 8px', borderRadius: 5, background: 'var(--bg-3)', color: 'var(--accent-text)', border: '1px solid var(--border)', fontFamily: 'var(--font-mono)' }}>{scope}</code>
                    <span style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>{why}</span>
                  </div>
                ))}
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 12, lineHeight: 1.6 }}>
                Revoke access any time from HubSpot Settings → Connected Apps, or from Open Lines → Account → Integrations.
              </p>
            </InfoBox>
          </div>
        </Section>

        <div className="div-line" style={{ margin: '48px 0' }} />

        {/* Calendar */}
        <Section id="calendar" label="Calendar" title="Connecting Google Calendar or Outlook" subtitle="Your AI receptionist checks real-time availability and books appointments directly into your calendar.">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
            {[
              { name: 'Google Calendar', steps: ['Go to Account → Calendar', 'Click "Connect Google Calendar"', 'Sign in and grant access', 'Set business hours and appointment duration'] },
              { name: 'Microsoft Outlook', steps: ['Go to Account → Calendar', 'Click "Connect Outlook"', 'Sign in with your Microsoft account', 'Set your availability preferences'] },
            ].map(({ name, steps }) => (
              <div key={name} style={{ padding: '16px 18px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 10 }}>{name}</div>
                <ol style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {steps.map((s, i) => (
                    <li key={i} style={{ display: 'flex', gap: 8, fontSize: 13, color: 'var(--text-2)' }}>
                      <span style={{ flexShrink: 0, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)', paddingTop: 2 }}>{i + 1}.</span>
                      {s}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
          <InfoBox label="Calendar settings you can configure">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 16px' }}>
              {['Appointment duration', 'Business hours', 'Buffer time between appointments', 'Days available for booking', 'Break / lunch windows', 'Timezone'].map(s => (
                <div key={s} style={{ fontSize: 13, color: 'var(--text-2)', display: 'flex', gap: 7 }}>
                  <span style={{ color: 'var(--text-3)', flexShrink: 0 }}>·</span>{s}
                </div>
              ))}
            </div>
          </InfoBox>
        </Section>

        <div className="div-line" style={{ margin: '48px 0' }} />

        {/* Knowledge Base */}
        <Section id="knowledge-base" label="Knowledge Base" title="Uploading your business knowledge" subtitle="The more detail you provide, the more accurately your AI answers caller questions.">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              { title: 'Services & pricing',  body: 'List every service with pricing ranges. The AI quotes these to callers and uses them to qualify intent.' },
              { title: 'Team & availability', body: 'Add staff names, roles, and specialties so the AI can route callers to the right person.' },
              { title: 'FAQs',                body: 'Write your most common caller questions and ideal answers. The AI treats these as ground truth.' },
              { title: 'Location & hours',    body: 'Add your address, parking info, and opening hours so location questions are answered accurately.' },
              { title: 'Policies',            body: 'Cancellation policy, refund terms, and business rules the AI should communicate clearly.' },
            ].map(({ title, body }) => (
              <div key={title} style={{ padding: '14px 18px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{title}</div>
                <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>{body}</div>
              </div>
            ))}
          </div>
        </Section>

        <div className="div-line" style={{ margin: '48px 0' }} />

        {/* Call routing */}
        <Section id="call-routing" label="Call Routing" title="Routing callers to your team" subtitle="Answer routine calls with AI and warm-transfer the ones that need a person to the right place. Available on Pro and Business plans.">
          <div style={{ padding: '14px 16px', background: 'var(--accent-dim)', border: '1px solid rgba(52,199,89,0.2)', borderRadius: 10, marginBottom: 20, fontSize: 13, color: 'var(--text)', lineHeight: 1.6 }}>
            <strong>Opt-in and safe by default:</strong> nothing changes on your calls until you turn routing on, and if no one answers a transfer the AI takes a callback — so no caller is ever dropped.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
            {ROUTING_STEPS.map(({ title, body }, i) => (
              <div key={i} style={{ display: 'flex', gap: 14, padding: '14px 16px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 10 }}>
                <div style={{ flexShrink: 0, width: 22, height: 22, borderRadius: '50%', background: 'var(--text)', color: 'var(--bg)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>{i + 1}</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 3 }}>{title}</div>
                  <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>{body}</div>
                </div>
              </div>
            ))}
          </div>
          <InfoBox label="What call routing does">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 16px' }}>
              {['Warm transfer — briefs your team before connecting the caller', 'Safe callback fallback if no one answers', 'Urgent / on-call routing for time-sensitive calls', 'Deterministic rules by caller intent', 'Domestic numbers only, stored encrypted', 'Never dials emergency or premium numbers'].map(item => (
                <div key={item} style={{ fontSize: 13, color: 'var(--text-2)', display: 'flex', gap: 7 }}>
                  <span style={{ color: 'var(--accent-text)', flexShrink: 0 }}>✓</span>{item}
                </div>
              ))}
            </div>
          </InfoBox>
          <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 12, lineHeight: 1.6 }}>
            Capacity: Pro includes up to 2 destinations and 5 rules; Business up to 50 of each.
          </p>
        </Section>

        <div className="div-line" style={{ margin: '48px 0' }} />

        {/* Troubleshooting */}
        <Section id="troubleshooting" label="Troubleshooting" title="Common issues & fixes" subtitle="Most issues resolve with a reconnect or a Knowledge Base update.">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {TROUBLESHOOTING.map(({ title, steps }) => (
              <div key={title} style={{ padding: '16px 18px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 10 }}>{title}</div>
                <ol style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {steps.map((s, i) => (
                    <li key={i} style={{ display: 'flex', gap: 8, fontSize: 13, color: 'var(--text-2)' }}>
                      <span style={{ flexShrink: 0, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)', paddingTop: 2 }}>{i + 1}.</span>
                      {s}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </Section>

        <div className="div-line" style={{ margin: '48px 0' }} />

        {/* FAQ */}
        <Section id="faq" label="FAQ" title="Frequently asked questions" subtitle={undefined}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {FAQS.map(({ q, a }) => (
              <div key={q} style={{ padding: '16px 18px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 12 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{q}</div>
                <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.7 }}>{a}</div>
              </div>
            ))}
          </div>
        </Section>

        <div className="div-line" style={{ margin: '48px 0' }} />

        {/* Support CTA */}
        <div style={{ textAlign: 'center', padding: '40px 0 20px' }}>
          <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'var(--font-syne)', marginBottom: 10 }}>Still need help?</div>
          <p style={{ fontSize: 14, color: 'var(--text-2)', marginBottom: 24, lineHeight: 1.7 }}>
            Our support team gets back to you within one business day.
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link href="/support" className="btn-main" style={{ fontSize: 14, padding: '10px 22px' }}>Visit support</Link>
            <a href="mailto:support@openlines.ai" className="btn-ghost" style={{ fontSize: 14, padding: '10px 22px' }}>support@openlines.ai</a>
          </div>
        </div>

      </div>

      <footer style={{ borderTop: '1px solid var(--border)', padding: '28px 40px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
        <Link href="/" className="nav-logo"><LogoMark /><span className="logo-name">open lines</span></Link>
        <div style={{ display: 'flex', gap: 20, fontSize: 12, color: 'var(--text-3)' }}>
          <Link href="/privacy" style={{ color: 'inherit', textDecoration: 'none' }}>Privacy</Link>
          <Link href="/terms"   style={{ color: 'inherit', textDecoration: 'none' }}>Terms</Link>
          <Link href="/support" style={{ color: 'inherit', textDecoration: 'none' }}>Support</Link>
          <a href="mailto:support@openlines.ai" style={{ color: 'inherit', textDecoration: 'none' }}>support@openlines.ai</a>
        </div>
        <ElevenLabsGrantBadge />
      </footer>
    </div>
  )
}

function Section({ id, label, title, subtitle, children }: { id?: string; label: string; title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section id={id} style={{ marginBottom: 0 }}>
      <div className="sec-label" style={{ marginBottom: 8 }}>{label}</div>
      <h2 style={{ fontSize: 'clamp(20px, 2.5vw, 26px)', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text)', marginBottom: subtitle ? 8 : 20, fontFamily: 'var(--font-syne)' }}>{title}</h2>
      {subtitle && <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.7, marginBottom: 20 }}>{subtitle}</p>}
      {children}
    </section>
  )
}

function InfoBox({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: '14px 16px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 10 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 12 }}>{label}</div>
      {children}
    </div>
  )
}
