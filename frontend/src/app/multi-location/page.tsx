import type { Metadata } from 'next'
import Link from 'next/link'
import SiteNav from '../components/SiteNav'
import SiteFooter from '../components/SiteFooter'
import PageCta from '../components/PageCta'
import Breadcrumbs from '../components/Breadcrumbs'
import { FaqJsonLd, BreadcrumbJsonLd, ServiceJsonLd } from '../components/JsonLd'

/**
 * Multi-location booking.
 *
 * Every claim here was checked against the code before it was written, because
 * this is the page most likely to be read by someone deciding whether we can
 * handle their business — and the fastest way to lose them is a capability that
 * turns out to be aspirational. In particular:
 *
 *   * It is SQUARE APPOINTMENTS ONLY. The location-scoped availability and
 *     booking paths sit inside the square_appointments_enabled branch; Google
 *     and Outlook tenants fall through to a single calendar. The page says so
 *     rather than implying otherwise by omission.
 *
 *   * The branch is chosen by the CALLER SAYING IT. call_location defines
 *     SOURCE_PHONE ("we knew from the number dialled") but nothing sets it, so
 *     the page must not claim a branch is identified by which number rang.
 *
 *   * Moving an appointment between branches is refused, and refused out loud.
 */

const TITLE = 'AI receptionist for multi-location businesses — Open Lines'
const DESCRIPTION =
  'One phone line for every branch. Open Lines asks which location the caller '
  + 'wants, checks that branch’s real Square Appointments availability, and books '
  + 'there — with the staff and services that belong to it.'

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: '/multi-location' },
  openGraph: {
    title: 'AI receptionist for businesses with several locations',
    description: DESCRIPTION,
    url: 'https://www.openlines.ai/multi-location',
  },
}

const STEPS = [
  { n: '01', title: 'Connect your Square account',
    body: 'Your locations come across with your services and team. Switch on the ones you want taking phone bookings — a branch you have not enabled is never offered to a caller.' },
  { n: '02', title: 'The caller says which branch',
    body: 'In their own words: "the one on Patrick Street", "your Cork shop", "the city centre one". Open Lines matches that against your location names.' },
  { n: '03', title: 'It asks when it is not sure',
    body: 'If more than one branch could be what they meant, it asks by name — "Cork, Dublin or Limerick?" — rather than picking one and hoping.' },
  { n: '04', title: 'Availability and booking are scoped to that branch',
    body: 'It checks the real Square availability for that location only, offers those times, and writes the booking there.' },
]

const DETAIL = [
  { icon: '📍', title: 'Each branch keeps its own calendar',
    body: 'Availability is read per location, so a slot that is free in Dublin is never offered to someone asking for Cork.' },
  { icon: '👥', title: 'Staff belong to a branch',
    body: 'Your Square team members are scoped to the locations they work at, so a caller asking for someone by name gets that person’s real availability where they actually are.' },
  { icon: '🧾', title: 'So do services',
    body: 'If a treatment is only offered at two of your four branches, it is only bookable at those two.' },
  { icon: '🔒', title: 'A branch you have not switched on stays invisible',
    body: 'It is not offered, and it is not a clarification candidate either. Offering somewhere you cannot serve is worse than not mentioning it.' },
  { icon: '🔁', title: 'Reschedules stay at the same branch',
    body: 'A caller can move an appointment to a new time for the same service at the same location.' },
  { icon: '🙋', title: 'Moving between branches is handed to your team',
    body: 'It is deliberately not automated, and the AI will not cancel-and-rebook to imitate one. It says your team will arrange it, and takes the details.' },
]

const HONEST = [
  { title: 'It needs Square Appointments',
    body: 'Location-scoped availability and booking are built on Square’s Bookings API. If your branches run on Google Calendar or Outlook, Open Lines still answers every call and books — but into one calendar, without per-branch scoping.' },
  { title: 'The caller tells it which branch',
    body: 'It does not currently infer the branch from which number was dialled. If a caller says nothing, it asks.' },
  { title: 'Two locations is the threshold',
    body: 'With one connected location it behaves as a single-site business, which is the right answer — nobody wants to be asked which branch when there is only one.' },
]

const FAQS = [
  { q: 'Can one AI receptionist handle several locations?',
    a: 'Yes. With two or more Square Appointments locations connected and switched on, Open Lines asks the caller which branch they want, checks that branch’s live availability, and books there. Staff and services are scoped to the location they belong to.' },
  { q: 'How does it know which location the caller means?',
    a: 'The caller says it in their own words — a town, a street, a nickname for the shop — and Open Lines matches that against your location names. If more than one branch could match, it asks by name rather than guessing. It does not currently work the branch out from which phone number was dialled.' },
  { q: 'Do I need a separate phone number for each location?',
    a: 'No. One number can serve every branch, because the caller says which one they want on the call. You can still run separate numbers if you prefer — but the branch is established by asking, not by the number.' },
  { q: 'Does it work with Google Calendar or Outlook across multiple locations?',
    a: 'Not per-branch. Location-scoped availability and booking are built on Square Appointments. On Google or Outlook, Open Lines answers every call and books appointments, but into a single calendar without per-location scoping.' },
  { q: 'Can a caller ask for a specific person at a specific branch?',
    a: 'Yes. Your Square team members are scoped to the locations they work at, so asking for someone by name checks that person’s real availability at the branch in question.' },
  { q: 'What if a service is only offered at some of my locations?',
    a: 'Then it is only bookable at those. Services are scoped per location the same way staff are, so the AI will not offer a treatment at a branch that does not do it.' },
  { q: 'Can a caller move an appointment from one branch to another?',
    a: 'Not automatically, and by design. The AI can move an appointment to a new time for the same service at the same branch. For a change of location it tells the caller your team will arrange it and takes their details — it will never cancel and rebook to imitate a move.' },
  { q: 'What happens to a location I have not switched on?',
    a: 'Nothing is offered there. It is not presented as an option and it is not suggested when the AI asks which branch the caller means — offering somewhere you cannot serve is worse than not mentioning it.' },
  { q: 'How many locations can it handle?',
    a: 'There is no fixed cap. The practical limit is how well your branches are distinguishable by name — if two are easy to confuse, give them names a caller would actually use.' },
]

