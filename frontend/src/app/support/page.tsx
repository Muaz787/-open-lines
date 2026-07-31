import Link from 'next/link'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Support — Open Lines AI',
  description: 'Get help with Open Lines. Browse our documentation, contact support, or book a live demo.',
  alternates: { canonical: '/support' },
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

const RESPONSE_TIMES = [
  { plan: 'Starter',  time: '< 24 hours', channel: 'Email only',              colour: 'var(--text-3)' },
  { plan: 'Pro',      time: '< 8 hours',  channel: 'Email + Live chat',       colour: 'var(--accent-text)' },
  { plan: 'Business', time: '< 2 hours',  channel: 'Email + Live chat + Priority', colour: '#f59e0b' },
]

const FAQS = [
  { q: 'What happens if my AI doesn\'t answer correctly?', a: 'Update your Knowledge Base with more specific information or explicit FAQs. Changes take effect on the next call. If you\'re unsure what the AI is saying, review the call summary in your dashboard Leads tab.' },
  { q: 'Can I change the AI\'s voice or name?', a: 'Yes — go to Settings in your dashboard. You can customize the AI\'s name, greeting, tone, and the questions it asks callers. Voice selection is available on Pro and Business plans.' },
  { q: 'How do I report a billing issue?', a: 'Email support@openlines.ai with your account email and a description of the issue. Billing issues are treated as priority regardless of plan.' },
  { q: 'My calendar isn\'t booking appointments — what\'s wrong?', a: 'First check that your calendar is connected under Account → Calendar. If it shows Connected, try disconnecting and reconnecting — OAuth tokens can expire. Also confirm your business hours are set correctly.' },
  { q: 'How do I cancel my subscription?', a: 'Go to Account → Subscription → Cancel plan. Your AI receptionist continues to work until the end of your billing period. We don\'t charge cancellation fees.' },
  { q: 'Can I use Open Lines for outbound calls?', a: 'Not currently. Open Lines handles inbound calls only. Outbound calling is on our roadmap.' },
  { q: 'Is my call data secure?', a: 'Call transcripts are processed to generate a structured summary, then discarded. We do not store full transcripts. Summaries are encrypted at rest in our database.' },
]

