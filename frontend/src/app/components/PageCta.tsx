'use client'

import Link from 'next/link'
import { trackEvent, getUtmParams } from '@/lib/analytics'

export default function PageCta({
  heading = 'Your line is waiting.',
  sub = 'Set up your AI receptionist in under 10 minutes. No engineers needed.',
  location,
}: { heading?: string; sub?: string; location: string }) {
  return (
    <div style={{ background: 'var(--bg-2)', borderTop: '1px solid var(--border)' }}>
      <div className="pricing-cta-inner">
        <h2 style={{ marginBottom: 16 }}>{heading}</h2>
        <p style={{ fontSize: 16, color: 'var(--text-2)', marginBottom: 36, lineHeight: 1.7, fontWeight: 300 }}>
          {sub}
        </p>
        <div className="pricing-cta-btns">
          <Link href="/onboarding" onClick={() => trackEvent('get_started_clicked', { location })}>
            <button className="btn-main">Start for free →</button>
          </Link>
          <a
            href="https://calendly.com/open-lines/demo"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackEvent('demo_cta_clicked', { location, ...getUtmParams() })}
          >
            <button className="btn-ghost">Book a demo</button>
          </a>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 20 }}>
          No credit card required to explore.
        </p>
      </div>
    </div>
  )
}
