import type { Metadata } from 'next'
import SiteNav from '../components/SiteNav'
import SiteFooter from '../components/SiteFooter'
import PageCta from '../components/PageCta'

export const metadata: Metadata = {
  title: 'How it works — Open Lines AI',
  description: 'Go live with an AI phone receptionist in under 10 minutes. Enter your website, get a dedicated number, and start answering every call — no hardware, no engineers.',
}

const STEPS = [
  { n: '01', title: 'Enter your website', body: 'The AI reads your site and learns your business — services, hours, pricing and FAQs — automatically.' },
  { n: '02', title: 'Review & fine-tune', body: 'Confirm what it learned, name your receptionist, set your hours, and upload any documents you want it to know.' },
  { n: '03', title: 'Get your number', body: 'A dedicated business phone line is provisioned instantly, in your own area code.' },
  { n: '04', title: 'Go live', body: 'Forward your calls (or use the new number) and your receptionist starts answering 24/7.' },
]

const ON_CALL = [
  { icon: '📞', title: 'Answers instantly, 24/7', body: 'Every call is picked up — day, night, weekends, holidays, or when your line is busy.' },
  { icon: '👋', title: 'Recognises returning callers', body: 'Greets them by name and picks up where they left off.' },
  { icon: '📋', title: 'Qualifies the lead', body: 'Captures name, reason for calling, urgency and the details you care about.' },
  { icon: '💬', title: 'Answers questions', body: 'From your website and uploaded documents — hours, services, pricing, policies.' },
  { icon: '📅', title: 'Books the appointment', body: 'Straight into your Google, Outlook or Square calendar — with a specific team member if asked.' },
  { icon: '💳', title: 'Takes a deposit', body: 'Sends a secure Stripe or Square payment link by text to cut no-shows (Pro & Business).' },
]

const AFTER = [
  { icon: '✉️', title: 'Summary to your inbox', body: 'After every call: caller name, intent, urgency and a suggested next step.' },
  { icon: '📱', title: 'SMS & WhatsApp alerts', body: 'Optional real-time alerts to your mobile, plus a text confirmation to the caller.' },
  { icon: '📊', title: 'Dashboard & AI insights', body: 'Full transcripts, AI call summaries, and operations insights — see what callers want and what you’re missing.' },
]

function Card({ icon, title, body }: { icon?: string; title: string; body: string }) {
  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '22px 22px' }}>
      {icon && <div style={{ fontSize: 24, marginBottom: 10 }}>{icon}</div>}
      <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{title}</div>
      <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{body}</p>
    </div>
  )
}

const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 } as const

export default function HowItWorksPage() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>
      <SiteNav />

      <section className="sec" style={{ textAlign: 'center', paddingBottom: 40 }}>
        <div className="wrap">
          <div className="sec-label">How it works</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', maxWidth: 620, margin: '0 auto 14px' }}>
            Live in under 10 minutes.
          </h2>
          <p className="sec-sub" style={{ maxWidth: 480, margin: '0 auto' }}>
            No hardware, no engineers, no contracts. Answer a few questions and your AI receptionist is ready to take calls.
          </p>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0 }}>
        <div className="wrap">
          <div style={grid}>
            {STEPS.map(s => (
              <div key={s.n} style={{ background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '24px 22px' }}>
                <div style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 28, fontWeight: 700, color: 'var(--accent-text)', marginBottom: 10 }}>{s.n}</div>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{s.title}</div>
                <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="div-line" />

      <section className="sec">
        <div className="wrap">
          <div className="sec-label">On every call</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 28 }}>It handles the whole conversation.</h2>
          <div style={grid}>
            {ON_CALL.map(c => <Card key={c.title} {...c} />)}
          </div>
        </div>
      </section>

      <div className="div-line" />

      <section className="sec">
        <div className="wrap">
          <div className="sec-label">After the call</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 28 }}>Nothing slips through.</h2>
          <div style={grid}>
            {AFTER.map(c => <Card key={c.title} {...c} />)}
          </div>
        </div>
      </section>

      <PageCta location="how_it_works_bottom" />
      <SiteFooter />
    </div>
  )
}
