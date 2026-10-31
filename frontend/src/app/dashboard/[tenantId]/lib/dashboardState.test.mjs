// Run with `npm test`.
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { presentAccount } from './accountState.ts'
import { emptyCallsCopy } from './emptyStates.ts'

const base = { plan: 'pro', has_provider_subscription: true, line_active: true, pending_activation: false }
const account = over => ({ ...base, source: 'subscription', subscription: 'active', ...over })

describe('presentAccount', () => {
  it('shows a paid subscription as active', () => {
    const v = presentAccount(account(), 'ready', 'ok')
    assert.equal(v.planLabel, 'Pro plan')
    assert.equal(v.statusLabel, 'Active')
    assert.equal(v.needsPlan, false)
  })

  it('shows a trial as a trial, not as active', () => {
    const v = presentAccount(account({ subscription: 'trialing' }), 'ready', 'ok')
    assert.equal(v.planLabel, 'Pro trial')
    assert.equal(v.statusLabel, 'Trial')
  })

  it('shows canceled and offers plans', () => {
    const v = presentAccount(account({ subscription: 'canceled' }), 'ready')
    assert.equal(v.statusLabel, 'Canceled')
    assert.equal(v.needsPlan, true)
  })

  it('never calls a manual plan a paid subscription', () => {
    const v = presentAccount(account({ source: 'manual', has_provider_subscription: false }), 'ready', 'none')
    assert.equal(v.planLabel, 'Pro (manual access)')
    assert.notEqual(v.statusLabel, 'Active')
    assert.equal(v.needsPlan, false)
    assert.match(v.billingNotice.title, /No paid subscription/)
  })

  it('describes a comped account', () => {
    const v = presentAccount(account({ source: 'complimentary', plan: null }), 'ready', 'none')
    assert.equal(v.planLabel, 'Complimentary')
    assert.equal(v.needsPlan, false)
  })

  it('offers plans when there is no subscription', () => {
    const v = presentAccount(account({ source: 'none', subscription: 'none', plan: null }), 'ready', 'none')
    assert.equal(v.planLabel, 'No active plan')
    assert.equal(v.needsPlan, true)
  })

  it('does not sell a plan to a tenant waiting on activation', () => {
    const v = presentAccount(account({ source: 'none', subscription: 'none', pending_activation: true }), 'ready')
    assert.equal(v.needsPlan, false)
  })

  it('claims nothing while loading', () => {
    const v = presentAccount(null, 'loading')
    assert.equal(v.planLabel, '')
    assert.equal(v.statusLabel, null)
    assert.equal(v.needsPlan, false)
    assert.equal(v.billingNotice, null)
  })

  it('does not treat a failed request as no plan', () => {
    const v = presentAccount(null, 'error')
    assert.equal(v.planLabel, 'Plan unavailable')
    assert.equal(v.needsPlan, false)
  })

  it('flags a subscription Stripe no longer has, and does not offer a second one', () => {
    const v = presentAccount(account(), 'ready', 'missing')
    assert.equal(v.statusLabel, 'Needs review')
    assert.equal(v.needsPlan, false)
    assert.match(v.billingNotice.title, /find your subscription/)
  })
})

describe('emptyCallsCopy', () => {
  it('names the filter, and is not first-time copy, when a quality matches nothing', () => {
    const c = emptyCallsCopy('hot', '30', 5)
    assert.equal(c.title, 'No hot calls in the last 30 days.')
    assert.equal(c.canClear, true)
    assert.doesNotMatch(c.sub, /first inbound/)
  })

  it('names the period when it has no calls', () => {
    assert.equal(emptyCallsCopy('all', '7', 0).title, 'No calls in the last 7 days.')
  })

  it('names the period, not the quality, when the period itself is empty', () => {
    assert.equal(emptyCallsCopy('hot', '7', 0).title, 'No calls in the last 7 days.')
  })

  it('keeps first-call copy for an account with no calls at all', () => {
    const c = emptyCallsCopy('all', '0', 0)
    assert.equal(c.title, 'No calls yet.')
    assert.equal(c.canClear, false)
  })
})
