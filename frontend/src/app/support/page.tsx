import Link from 'next/link'
import type { Metadata } from 'next'
import {
  Mail, MessageSquare, Zap, Clock, Shield, BookOpen,
  ArrowRight, CheckCircle2, HelpCircle, PhoneCall, Star,
} from 'lucide-react'

export const metadata: Metadata = {
  title: 'Support — Open Lines AI',
  description: 'Get help with your Open Lines AI phone receptionist. Email support, documentation, and priority assistance for paid plans.',
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
  { plan: 'Free',     color: '#9AAABB', time: '3–5 business days', channel: 'Email only' },
  { plan: 'Starter',  color: '#60A5FA', time: '1–2 business days', channel: 'Email' },
  { plan: 'Pro',      color: '#34C759', time: 'Same business day',  channel: 'Email + priority queue' },
  { plan: 'Business', color: '#A78BFA', time: 'Within 4 hours',     channel: 'Email + priority queue' },
]

const RESOURCES = [
  {
    icon: BookOpen,
    title: 'Documentation',
    body: 'Step-by-step guides for every feature — setup, calendar, HubSpot, and troubleshooting.',
    href: '/docs',
    cta: 'Browse docs',
  },
  {
    icon: PhoneCall,
    title: 'Book a demo',
    body: 'Speak with our team and we\'ll walk you through the platform and answer your questions live.',
    href: 'https://calendly.com/openlines',
    cta: 'Schedule a call',
    external: true,
  },
  {
    icon: Star,
    title: 'Upgrade your plan',
    body: 'Unlock calendar booking, HubSpot sync, and priority support by upgrading to Pro or Business.',
    href: '/pricing',
    cta: 'View plans',
  },
]

const FAQS = [
  {
    q: 'How do I get my first call set up?',
    a: 'Create your account, connect a phone number under Settings, upload your business info to the Knowledge Base, and your AI receptionist is ready. Most users are live within 30 minutes.',
  },
  {
    q: 'My AI is giving incorrect answers — what should I do?',
    a: 'Go to Knowledge Base in your dashboard and add more detail about the topic it\'s getting wrong. The more specific your entries, the more accurate the AI becomes. Changes take effect immediately.',
  },
  {
    q: 'How do I reconnect my calendar after it expires?',
    a: 'Go to Account → Calendar and click Disconnect, then reconnect your Google or Outlook account. Calendar tokens expire periodically and a fresh reconnect always fixes sync issues.',
  },
  {
    q: 'Can I change the AI\'s voice or name?',
    a: 'Yes — go to Settings → AI Configuration to update the assistant\'s name, voice style, greeting message, and personality tone.',
  },
  {
    q: 'How do I cancel or change my plan?',
    a: 'Go to Billing & Payments in your dashboard. You can upgrade, downgrade, or cancel at any time. Cancellations take effect at the end of the current billing period.',
  },
  {
    q: 'Is there a free trial?',
    a: 'Yes. New accounts get a 14-day free trial of the Starter plan with no credit card required. You can upgrade at any point during or after the trial.',
  },
]

