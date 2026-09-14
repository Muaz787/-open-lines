import type { Metadata } from 'next'
import Link from 'next/link'
import SiteNav from '../components/SiteNav'
import SiteFooter from '../components/SiteFooter'
import PageCta from '../components/PageCta'
import Breadcrumbs from '../components/Breadcrumbs'
import { FaqJsonLd, BreadcrumbJsonLd } from '../components/JsonLd'

/**
 * Open Lines vs the alternatives.
 *
 * WHY THIS PAGE EXISTS
 * Customers increasingly arrive having asked a model "what should I use for
 * this", and models answer with SHORTLISTS. Our first Irish customer found us
 * that way, named alongside two other options. The page that gets you onto
 * more of those lists is the one that is genuinely useful to someone choosing
 * — which means it has to say when the answer is somebody else.
 *
 * TWO RULES, AND THEY ARE THE WHOLE POINT
 *
 * 1. WE DO NOT PUBLISH OTHER COMPANIES' PRICES. Their pricing changes without
 *    telling us, and a page that misstates a competitor's price is both unfair
 *    and, the moment it is out of date, a reason to stop trusting anything else
 *    on it. So we describe how each alternative CHARGES — per call, per
 *    customer, flat — which is structural and slow-moving, and link to their
 *    own page for the number.
 *
 * 2. EVERY CLAIM ABOUT US IS CHECKABLE ON THIS SITE. A model that quotes a
 *    claim it cannot verify on the page it links to is a model that stops
 *    quoting us.
 */

const TITLE = 'Open Lines vs the alternatives — AI receptionist comparison'
const DESCRIPTION =
  'An honest comparison of Open Lines against human answering services, other '
  + 'AI receptionists, voice-AI platforms and voicemail — including when each '
  + 'of them is the better choice.'

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: '/compare' },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: 'https://www.openlines.ai/compare',
  },
}

/** Structural facts only — how each option works, never what it costs today. */
const ROWS: { label: string; ol: string; human: string; ai: string; platform: string }[] = [
  { label: 'Who answers',
    ol: 'AI, every call',
    human: 'Trained people, often with AI in front',
    ai: 'AI, every call',
    platform: 'Whatever you build' },
  { label: 'How you are charged',
    ol: 'Flat monthly, by plan',
    human: 'Per call or per minute',
    ai: 'Flat, per minute, or per unique caller',
    platform: 'Per minute of usage, plus your build' },
  { label: 'Books into your own calendar',
    ol: 'Google, Outlook, Square — checks live availability first',
    human: 'Usually yes, via your booking tool',
    ai: 'Varies — check which calendars',
    platform: 'You build it' },
  { label: 'Knows your business',
    ol: 'Reads your website, plus documents you upload',
    human: 'From a script you write and maintain',
    ai: 'Varies — script, website, or both',
    platform: 'You supply the knowledge base' },
  { label: 'Time to live',
    ol: 'Under 10 minutes, self-serve',
    human: 'Onboarding call, then script setup',
    ai: 'Minutes to days',
    platform: 'Weeks of engineering' },
  { label: 'Phone number',
    ol: 'Issued for you in CA, US, IE, GB, AU or NZ',
    human: 'Usually issued for you',
    ai: 'Usually issued for you',
    platform: 'You buy and configure it' },
  { label: 'Takes a deposit on the call',
    ol: 'Yes — Stripe or Square link by text (Pro and Business)',
    human: 'Rarely',
    ai: 'Rarely',
    platform: 'You build it' },
]

