'use client'

import Link from 'next/link'

export interface TrialInfo {
  trial_active: boolean
  trial_expired: boolean
  trial_days_total: number
  trial_days_remaining: number
  trial_ends_at?: string | null
  trial_minutes_remaining?: number
  has_active_subscription: boolean
  line_active: boolean
  subscription_required: boolean
}

/** Slim banner shown across all dashboard pages while a tenant is on the free
 *  trial (or after it expires). Hidden entirely once they have a subscription. */
export function TrialBanner({ trial, tenantId }: { trial?: TrialInfo | null; tenantId: string }) {
  if (!trial || trial.has_active_subscription) return null

  const subUrl = `/dashboard/${tenantId}/subscription`

  let tone: 'info' | 'warn' | 'danger'
  let message: string
  let cta = 'Choose Plan'

  if (trial.trial_expired) {
    tone = 'danger'
    message = 'Your trial has ended. Subscribe now to reactivate your AI receptionist.'
    cta = 'Subscribe'
  } else if (trial.trial_days_remaining <= 0) {
    tone = 'warn'
    message = 'Your free trial ends today. Subscribe now to keep your phone line active.'
  } else if (trial.trial_days_remaining === 1) {
    tone = 'warn'
    message = 'Your free trial ends tomorrow. Add a plan to avoid interruption.'
  } else {
    tone = 'info'
    message = `Your free trial ends in ${trial.trial_days_remaining} days. Choose a plan to keep your AI receptionist active.`
  }

  const c = {
    info:   { bg: '#eaf2ff', border: '#bcd6ff', text: '#0b3d91' },
    warn:   { bg: '#fff4e5', border: '#ffd8a8', text: '#92400e' },
    danger: { bg: '#fdecec', border: '#f5b5b5', text: '#9b1c1c' },
  }[tone]

  return (
    <div
      role="status"
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 12, flexWrap: 'wrap', padding: '10px 16px',
        background: c.bg, borderBottom: `1px solid ${c.border}`, color: c.text,
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 500 }}>{message}</span>
      <Link
        href={subUrl}
        style={{
          flexShrink: 0, fontSize: 13, fontWeight: 700, textDecoration: 'none',
          background: c.text, color: '#fff', padding: '6px 14px', borderRadius: 7, whiteSpace: 'nowrap',
        }}
      >
        {cta} →
      </Link>
    </div>
  )
}