export default function SupportPage() {
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
        <div className="sec-label" style={{ marginBottom: 14 }}>Support</div>
        <h1 style={{ fontSize: 'clamp(28px, 4vw, 48px)', fontWeight: 700, letterSpacing: '-0.03em', lineHeight: 1.1, marginBottom: 16, fontFamily: 'var(--font-syne), sans-serif' }}>
          We're here to help
        </h1>
        <p style={{ fontSize: 16, color: 'var(--text-2)', maxWidth: 440, margin: '0 auto 28px', lineHeight: 1.7, fontWeight: 300 }}>
          Search the docs, email the team, or book a 20-minute walkthrough.
        </p>
        <a href="mailto:support@openlines.ai" className="btn-main" style={{ fontSize: 14, padding: '10px 22px' }}>
          Email support@openlines.ai
        </a>
      </div>

      <div className="legal-body" style={{ paddingTop: 0 }}>

        {/* Contact methods */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 48 }}>
          {[
            {
              icon: '✉',
              label: 'Email support',
              desc: 'Send us a message and we\'ll reply within 24 hours.',
              cta: 'support@openlines.ai',
              href: 'mailto:support@openlines.ai',
              external: false,
            },
            {
              icon: '💬',
              label: 'Live chat',
              desc: 'Chat with the team directly in your dashboard.',
              cta: 'Open dashboard',
              href: '/login',
              external: false,
            },
            {
              icon: '📅',
              label: 'Book a demo',
              desc: 'Get a 20-minute walkthrough with a product expert.',
              cta: 'Schedule now',
              href: '/onboarding',
              external: false,
            },
          ].map(({ icon, label, desc, cta, href, external }) => (
            <a
              key={label}
              href={href}
              {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
              style={{ display: 'block', padding: '20px 18px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 14, textDecoration: 'none' }}
            >
              <div style={{ fontSize: 24, marginBottom: 10 }}>{icon}</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{label}</div>
              <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6, marginBottom: 14 }}>{desc}</div>
              <div style={{ fontSize: 13, color: 'var(--accent-text)', fontWeight: 500 }}>{cta} →</div>
            </a>
          ))}
        </div>

        <div className="div-line" style={{ margin: '0 0 48px' }} />

        {/* Response times */}
        <section style={{ marginBottom: 48 }}>
          <div className="sec-label" style={{ marginBottom: 8 }}>Response times</div>
          <h2 style={{ fontSize: 'clamp(18px, 2.5vw, 24px)', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text)', marginBottom: 8, fontFamily: 'var(--font-syne)' }}>
            Support by plan
          </h2>
          <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.7, marginBottom: 20 }}>
            All plans include email support. Pro and Business add live chat and faster response times.
          </p>
          <div style={{ overflow: 'hidden', border: '1px solid var(--border)', borderRadius: 12 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--bg-2)' }}>
                  {['Plan', 'Response time', 'Channels'].map(h => (
                    <th key={h} style={{ padding: '10px 16px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', borderBottom: '1px solid var(--border)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {RESPONSE_TIMES.map(({ plan, time, channel, colour }, i) => (
                  <tr key={plan} style={{ borderBottom: i < RESPONSE_TIMES.length - 1 ? '1px solid var(--border)' : 'none' }}>
                    <td style={{ padding: '14px 16px', fontSize: 13, fontWeight: 600, color: colour }}>{plan}</td>
                    <td style={{ padding: '14px 16px', fontSize: 13, color: 'var(--text)', fontFamily: 'var(--font-mono)' }}>{time}</td>
                    <td style={{ padding: '14px 16px', fontSize: 13, color: 'var(--text-2)' }}>{channel}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 10, lineHeight: 1.6 }}>
            Response times are during business hours (Mon–Fri, 9am–6pm GMT). Billing issues are treated as priority on all plans.
          </p>
        </section>

        <div className="div-line" style={{ margin: '0 0 48px' }} />

        {/* Priority support */}
        <section style={{ marginBottom: 48 }}>
          <div style={{ padding: '20px 22px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 14, display: 'flex', gap: 18, alignItems: 'flex-start' }}>
            <div style={{ fontSize: 28, flexShrink: 0 }}>⚡</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 6, fontFamily: 'var(--font-syne)' }}>Priority support — Business plan</div>
              <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.7, marginBottom: 14 }}>
                Business customers get dedicated support with a 2-hour response target, a shared Slack channel with the Open Lines team, and help setting up HubSpot, Slack, and calendar integrations.
              </div>
              <Link href="/pricing" className="btn-ghost" style={{ fontSize: 13, padding: '8px 18px', display: 'inline-block' }}>
                Compare plans →
              </Link>
            </div>
          </div>
        </section>

        <div className="div-line" style={{ margin: '0 0 48px' }} />

        {/* Resources */}
        <section style={{ marginBottom: 48 }}>
          <div className="sec-label" style={{ marginBottom: 8 }}>Resources</div>
          <h2 style={{ fontSize: 'clamp(18px, 2.5vw, 24px)', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text)', marginBottom: 20, fontFamily: 'var(--font-syne)' }}>
            Useful links
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {[
              { title: 'Documentation',    href: '/docs',    desc: 'Complete setup guides for every feature.' },
              { title: 'Privacy policy',   href: '/privacy', desc: 'How we collect, store, and protect your data.' },
              { title: 'Terms of service', href: '/terms',   desc: 'Legal terms covering use of Open Lines.' },
              { title: 'Pricing',          href: '/pricing', desc: 'Compare Starter, Pro, and Business plans.' },
            ].map(({ title, href, desc }) => (
              <Link key={title} href={href} style={{ display: 'block', padding: '14px 18px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 10, textDecoration: 'none' }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{title} →</div>
                <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6 }}>{desc}</div>
              </Link>
            ))}
          </div>
        </section>

        <div className="div-line" style={{ margin: '0 0 48px' }} />

        {/* FAQ */}
        <section style={{ marginBottom: 48 }}>
          <div className="sec-label" style={{ marginBottom: 8 }}>FAQ</div>
          <h2 style={{ fontSize: 'clamp(18px, 2.5vw, 24px)', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text)', marginBottom: 20, fontFamily: 'var(--font-syne)' }}>
            Frequently asked questions
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {FAQS.map(({ q, a }) => (
              <div key={q} style={{ padding: '16px 18px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 12 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{q}</div>
                <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.7 }}>{a}</div>
              </div>
            ))}
          </div>
        </section>

        <div className="div-line" style={{ margin: '0 0 48px' }} />

        {/* CTA */}
        <div style={{ padding: '40px 32px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 18, textAlign: 'center', marginBottom: 20 }}>
          <div style={{ fontSize: 'clamp(18px, 2.5vw, 24px)', fontWeight: 700, fontFamily: 'var(--font-syne)', marginBottom: 10, letterSpacing: '-0.02em' }}>
            Can't find what you're looking for?
          </div>
          <p style={{ fontSize: 14, color: 'var(--text-2)', marginBottom: 24, lineHeight: 1.7, maxWidth: 380, margin: '0 auto 24px' }}>
            Email us directly and a human will reply — no bots, no templated responses.
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
            <a href="mailto:support@openlines.ai" className="btn-main" style={{ fontSize: 14, padding: '10px 22px' }}>Email support</a>
            <Link href="/docs" className="btn-ghost" style={{ fontSize: 14, padding: '10px 22px' }}>Browse docs</Link>
          </div>
        </div>

      </div>

      <footer style={{ borderTop: '1px solid var(--border)', padding: '28px 40px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
        <Link href="/" className="nav-logo"><LogoMark /><span className="logo-name">open lines</span></Link>
        <div style={{ display: 'flex', gap: 20, fontSize: 12, color: 'var(--text-3)' }}>
          <Link href="/privacy" style={{ color: 'inherit', textDecoration: 'none' }}>Privacy</Link>
          <Link href="/terms"   style={{ color: 'inherit', textDecoration: 'none' }}>Terms</Link>
          <Link href="/docs"    style={{ color: 'inherit', textDecoration: 'none' }}>Docs</Link>
          <a href="mailto:support@openlines.ai" style={{ color: 'inherit', textDecoration: 'none' }}>support@openlines.ai</a>
        </div>
      </footer>
    </div>
  )
}
