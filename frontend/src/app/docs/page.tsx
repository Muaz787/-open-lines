import Link from 'next/link'
import type { Metadata } from 'next'
import {
  Zap, Phone, BookOpen, Calendar, TestTube2, HelpCircle, ChevronRight,
  CheckCircle2, AlertCircle, ArrowRight, Database, Settings, Mail,
  RefreshCw, Link2, Users, Clock,
} from 'lucide-react'

export const metadata: Metadata = {
  title: 'Documentation — Open Lines AI',
  description: 'Learn how to set up your AI phone receptionist, connect calendars, sync HubSpot CRM, and configure your Open Lines account.',
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
  { icon: Users,      step: '01', title: 'Create your account',        body: 'Sign up at openlines.ai and complete your business profile. Add your business name, industry, and contact preferences.' },
  { icon: Phone,      step: '02', title: 'Connect a phone number',     body: 'Provision a local or toll-free number through our dashboard. Your AI receptionist will answer all calls made to this number.' },
  { icon: Database,   step: '03', title: 'Upload your business info',  body: 'Add your services, pricing, FAQs, and team details to the Knowledge Base. The AI uses this to answer caller questions accurately.' },
  { icon: Calendar,   step: '04', title: 'Connect your calendar',      body: 'Link Google Calendar or Microsoft Outlook. The AI checks your availability in real time and books appointments automatically.' },
  { icon: TestTube2,  step: '05', title: 'Test your AI receptionist', body: 'Call your number and speak with the AI. Adjust the tone, knowledge, and booking logic in Settings until it feels right.' },
]

const HUBSPOT_STEPS = [
  { title: 'Navigate to Integrations',     body: 'In your dashboard, go to Account → Integrations. This feature is available on Pro and Business plans.' },
  { title: 'Connect HubSpot',              body: 'Click "Connect HubSpot" and authorize Open Lines to access your HubSpot portal via OAuth.' },
  { title: 'Automatic contact sync',       body: 'After every call, Open Lines searches HubSpot for the caller\'s phone number. If no contact exists, a new one is created automatically.' },
  { title: 'AI call summaries as notes',   body: 'A structured note is added to the contact containing urgency level, appointment status, key details, and suggested next steps — no full transcript.' },
]

const FAQS = [
  {
    q: 'What happens if the AI can\'t answer a question?',
    a: 'If the caller asks something not covered in your Knowledge Base, the AI politely informs them it will pass the message along and captures their contact details for follow-up.',
  },
  {
    q: 'Can I use my existing phone number?',
    a: 'Yes — you can port your existing number to Open Lines or use call forwarding to route calls from your current number to your Open Lines line.',
  },
  {
    q: 'How does calendar booking work?',
    a: 'The AI checks your connected calendar for available slots, offers times to the caller, and creates a calendar event with the caller\'s details. Reschedule and cancellation are also handled automatically.',
  },
  {
    q: 'Is the call transcript stored?',
    a: 'Call transcripts are processed to generate a structured summary and lead record, then discarded. We do not store raw transcripts. Only the summary, urgency, and key details are retained.',
  },
  {
    q: 'What\'s the difference between plans?',
    a: 'The Starter plan covers AI calling and lead capture. Pro adds calendar booking and HubSpot sync. Business adds priority support, higher call volume, and advanced customization.',
  },
  {
    q: 'How do I change what the AI says?',
    a: 'Go to Settings in your dashboard to update your AI\'s name, greeting, tone, and the specific qualification questions it asks callers.',
  },
]