export default function SupportPage() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>

      {/* Nav */}
      <nav>
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
            <button className="btn-nav" style={{ background: 'transparent', color: 'var(--text-2)', border: '1px solid var(--border-2)' }}>
              Sign in
            </button>
          </Link>
          <Link href="/onboarding">
            <button className="btn-nav" style={{ background: 'var(--text)', color: 'var(--bg)' }}>
              Get started
            </button>
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-32 pb-16 px-6" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="max-w-2xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium mb-6"
            style={{ background: 'var(--accent-dim)', color: 'var(--accent-text)', border: '1px solid rgba(52,199,89,0.2)' }}>
            <Shield size={12} />
            Support Centre
          </div>
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-4"
            style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.03em', lineHeight: 1.1 }}>
            How can we help?
          </h1>
          <p className="text-lg mb-8" style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>
            Our team is here to make sure your AI receptionist runs smoothly.
            Reach out and we&apos;ll get back to you fast.
          </p>
          <a href="mailto:support@openlines.ai"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
            style={{ background: 'var(--text)', color: 'var(--bg)' }}>
            <Mail size={15} />
            Email support@openlines.ai
          </a>
        </div>
      </section>

      <div className="max-w-4xl mx-auto px-6 py-16 space-y-20">

        {/* Contact Methods */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Mail size={14} style={{ color: 'var(--accent-text)' }} />
            <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--accent-text)' }}>
              Contact
            </span>
          </div>
          <h2 className="text-2xl font-bold mb-8" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            Ways to reach us
          </h2>
          <div className="grid md:grid-cols-3 gap-4">

            {/* Email */}
            <div className="p-5 rounded-xl flex flex-col" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-4"
                style={{ background: 'var(--accent-dim)' }}>
                <Mail size={16} style={{ color: 'var(--accent-text)' }} />
              </div>
              <p className="text-sm font-semibold mb-1" style={{ color: 'var(--text)' }}>Email support</p>
              <p className="text-xs leading-relaxed mb-4 flex-1" style={{ color: 'var(--text-2)' }}>
                Send us a detailed message and we&apos;ll get back to you with a fix.
              </p>
              <a href="mailto:support@openlines.ai"
                className="inline-flex items-center gap-1.5 text-xs font-medium transition-opacity hover:opacity-70"
                style={{ color: 'var(--accent-text)' }}>
                support@openlines.ai <ArrowRight size={11} />
              </a>
            </div>

            {/* Live chat */}
            <div className="p-5 rounded-xl flex flex-col relative overflow-hidden"
              style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
              <div className="absolute top-3 right-3 px-2 py-0.5 rounded-full text-xs"
                style={{ background: 'var(--bg-3)', color: 'var(--text-3)', border: '1px solid var(--border)' }}>
                Coming soon
              </div>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-4"
                style={{ background: 'var(--bg-3)' }}>
                <MessageSquare size={16} style={{ color: 'var(--text-3)' }} />
              </div>
              <p className="text-sm font-semibold mb-1" style={{ color: 'var(--text)' }}>Live chat</p>
              <p className="text-xs leading-relaxed mb-4 flex-1" style={{ color: 'var(--text-2)' }}>
                Real-time chat support directly inside your dashboard. Launching soon.
              </p>
              <span className="text-xs" style={{ color: 'var(--text-3)' }}>Available Q3 2026</span>
            </div>

            {/* Book demo */}
            <div className="p-5 rounded-xl flex flex-col" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-4"
                style={{ background: 'var(--accent-dim)' }}>
                <PhoneCall size={16} style={{ color: 'var(--accent-text)' }} />
              </div>
              <p className="text-sm font-semibold mb-1" style={{ color: 'var(--text)' }}>Book a demo call</p>
              <p className="text-xs leading-relaxed mb-4 flex-1" style={{ color: 'var(--text-2)' }}>
                Speak with our team for a live walkthrough and setup help.
              </p>
              <a href="https://calendly.com/openlines"
                target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs font-medium transition-opacity hover:opacity-70"
                style={{ color: 'var(--accent-text)' }}>
                Schedule a call <ArrowRight size={11} />
              </a>
            </div>

          </div>
        </section>

        {/* Response Times */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Clock size={14} style={{ color: 'var(--accent-text)' }} />
            <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--accent-text)' }}>
              Response Times
            </span>
          </div>
          <h2 className="text-2xl font-bold mb-2" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            When to expect a reply
          </h2>
          <p className="text-sm mb-8" style={{ color: 'var(--text-2)' }}>
            Response times depend on your plan. Paid plans receive priority handling.
          </p>
          <div className="rounded-xl overflow-hidden" style={{ border: '1px solid var(--border)' }}>
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: 'var(--bg-3)', borderBottom: '1px solid var(--border)' }}>
                  <th className="text-left px-5 py-3 text-xs font-semibold" style={{ color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Plan</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold" style={{ color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Response time</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold" style={{ color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Channels</th>
                </tr>
              </thead>
              <tbody>
                {RESPONSE_TIMES.map(({ plan, color, time, channel }, i) => (
                  <tr key={plan} style={{
                    background: 'var(--bg-2)',
                    borderBottom: i < RESPONSE_TIMES.length - 1 ? '1px solid var(--border)' : 'none',
                  }}>
                    <td className="px-5 py-3.5">
                      <span className="inline-flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
                        <span className="font-medium" style={{ color: 'var(--text)' }}>{plan}</span>
                      </span>
                    </td>
                    <td className="px-5 py-3.5" style={{ color: 'var(--text-2)' }}>{time}</td>
                    <td className="px-5 py-3.5" style={{ color: 'var(--text-2)' }}>{channel}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs mt-3" style={{ color: 'var(--text-3)' }}>
            Response times apply to business hours (Mon–Fri, 9am–6pm ET). Weekend queries are handled the next business day.
          </p>
        </section>

        {/* Priority Support */}
        <section className="p-6 rounded-2xl" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{ background: 'var(--accent-dim)' }}>
              <Zap size={18} style={{ color: 'var(--accent-text)' }} />
            </div>
            <div className="flex-1">
              <p className="text-sm font-semibold mb-1" style={{ color: 'var(--text)' }}>Priority support on Pro & Business</p>
              <p className="text-sm leading-relaxed mb-4" style={{ color: 'var(--text-2)' }}>
                Pro and Business customers receive same-day or 4-hour support, a dedicated priority queue,
                and direct escalation to our engineering team for technical issues.
              </p>
              <div className="flex flex-wrap gap-2">
                {['Same-day response', 'Priority queue', 'Dedicated onboarding', 'Direct escalation'].map(f => (
                  <span key={f} className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs"
                    style={{ background: 'var(--accent-dim)', color: 'var(--accent-text)', border: '1px solid rgba(52,199,89,0.2)' }}>
                    <CheckCircle2 size={10} />
                    {f}
                  </span>
                ))}
              </div>
            </div>
            <Link href="/pricing"
              className="flex-shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium transition-opacity hover:opacity-80 hidden md:inline-flex"
              style={{ background: 'var(--text)', color: 'var(--bg)' }}>
              Upgrade <ArrowRight size={11} />
            </Link>
          </div>
        </section>

        {/* Troubleshooting Resources */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <BookOpen size={14} style={{ color: 'var(--accent-text)' }} />
            <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--accent-text)' }}>
              Resources
            </span>
          </div>
          <h2 className="text-2xl font-bold mb-8" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            Self-serve resources
          </h2>
          <div className="grid md:grid-cols-3 gap-4">
            {RESOURCES.map(({ icon: Icon, title, body, href, cta, external }) => (
              <div key={title} className="p-5 rounded-xl flex flex-col transition-all duration-200 hover:shadow-md"
                style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-4"
                  style={{ background: 'var(--accent-dim)' }}>
                  <Icon size={16} style={{ color: 'var(--accent-text)' }} />
                </div>
                <p className="text-sm font-semibold mb-1" style={{ color: 'var(--text)' }}>{title}</p>
                <p className="text-xs leading-relaxed mb-4 flex-1" style={{ color: 'var(--text-2)' }}>{body}</p>
                {external ? (
                  <a href={href} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-xs font-medium transition-opacity hover:opacity-70"
                    style={{ color: 'var(--accent-text)' }}>
                    {cta} <ArrowRight size={11} />
                  </a>
                ) : (
                  <Link href={href}
                    className="inline-flex items-center gap-1.5 text-xs font-medium transition-opacity hover:opacity-70"
                    style={{ color: 'var(--accent-text)' }}>
                    {cta} <ArrowRight size={11} />
                  </Link>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* FAQ */}
        <section id="faq">
          <div className="flex items-center gap-2 mb-3">
            <HelpCircle size={14} style={{ color: 'var(--accent-text)' }} />
            <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--accent-text)' }}>
              FAQ
            </span>
          </div>
          <h2 className="text-2xl font-bold mb-8" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            Common questions
          </h2>
          <div className="space-y-3">
            {FAQS.map(({ q, a }) => (
              <div key={q} className="p-5 rounded-xl" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <p className="text-sm font-semibold mb-2" style={{ color: 'var(--text)' }}>{q}</p>
                <p className="text-sm leading-relaxed" style={{ color: 'var(--text-2)' }}>{a}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Demo CTA */}
        <section className="rounded-2xl p-10 text-center relative overflow-hidden"
          style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
          <div className="absolute inset-0 opacity-30 pointer-events-none"
            style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(52,199,89,0.12) 0%, transparent 70%)' }} />
          <div className="relative">
            <div className="w-12 h-12 rounded-2xl flex items-center justify-center mx-auto mb-5"
              style={{ background: 'var(--accent-dim)', border: '1px solid rgba(52,199,89,0.2)' }}>
              <PhoneCall size={20} style={{ color: 'var(--accent-text)' }} />
            </div>
            <h3 className="text-2xl font-bold mb-3" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
              Want a guided walkthrough?
            </h3>
            <p className="text-sm mb-8 max-w-md mx-auto" style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>
              Book a 20-minute demo call with our team. We&apos;ll walk you through setup, show you the AI
              in action, and answer any questions you have.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-3">
              <a href="https://calendly.com/openlines"
                target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
                style={{ background: 'var(--text)', color: 'var(--bg)' }}>
                Book a demo <ArrowRight size={14} />
              </a>
              <a href="mailto:support@openlines.ai"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
                style={{ border: '1px solid var(--border-2)', color: 'var(--text-2)' }}>
                <Mail size={14} />
                Email us instead
              </a>
            </div>
          </div>
        </section>

      </div>

      {/* Footer */}
      <footer className="border-t py-8 px-6" style={{ borderColor: 'var(--border)' }}>
        <div className="max-w-4xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <Link href="/" className="nav-logo">
            <LogoMark />
            <span className="logo-name">open lines</span>
          </Link>
          <div className="flex gap-6 text-xs" style={{ color: 'var(--text-3)' }}>
            <Link href="/privacy" className="hover:underline">Privacy</Link>
            <Link href="/terms" className="hover:underline">Terms</Link>
            <Link href="/docs" className="hover:underline">Docs</Link>
            <a href="mailto:support@openlines.ai" className="hover:underline">support@openlines.ai</a>
          </div>
        </div>
      </footer>

    </div>
  )
}