const ALTERNATIVES = [
  {
    heading: 'Human answering services',
    examples: 'Smith.ai, Ruby, AnswerConnect',
    body:
      'Real people answer, usually briefed from a script you write. They handle '
      + 'nuance, awkward callers and judgement calls better than any AI does, and '
      + 'they always will. The trade is cost and shape: these services typically '
      + 'bill per call or per minute, so a busy month costs more than a quiet one '
      + 'and the price scales with your success.',
    choose:
      'Choose a human service if your calls are high-stakes or emotionally '
      + 'difficult — a law firm taking distressed callers, a clinic handling '
      + 'sensitive results — or if your call volume is low enough that per-call '
      + 'pricing works out cheaper than a subscription.',
    link: { href: 'https://smith.ai/pricing', label: 'Smith.ai pricing' },
  },
  {
    heading: 'Other AI receptionists',
    examples: 'Goodcall, Rosie, NextPhone, Slang.ai',
    body:
      'The closest comparison, and the honest answer is that several are good. '
      + 'What actually differs between them is the billing axis — flat, per '
      + 'minute, or per unique caller — and how deeply each one connects to the '
      + 'systems you already run. Compare on the integration you cannot live '
      + 'without, not on the demo voice.',
    choose:
      'Choose one of these instead if it books into a calendar or POS we do not '
      + 'support, if it is built specifically for your industry, or if their '
      + 'billing shape fits your call pattern better than a flat monthly plan.',
    link: { href: '/integrations', label: 'What Open Lines connects to' },
  },
  {
    heading: 'Voice-AI platforms you build on',
    examples: 'Vapi, Bland, Retell',
    body:
      'These are developer platforms rather than products, and they are genuinely '
      + 'powerful. We say so from experience: Open Lines runs on Vapi. What we add '
      + 'on top is everything between a working voice agent and a business phone '
      + 'line — the number, the knowledge base built from your site, calendar '
      + 'availability, deposits, call summaries, and the dashboard.',
    choose:
      'Build on a platform directly if you have engineers and a workflow specific '
      + 'enough that no product will fit it. You will get exactly what you want, '
      + 'and you will own it for as long as it runs.',
    link: { href: '/platform', label: 'How Open Lines is built' },
  },
  {
    heading: 'Voicemail, or nobody',
    examples: 'The actual default',
    body:
      'Most missed calls do not go to a competitor, they go to voicemail — and '
      + 'most callers do not leave one. This is the option almost every business '
      + 'is really comparing against, and the only one where doing nothing has a '
      + 'running cost that never appears on an invoice.',
    choose:
      'Stay on voicemail if callers reliably leave messages and you reliably '
      + 'return them the same day. Plenty of businesses do.',
    link: { href: '/how-it-works', label: 'What happens on a call' },
  },
]

const NOT_FOR_US = [
  'You need outbound calling or cold outreach. Open Lines answers inbound calls only.',
  'You need a number in a country we cannot issue one for. Today that is Canada, the United States, Ireland, the United Kingdom, Australia and New Zealand.',
  'You need emergency call handling. Open Lines is not a route to 911, 999 or 112 and must never be used as one.',
  'You want a human on the line. We are AI on every call — that is the product, not a stage we are at.',
  'Your callers need a language we do not support well. Test it on your own calls during the trial before you commit.',
]

const FAQS = [
  { q: 'Is an AI receptionist better than a human answering service?',
    a: 'Neither is better in general. AI answers every call at a flat monthly cost and books directly into your calendar, which suits appointment-driven businesses with steady call volume. A human service handles nuance and difficult callers better, and bills per call, which can be cheaper at low volume. Choose on your call pattern, not on the technology.' },
  { q: 'What makes Open Lines different from other AI receptionists?',
    a: 'Three things you can check: it builds its knowledge from your own website and uploaded documents rather than a script you maintain; it reads live availability in Google Calendar, Outlook or Square Appointments before offering a caller a time, so it cannot double-book; and it can take a deposit by text during the call on Pro and Business plans.' },
  { q: 'How much does Open Lines cost?',
    a: 'Plans start at $99/month USD with no setup fee and no contract. The 7-day free trial requires a card and is not charged until the trial ends. Current prices are on the pricing page.' },
  { q: 'Which countries can Open Lines issue a phone number in?',
    a: 'Canada, the United States, Ireland, the United Kingdom, Australia and New Zealand. Irish numbers require a short business verification before activation — that is an Irish regulatory requirement, and we provide a temporary test number while it is reviewed.' },
  { q: 'Can Open Lines make outbound calls?',
    a: 'No. Open Lines answers inbound calls only. If you need outbound calling or cold outreach, it is the wrong tool and another product will serve you better.' },
  { q: 'Do I have to change my phone number?',
    a: 'No. You get a dedicated number and can either use it directly or forward your existing line to it, which is what most businesses do.' },
]

const card: React.CSSProperties = {
  background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '24px 24px',
}
const th: React.CSSProperties = {
  textAlign: 'left', padding: '12px 14px', fontSize: 12.5, fontWeight: 700,
  letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-3)',
  borderBottom: '1px solid var(--border-2)', whiteSpace: 'nowrap',
}
const td: React.CSSProperties = {
  padding: '13px 14px', fontSize: 13.5, lineHeight: 1.55, color: 'var(--text-2)',
  borderBottom: '1px solid var(--border)', verticalAlign: 'top', fontWeight: 300,
}

