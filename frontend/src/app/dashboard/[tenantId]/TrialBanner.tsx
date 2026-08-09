'use client'

import { useState } from 'react'
import Link from 'next/link'
import { authedFetch } from '@/lib/api'
import { PLANS } from '@/lib/plans'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export interface TrialInfo {
  trial_active: boolean
  trial_expired: boolean
  trial_days_total: number
  trial_days_remaining: number
  trial_ends_at?: string | null
  trial_minutes_total?: number
  trial_minutes_used?: number
  trial_minutes_remaining?: number
  has_active_subscription: boolean
  line_active: boolean
  subscription_required: boolean
  /** A Stripe trial with a card on file, as opposed to the legacy card-free trial. */
  card_trial?: boolean
  /** The first charge after a trial bounced — the line is gated until it's paid. */
  payment_required?: boolean
  plan?: string | null
}

function fmtDate(iso?: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-CA', { month: 'long', day: 'numeric' })
}

/** Slim banner shown across all dashboard pages while a tenant is on a trial (or
 *  after one lapses). Hidden once they are a paying customer in good standing.
 *
 *  Card trials look like an active subscription to every other part of the app
 *  (`trialing` is in the active-status set), so this cannot key off
 *  has_active_subscription alone — doing that hid the banner from exactly the
 *  people who most need to know when their card is about to be charged. */
export function TrialBanner({ trial, tenantId }: { trial?: TrialInfo | null; tenantId: string }) {
  const [starting, setStarting] = useState(false)
  const [failed, setFailed]     = useState(false)

  if (!trial) return null
  // A settled paying customer sees nothing. Card trials and the bounced-first-charge
  // state both carry has_active_subscription, so they are excluded explicitly.
  if (trial.has_active_subscription && !trial.card_trial && !trial.payment_required) return null

  const subUrl = `/dashboard/${tenantId}/subscription`
  const planPrice = PLANS.find(p => p.id === trial.plan)?.price

  const startPlanNow = async () => {
    setStarting(true)
    setFailed(false)
    try {
      const res = await authedFetch(`${API}/billing/end-trial/${tenantId}`, { method: 'POST' })
      if (!res.ok) throw new Error()
      window.location.reload()
    } catch {
      setFailed(true)
      setStarting(false)
    }
  }

  let tone: 'info' | 'warn' | 'danger'
  let message: string
  let cta: { label: string; href?: string; onClick?: () => void }

  if (trial.payment_required) {
    // Trial ended, the card bounced, and the line is off until it's paid.
    tone = 'danger'
    message = 'Your payment didn’t go through, so your AI receptionist is paused. Update your card to bring it back online.'
    cta = { label: 'Update Card', href: subUrl }
  } else if (trial.card_trial && !trial.line_active) {
    // The 60-minute safety net fired, meaning auto-conversion didn't happen.
    // One click starts the plan they already chose and reopens the line.
    tone = 'danger'
    message = 'You’ve used all your trial minutes and your line is paused. Start your plan now to bring it straight back.'
    cta = { label: starting ? 'Starting…' : 'Start My Plan', onClick: startPlanNow }
  } else if (trial.card_trial) {
    const day = fmtDate(trial.trial_ends_at)
    const price = planPrice ? `$${planPrice} + tax` : 'your plan'
    const mins = trial.trial_minutes_total
      ? ` ${trial.trial_minutes_used ?? 0} of ${trial.trial_minutes_total} trial minutes used.`
      : ''
    if (trial.trial_days_remaining <= 1) {
      tone = 'warn'
      message = `Your free trial ends ${trial.trial_days_remaining === 0 ? 'today' : 'tomorrow'} — we’ll charge ${price}${day ? ` on ${day}` : ''}.${mins}`
    } else {
      tone = 'info'
      message = `Free trial — ${trial.trial_days_remaining} days left. We’ll charge ${price}${day ? ` on ${day}` : ''}.${mins}`
    }
    cta = { label: 'Manage Plan', href: subUrl }
  } else if (trial.trial_expired) {
    tone = 'danger'
    message = 'Your trial has ended. Subscribe now to reactivate your AI receptionist.'
    cta = { label: 'Subscribe', href: subUrl }
  } else if (trial.trial_days_remaining <= 0) {
    tone = 'warn'
    message = 'Your free trial ends today. Subscribe now to keep your phone line active.'
    cta = { label: 'Choose Plan', href: subUrl }
  } else if (trial.trial_days_remaining === 1) {
    tone = 'warn'
    message = 'Your free trial ends tomorrow. Add a plan to avoid interruption.'
    cta = { label: 'Choose Plan', href: subUrl }
  } else {
    tone = 'info'
    message = `Your free trial ends in ${trial.trial_days_remaining} days. Choose a plan to keep your AI receptionist active.`
    cta = { label: 'Choose Plan', href: subUrl }
  }

  const c = {
    info:   { bg: '#eaf2ff', border: '#bcd6ff', text: '#0b3d91' },
    warn:   { bg: '#fff4e5', border: '#ffd8a8', text: '#92400e' },
    danger: { bg: '#fdecec', border: '#f5b5b5', text: '#9b1c1c' },
  }[tone]

  const btnStyle: React.CSSProperties = {
    flexShrink: 0, fontSize: 13, fontWeight: 700, textDecoration: 'none',
    background: c.text, color: '#fff', padding: '6px 14px', borderRadius: 7,
    whiteSpace: 'nowrap', border: 'none', cursor: starting ? 'default' : 'pointer',
    opacity: starting ? 0.6 : 1,
  }

  return (
    <div
      role="status"
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 12, flexWrap: 'wrap', padding: '10px 16px',
        background: c.bg, borderBottom: `1px solid ${c.border}`, color: c.text,
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 500 }}>
        {message}
        {failed && ' Something went wrong — please try again or update your card.'}
      </span>
      {cta.href ? (
        <Link href={cta.href} style={btnStyle}>{cta.label} →</Link>
      ) : (
        <button type="button" onClick={cta.onClick} disabled={starting} style={btnStyle}>
          {cta.label} →
        </button>
      )}
    </div>
  )
}
