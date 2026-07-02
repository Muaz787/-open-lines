'use client'

import { trackEvent, getUtmParams } from '@/lib/analytics'

// Client wrapper so the pricing page (a server component) can track demo clicks.
export default function BookDemoButton() {
  return (
    <a
      href="https://calendly.com/open-lines/demo"
      target="_blank"
      rel="noopener noreferrer"
      onClick={() => trackEvent('demo_cta_clicked', { location: 'pricing_bottom', ...getUtmParams() })}
    >
      <button className="btn-ghost">Book a demo</button>
    </a>
  )
}