const card: React.CSSProperties = {
  background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '22px 22px',
}
const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 } as const

export default function MultiLocationPage() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)', overflowX: 'hidden' }}>
      <SiteNav />

      <FaqJsonLd faqs={FAQS} />
      <BreadcrumbJsonLd trail={[{ name: 'Home', path: '/' }, { name: 'Multi-location', path: '/multi-location' }]} />
      <ServiceJsonLd
        name="Multi-location AI receptionist — Open Lines"
        description={DESCRIPTION}
        path="/multi-location"
        serviceType="Multi-location appointment booking by phone"
      />

      <section className="sec" style={{ paddingBottom: 48 }}>
        <div className="wrap" style={{ maxWidth: 860 }}>
          <Breadcrumbs trail={[{ name: 'Home', path: '/' }, { name: 'Multi-location', path: '/multi-location' }]} />
          <div className="sec-label">Multi-location</div>
          <h1 style={{
            fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(30px, 4.6vw, 48px)',
            fontWeight: 700, letterSpacing: '-0.025em', lineHeight: 1.1, marginBottom: 18,
          }}>
            One phone line. Every branch.
          </h1>
          <p style={{ fontSize: 17, color: 'var(--text-2)', lineHeight: 1.7, fontWeight: 400, maxWidth: 660 }}>
            Callers do not ring the branch, they ring the business. Open Lines asks which
            location they want, checks that branch&rsquo;s real availability, and books there —
            with the staff and services that actually belong to it.
          </p>
          <p style={{ fontSize: 14.5, color: 'var(--text-3)', lineHeight: 1.65, marginTop: 14, maxWidth: 660 }}>
            Per-branch booking runs on{' '}
            <Link href="/integrations/square-appointments" style={{ color: 'var(--accent-text)', fontWeight: 600 }}>
              Square Appointments
            </Link>. On Google Calendar or Outlook, Open Lines answers every call and books —
            into one calendar, without per-branch scoping.
          </p>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0, paddingBottom: 56 }}>
        <div className="wrap" style={{ maxWidth: 860 }}>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 20 }}>
            How a call to a multi-branch business goes
          </h2>
          <div style={{ display: 'grid', gap: 14 }}>
            {STEPS.map(s => (
              <div key={s.n} style={{ ...card, display: 'flex', gap: 18, alignItems: 'flex-start' }}>
                <div style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 13, color: 'var(--accent-text)', fontWeight: 700, paddingTop: 2 }}>{s.n}</div>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{s.title}</div>
                  <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.65, margin: 0 }}>{s.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0, paddingBottom: 56 }}>
        <div className="wrap" style={{ maxWidth: 1000 }}>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 20 }}>
            What stays separate between branches
          </h2>
          <div style={grid}>
            {DETAIL.map(d => (
              <div key={d.title} style={card}>
                <div style={{ fontSize: 22, marginBottom: 10 }}>{d.icon}</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{d.title}</div>
                <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.65, margin: 0 }}>{d.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0, paddingBottom: 56 }}>
        <div className="wrap" style={{ maxWidth: 860 }}>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 8 }}>
            The limits, before you sign up
          </h2>
          <p style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.7, marginBottom: 20, maxWidth: 620 }}>
            Three things worth knowing now rather than in week two.
          </p>
          <div style={{ display: 'grid', gap: 14 }}>
            {HONEST.map(h => (
              <div key={h.title} style={card}>
                <div style={{ fontSize: 15.5, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{h.title}</div>
                <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.65, margin: 0 }}>{h.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0, paddingBottom: 56 }}>
        <div className="wrap" style={{ maxWidth: 860 }}>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 20 }}>
            Common questions
          </h2>
          <div style={{ display: 'grid', gap: 14 }}>
            {FAQS.map(f => (
              <div key={f.q} style={card}>
                <div style={{ fontSize: 15.5, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>{f.q}</div>
                <p style={{ fontSize: 14.5, color: 'var(--text-2)', lineHeight: 1.7, margin: 0 }}>{f.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <PageCta
        location="multi-location"
        heading="Answer every branch from one line."
        sub="Connect Square Appointments and let your AI receptionist route each caller to the right location — in under 10 minutes."
      />
      <SiteFooter />
    </div>
  )
}