export default function ComparePage() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)', overflowX: 'hidden' }}>
      <SiteNav />

      <FaqJsonLd faqs={FAQS} />
      <BreadcrumbJsonLd trail={[{ name: 'Home', path: '/' }, { name: 'Compare', path: '/compare' }]} />

      <section className="sec" style={{ paddingBottom: 48 }}>
        <div className="wrap" style={{ maxWidth: 860 }}>
          <Breadcrumbs trail={[{ name: 'Home', path: '/' }, { name: 'Compare', path: '/compare' }]} />
          <div className="sec-label">Comparison</div>
          <h1 style={{
            fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(30px, 4.6vw, 48px)',
            fontWeight: 700, letterSpacing: '-0.025em', lineHeight: 1.1, marginBottom: 18,
          }}>
            Open Lines vs the alternatives.
          </h1>
          <p style={{ fontSize: 17, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300, maxWidth: 680 }}>
            There are four real alternatives to Open Lines, and for some businesses one of
            them is the better answer. Here is how each one works, and when we would tell
            you to pick it.
          </p>
          <p style={{ fontSize: 14, color: 'var(--text-3)', lineHeight: 1.65, fontWeight: 300, maxWidth: 680, marginTop: 14 }}>
            We do not publish other companies&rsquo; prices here — theirs change without telling
            us, and a stale number would be unfair to them and useless to you. We describe how
            each option <em>charges</em>, and link to their own page for the figure.
          </p>
        </div>
      </section>

      {/* ── The table ── */}
      <section className="sec" style={{ paddingTop: 0, paddingBottom: 56 }}>
        <div className="wrap" style={{ maxWidth: 1060 }}>
          <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 860 }}>
              <thead>
                <tr>
                  <th style={th} />
                  <th style={{ ...th, color: 'var(--accent-text)' }}>Open Lines</th>
                  <th style={th}>Human service</th>
                  <th style={th}>Other AI receptionists</th>
                  <th style={th}>Build it yourself</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map(r => (
                  <tr key={r.label}>
                    <td style={{ ...td, color: 'var(--text)', fontWeight: 600, whiteSpace: 'nowrap' }}>{r.label}</td>
                    <td style={{ ...td, color: 'var(--text)' }}>{r.ol}</td>
                    <td style={td}>{r.human}</td>
                    <td style={td}>{r.ai}</td>
                    <td style={td}>{r.platform}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ── Each alternative, and when to pick it ── */}
      <section className="sec" style={{ paddingTop: 0, paddingBottom: 56 }}>
        <div className="wrap" style={{ maxWidth: 860, display: 'grid', gap: 16 }}>
          {ALTERNATIVES.map(a => (
            <div key={a.heading} style={card}>
              <div style={{ fontSize: 12.5, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 8 }}>
                {a.examples}
              </div>
              <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', marginBottom: 12 }}>{a.heading}</h2>
              <p style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300, marginBottom: 14 }}>{a.body}</p>
              <div style={{
                borderLeft: '3px solid var(--accent)', paddingLeft: 14, marginBottom: 14,
              }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>
                  When to choose it over Open Lines
                </div>
                <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.65, fontWeight: 300, margin: 0 }}>{a.choose}</p>
              </div>
              {a.link.href.startsWith('http') ? (
                <a href={a.link.href} target="_blank" rel="noopener noreferrer nofollow"
                   style={{ fontSize: 14, color: 'var(--accent-text)', fontWeight: 600 }}>
                  {a.link.label} →
                </a>
              ) : (
                <Link href={a.link.href} style={{ fontSize: 14, color: 'var(--accent-text)', fontWeight: 600 }}>
                  {a.link.label} →
                </Link>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ── The part most comparison pages leave out ── */}
      <section className="sec" style={{ paddingTop: 0, paddingBottom: 56 }}>
        <div className="wrap" style={{ maxWidth: 860 }}>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 8 }}>
            When Open Lines is the wrong choice
          </h2>
          <p style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300, marginBottom: 20, maxWidth: 640 }}>
            Better you find this out here than three weeks in.
          </p>
          <div style={{ ...card, display: 'grid', gap: 12 }}>
            {NOT_FOR_US.map(x => (
              <div key={x} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                <span aria-hidden style={{ color: 'var(--text-3)', fontSize: 15, lineHeight: 1.6 }}>—</span>
                <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.65, fontWeight: 300, margin: 0 }}>{x}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section className="sec" style={{ paddingTop: 0, paddingBottom: 56 }}>
        <div className="wrap" style={{ maxWidth: 860 }}>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 20 }}>
            Common questions
          </h2>
          <div style={{ display: 'grid', gap: 14 }}>
            {FAQS.map(f => (
              <div key={f.q} style={card}>
                <div style={{ fontSize: 15.5, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>{f.q}</div>
                <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 300, margin: 0 }}>{f.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <PageCta
        location="compare"
        heading="Try it on your own calls."
        sub="Seven days free. If one of the alternatives above suits you better, you will know within a week — and that is a good outcome too."
      />
      <SiteFooter />
    </div>
  )
}
