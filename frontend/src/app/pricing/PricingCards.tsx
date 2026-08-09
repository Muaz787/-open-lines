'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { trackEvent, getUtmParams } from '@/lib/analytics'
import { PLANS } from '@/lib/plans'

const Check = () => (
  <svg width="15" height="15" viewBox="0 0 15 15" fill="none" style={{ flexShrink: 0, marginTop: 1 }}>
    <circle cx="7.5" cy="7.5" r="7.5" fill="var(--accent-dim)" />
    <path d="M4.5 7.5L6.5 9.5L10.5 5.5" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

type Interval = 'month' | 'year'

export default function PricingCards() {
  useEffect(() => {
    trackEvent('pricing_page_viewed', {
      page_path: window.location.pathname,
      referrer: document.referrer || '$direct',
      ...getUtmParams(),
    })
  }, [])

  // Each card tracks its own monthly/annual choice
  const [intervals, setIntervals] = useState<Record<string, Interval>>({})
  const iv = (name: string): Interval => intervals[name] ?? 'month'
  const setIv = (name: string, v: Interval) =>
    setIntervals(prev => ({ ...prev, [name]: v }))

  return (
    <div className="pricing-cards-wrap">
      <div className="pp-grid">
        {PLANS.map(plan => {
          const annual = iv(plan.name) === 'year'
          const monthlyEquiv = Math.round(plan.priceYear / 12)
          return (
            <div key={plan.name} className={`pp-card${plan.popular ? ' pp-popular' : ''}`}>
              <div className="pp-accent" style={{ background: plan.accent }} />
              {plan.popular && <div className="pp-badge">Most Popular</div>}

              <div className="pp-body">
                <div className="pp-name-row">
                  <span className="pp-name">{plan.name}</span>
                  <div className="pp-toggle" role="group" aria-label={`${plan.name} billing period`}>
                    <button
                      type="button"
                      className={!annual ? 'on' : ''}
                      onClick={() => setIv(plan.name, 'month')}
                    >
                      Monthly
                    </button>
                    <button
                      type="button"
                      className={annual ? 'on' : ''}
                      onClick={() => setIv(plan.name, 'year')}
                    >
                      Annual
                    </button>
                  </div>
                </div>

                <div className="pp-price">
                  <span className="pp-price-num">${annual ? monthlyEquiv : plan.price}</span>
                  <span className="pp-price-unit">/mo</span>
                </div>

                {annual && (
                  <div className="pp-price-sub">
                    ${plan.priceYear.toLocaleString()} billed yearly · <span className="pp-save">2 months free</span>
                  </div>
                )}

                <div className="pp-minutes">{plan.minutes} minutes included · {plan.note}</div>

                <Link
                  href="/onboarding"
                  style={{ display: 'block', textDecoration: 'none' }}
                  onClick={() => trackEvent('get_started_clicked', {
                    location: 'pricing',
                    plan: plan.name.toLowerCase(),
                    interval: iv(plan.name),
                  })}
                >
                  <button className={`pp-cta${plan.popular ? ' pp-cta-popular' : ''}`}>
                    Get started →
                  </button>
                </Link>

                <div className="pp-divider" />

                <div className="pp-features">
                  {plan.features.map(f => (
                    <div key={f} className="pp-feat">
                      <Check />
                      <span>{f}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <p className="pp-overage-note">
        Overage minutes are billed at $0.69/min. Calls are never cut off mid-conversation.
      </p>
    </div>
  )
}