const TROUBLESHOOTING = [
  {
    icon: AlertCircle,
    title: 'AI not answering calls',
    steps: ['Verify your Twilio number is active in Settings → Phone Number', 'Check that your Vapi assistant is connected (Settings → AI Config)', 'Ensure your account is on an active plan'],
  },
  {
    icon: Calendar,
    title: 'Calendar not booking',
    steps: ['Re-connect your calendar under Account → Calendar', 'Confirm your business hours are set correctly', 'Check that the calendar token hasn\'t expired (reconnect fixes this)'],
  },
  {
    icon: Link2,
    title: 'HubSpot not syncing',
    steps: ['Go to Account → Integrations and verify HubSpot shows Connected', 'Disconnect and reconnect to refresh the OAuth token', 'Check that your HubSpot portal has contacts permissions enabled'],
  },
  {
    icon: RefreshCw,
    title: 'AI giving wrong answers',
    steps: ['Update your Knowledge Base with more detailed information', 'Add specific FAQs for topics the AI is getting wrong', 'Use the Calls page to review recent transcripts and identify gaps'],
  },
]

export default function DocsPage() {
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
        <div className="max-w-3xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium mb-6"
            style={{ background: 'var(--accent-dim)', color: 'var(--accent-text)', border: '1px solid rgba(52,199,89,0.2)' }}>
            <BookOpen size={12} />
            Documentation
          </div>
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-4"
            style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.03em', lineHeight: 1.1 }}>
            Everything you need to get started
          </h1>
          <p className="text-lg mb-8" style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>
            Set up your AI phone receptionist in minutes. Connect your calendar, sync your CRM,
            and start capturing leads around the clock.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <a href="#quickstart"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
              style={{ background: 'var(--text)', color: 'var(--bg)' }}>
              Quick start <ArrowRight size={14} />
            </a>
            <a href="#faq"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
              style={{ border: '1px solid var(--border-2)', color: 'var(--text-2)' }}>
              View FAQ
            </a>
          </div>
        </div>
      </section>

      <div className="max-w-4xl mx-auto px-6 py-16 space-y-24">

        {/* Quick Start */}
        <section id="quickstart">
          <SectionLabel icon={Zap} label="Quick Start" />
          <h2 className="text-2xl font-bold mb-2" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            Up and running in 5 steps
          </h2>
          <p className="text-sm mb-10" style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>
            Follow these steps in order to configure your AI receptionist from scratch.
          </p>
          <div className="space-y-4">
            {QUICK_STEPS.map(({ icon: Icon, step, title, body }) => (
              <div key={step}
                className="flex gap-5 p-5 rounded-xl transition-all duration-200 hover:shadow-md"
                style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <div className="flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center"
                  style={{ background: 'var(--accent-dim)' }}>
                  <Icon size={18} style={{ color: 'var(--accent-text)' }} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono" style={{ color: 'var(--text-3)' }}>{step}</span>
                    <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{title}</span>
                  </div>
                  <p className="text-sm leading-relaxed" style={{ color: 'var(--text-2)' }}>{body}</p>
                </div>
                <ChevronRight size={16} className="flex-shrink-0 mt-1" style={{ color: 'var(--text-3)' }} />
              </div>
            ))}
          </div>
        </section>

        {/* HubSpot Integration */}
        <section id="hubspot">
          <SectionLabel icon={Link2} label="HubSpot Integration" />
          <h2 className="text-2xl font-bold mb-2" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            How HubSpot CRM sync works
          </h2>
          <p className="text-sm mb-8" style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>
            Open Lines automatically creates and updates contacts in HubSpot after every call — no manual data entry needed.
            Available on Pro and Business plans.
          </p>

          <div className="p-5 rounded-xl mb-8"
            style={{ background: 'var(--accent-dim)', border: '1px solid rgba(52,199,89,0.2)' }}>
            <div className="flex items-start gap-3">
              <CheckCircle2 size={16} className="flex-shrink-0 mt-0.5" style={{ color: 'var(--accent-text)' }} />
              <p className="text-sm" style={{ color: 'var(--text)', lineHeight: 1.7 }}>
                <strong>Privacy by default:</strong> Open Lines never sends full call transcripts to HubSpot.
                Only structured summaries — urgency, intent, and next steps — are synced.
              </p>
            </div>
          </div>

          <div className="grid gap-4">
            {HUBSPOT_STEPS.map(({ title, body }, i) => (
              <div key={i} className="flex gap-4 p-4 rounded-xl"
                style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <div className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: 'var(--text)', color: 'var(--bg)' }}>
                  {i + 1}
                </div>
                <div>
                  <p className="text-sm font-semibold mb-0.5" style={{ color: 'var(--text)' }}>{title}</p>
                  <p className="text-sm" style={{ color: 'var(--text-2)', lineHeight: 1.6 }}>{body}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 p-4 rounded-xl"
            style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
            <p className="text-xs font-semibold mb-2" style={{ color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              What gets synced to each contact note
            </p>
            <div className="grid grid-cols-2 gap-2">
              {['Call date & time', 'Caller phone number', 'Urgency (Hot / Warm / Cold)', 'Appointment booked (Yes / No)', '2-sentence AI summary', 'Suggested next step', 'Key qualification details'].map(item => (
                <div key={item} className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-2)' }}>
                  <CheckCircle2 size={12} style={{ color: 'var(--accent-text)', flexShrink: 0 }} />
                  {item}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Google Calendar */}
        <section id="calendar">
          <SectionLabel icon={Calendar} label="Calendar" />
          <h2 className="text-2xl font-bold mb-2" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            Connecting Google Calendar or Outlook
          </h2>
          <p className="text-sm mb-8" style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>
            Once connected, your AI receptionist checks your real-time availability and books appointments
            directly into your calendar — no double bookings, no missed slots.
          </p>
          <div className="grid md:grid-cols-2 gap-4 mb-6">
            {[
              { name: 'Google Calendar', steps: ['Go to Account → Calendar', 'Click "Connect Google Calendar"', 'Sign in and grant access', 'Set your business hours and appointment duration'] },
              { name: 'Microsoft Outlook', steps: ['Go to Account → Calendar', 'Click "Connect Outlook"', 'Sign in with your Microsoft account', 'Set your availability preferences'] },
            ].map(({ name, steps }) => (
              <div key={name} className="p-5 rounded-xl" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <p className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>{name}</p>
                <ol className="space-y-2">
                  {steps.map((s, i) => (
                    <li key={i} className="flex gap-2 text-sm" style={{ color: 'var(--text-2)' }}>
                      <span className="flex-shrink-0 font-mono text-xs mt-0.5" style={{ color: 'var(--text-3)' }}>{i + 1}.</span>
                      {s}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
          <div className="p-4 rounded-xl" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
            <p className="text-xs font-semibold mb-2" style={{ color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Calendar settings you can configure</p>
            <div className="grid grid-cols-2 gap-1.5">
              {['Appointment duration', 'Business hours', 'Buffer time between appointments', 'Days available for booking', 'Break / lunch windows', 'Timezone'].map(s => (
                <div key={s} className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-2)' }}>
                  <Settings size={11} style={{ color: 'var(--text-3)', flexShrink: 0 }} />
                  {s}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Knowledge Base */}
        <section id="knowledge-base">
          <SectionLabel icon={Database} label="Knowledge Base" />
          <h2 className="text-2xl font-bold mb-2" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            Uploading your business knowledge
          </h2>
          <p className="text-sm mb-8" style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>
            The Knowledge Base is the source of truth for your AI. The more detail you provide,
            the more accurately it answers caller questions.
          </p>
          <div className="space-y-3">
            {[
              { title: 'Services & pricing',     body: 'List every service you offer with pricing ranges. The AI will quote these to callers and use them to qualify intent.' },
              { title: 'Team & availability',    body: 'Add staff names, roles, and specialties. The AI can route callers to the right person or book with the right team member.' },
              { title: 'FAQs',                   body: 'Write out your most common caller questions and ideal answers. The AI treats these as ground truth.' },
              { title: 'Location & hours',       body: 'Add your address, parking info, and opening hours so the AI answers location questions without guessing.' },
              { title: 'Policies',               body: 'Cancellation policy, refund terms, and any other business rules the AI should communicate clearly.' },
            ].map(({ title, body }) => (
              <div key={title} className="p-4 rounded-xl transition-all duration-200 hover:shadow-md"
                style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <p className="text-sm font-semibold mb-1" style={{ color: 'var(--text)' }}>{title}</p>
                <p className="text-sm leading-relaxed" style={{ color: 'var(--text-2)' }}>{body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Troubleshooting */}
        <section id="troubleshooting">
          <SectionLabel icon={AlertCircle} label="Troubleshooting" />
          <h2 className="text-2xl font-bold mb-2" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            Common issues & fixes
          </h2>
          <p className="text-sm mb-8" style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>
            Most issues resolve with a reconnect or a Knowledge Base update. Here are the most frequent ones.
          </p>
          <div className="grid md:grid-cols-2 gap-4">
            {TROUBLESHOOTING.map(({ icon: Icon, title, steps }) => (
              <div key={title} className="p-5 rounded-xl" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <div className="flex items-center gap-2 mb-3">
                  <Icon size={15} style={{ color: 'var(--accent-text)' }} />
                  <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{title}</p>
                </div>
                <ol className="space-y-1.5">
                  {steps.map((s, i) => (
                    <li key={i} className="flex gap-2 text-sm" style={{ color: 'var(--text-2)' }}>
                      <span className="flex-shrink-0 font-mono text-xs mt-0.5" style={{ color: 'var(--text-3)' }}>{i + 1}.</span>
                      {s}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </section>

        {/* FAQ */}
        <section id="faq">
          <SectionLabel icon={HelpCircle} label="FAQ" />
          <h2 className="text-2xl font-bold mb-2" style={{ fontFamily: 'var(--font-syne)', letterSpacing: '-0.02em' }}>
            Frequently asked questions
          </h2>
          <p className="text-sm mb-8" style={{ color: 'var(--text-2)' }}>
            Can&apos;t find what you&apos;re looking for?{' '}
            <Link href="/support" style={{ color: 'var(--accent-text)' }}>Contact support →</Link>
          </p>
          <div className="space-y-3">
            {FAQS.map(({ q, a }) => (
              <div key={q} className="p-5 rounded-xl" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <p className="text-sm font-semibold mb-2" style={{ color: 'var(--text)' }}>{q}</p>
                <p className="text-sm leading-relaxed" style={{ color: 'var(--text-2)' }}>{a}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Support CTA */}
        <section className="rounded-2xl p-8 text-center"
          style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
          <div className="w-10 h-10 rounded-full flex items-center justify-center mx-auto mb-4"
            style={{ background: 'var(--accent-dim)' }}>
            <Mail size={18} style={{ color: 'var(--accent-text)' }} />
          </div>
          <h3 className="text-xl font-bold mb-2" style={{ fontFamily: 'var(--font-syne)' }}>
            Still need help?
          </h3>
          <p className="text-sm mb-6" style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>
            Our support team is here for you. Reach out and we&apos;ll get back to you within one business day.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Link href="/support"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
              style={{ background: 'var(--text)', color: 'var(--bg)' }}>
              Visit support centre <ArrowRight size={14} />
            </Link>
            <a href="mailto:support@openlines.ai"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
              style={{ border: '1px solid var(--border-2)', color: 'var(--text-2)' }}>
              support@openlines.ai
            </a>
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
            <Link href="/support" className="hover:underline">Support</Link>
            <a href="mailto:support@openlines.ai" className="hover:underline">support@openlines.ai</a>
          </div>
        </div>
      </footer>

    </div>
  )
}

function SectionLabel({ icon: Icon, label }: { icon: React.ElementType; label: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon size={14} style={{ color: 'var(--accent-text)' }} />
      <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--accent-text)' }}>
        {label}
      </span>
    </div>
  )
}
