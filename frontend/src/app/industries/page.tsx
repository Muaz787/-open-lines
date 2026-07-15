import type { Metadata } from 'next'
import Link from 'next/link'
import SiteNav from '../components/SiteNav'
import SiteFooter from '../components/SiteFooter'
import PageCta from '../components/PageCta'

export const metadata: Metadata = {
  title: 'Industries — Open Lines AI',
  description: 'An AI phone receptionist built for local, appointment-driven businesses — real estate, dental & medical, salons, legal, home services, restaurants and more.',
  alternates: { canonical: '/industries' },
}

const INDUSTRIES = [
  { icon: '🏠', name: 'Real Estate', body: 'Answer listing enquiries, qualify buyers, and book viewings straight into your calendar — even after hours.' },
  { icon: '🦷', name: 'Dental & Medical Clinics', body: 'Book and reschedule appointments, run new-patient intake, and answer hours & insurance questions.' },
  { icon: '💇', name: 'Salons, Spas & Barbershops', body: 'Book with a specific stylist, take deposits to cut no-shows, and handle group bookings.' },
  { icon: '⚖️', name: 'Legal', body: 'Capture new-client intake, screen matters, and schedule consultations — messages routed when a lawyer is needed.' },
  { icon: '🔧', name: 'Home Services (HVAC, Plumbing)', body: 'Triage urgent vs. routine jobs, capture the details, and book the service call.' },
  { icon: '🏗️', name: 'Contractors & Builders', body: 'Qualify project leads, collect scope and budget, and book site visits or estimates.' },
  { icon: '🍽️', name: 'Restaurants', body: 'Take reservations, answer hours & menu questions, and never miss a booking during the rush.' },
  { icon: '🚗', name: 'Automotive', body: 'Dealerships, repair shops and body shops — route sales, service and collision calls, capture the vehicle, and book the right next step.' },
  { icon: '🛡️', name: 'Insurance', body: 'Brokers & agencies — take new-quote and policy intake, flag claims for priority, and book callbacks with a licensed advisor.' },
  { icon: '📦', name: 'Courier & Delivery', body: 'Never miss an order to a phone outage — capture pickup & drop-off details on the call and send them straight to dispatch, 24/7.' },
]

export default function IndustriesPage() {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)' }}>
      <SiteNav />

      <section className="sec" style={{ textAlign: 'center', paddingBottom: 40 }}>
        <div className="wrap">
          <div className="sec-label">Industries</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', maxWidth: 640, margin: '0 auto 14px' }}>
            Built for businesses that can’t miss a call.
          </h2>
          <p className="sec-sub" style={{ maxWidth: 500, margin: '0 auto' }}>
            One platform, tuned to your industry. Your AI receptionist learns how you work and books the way you book.
          </p>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0 }}>
        <div className="wrap">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
            {INDUSTRIES.map(i => (
              <div key={i.name} style={{ background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 16, padding: '22px 22px' }}>
                <div style={{ fontSize: 26, marginBottom: 10 }}>{i.icon}</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{i.name}</div>
                <p style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, margin: 0, fontWeight: 300 }}>{i.body}</p>
              </div>
            ))}
          </div>

          <p style={{ fontSize: 14, color: 'var(--text-2)', textAlign: 'center', marginTop: 28, fontWeight: 300, lineHeight: 1.7, maxWidth: 560, marginLeft: 'auto', marginRight: 'auto' }}>
            Don’t see your business? If you rely on the phone, it fits. The AI trains on your own website and documents,
            so it works for virtually any local, appointment- or enquiry-driven business.
          </p>
        </div>
      </section>

      <div className="div-line" />

      <section className="sec" style={{ textAlign: 'center' }}>
        <div className="wrap">
          <div className="sec-label">Dedicated guides</div>
          <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', marginBottom: 10 }}>See it for your business.</h2>
          <p className="sec-sub" style={{ maxWidth: 480, margin: '0 auto 28px' }}>
            Built-for-you walkthroughs of how Open Lines works in your line of work.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, justifyContent: 'center' }}>
            {[
              { href: '/salons', label: '💇 AI for Salons & Spas' },
              { href: '/barbers', label: '💈 AI for Barbershops' },
              { href: '/realtors', label: '🏠 AI for Real Estate' },
            ].map(g => (
              <Link key={g.href} href={g.href} style={{ fontSize: 14, fontWeight: 500, color: 'var(--text)', background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 999, padding: '10px 20px' }}>
                {g.label} →
              </Link>
            ))}
          </div>
        </div>
      </section>

      <PageCta location="industries_bottom" />
      <SiteFooter />
    </div>
  )
}
