// Run with `npm test`.
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { presentAccount } from './accountState.ts'
import { emptyCallsCopy } from './emptyStates.ts'

const base = { plan: 'pro', feature_plan: 'pro', phone_line: 'on', has_provider_subscription: true, line_active: true, pending_activation: false }
const account = over => ({ ...base, source: 'subscription', subscription: 'active', ...over })

describe('presentAccount', () => {
  it('shows a paid subscription as active once Stripe confirms it', () => {
    const v = presentAccount(account(), 'ready', 'ok')
    assert.equal(v.planLabel, 'Pro plan')
    assert.equal(v.subscription.label, 'Active')
    assert.equal(v.needsPlan, false)
    assert.equal(v.canChoosePlan, true)
  })

  it('never says Active before Stripe has answered', () => {
    const v = presentAccount(account(), 'ready', undefined)
    assert.equal(v.subscription.label, 'Checking…')
    assert.equal(v.canChoosePlan, false)
  })

  it('shows a trial as a trial, not as active', () => {
    const v = presentAccount(account({ subscription: 'trialing' }), 'ready', 'ok')
    assert.equal(v.planLabel, 'Pro trial')
    assert.equal(v.subscription.label, 'Trial')
  })

  it('shows canceled and offers plans', () => {
    const v = presentAccount(account({ subscription: 'canceled' }), 'ready')
    assert.equal(v.subscription.label, 'Canceled')
    assert.equal(v.needsPlan, true)
  })

  it('never calls a manual plan a paid subscription', () => {
    const v = presentAccount(account({ source: 'manual', has_provider_subscription: false }), 'ready', 'none')
    assert.equal(v.planLabel, 'Pro (manual access)')
    assert.notEqual(v.subscription.label, 'Active')
    assert.equal(v.needsPlan, false)
    assert.match(v.billingNotice.title, /No paid subscription/)
  })

  it('offers plans when there is no subscription', () => {
    const v = presentAccount(account({ source: 'none', subscription: 'none', plan: null, feature_plan: null }), 'ready', 'none')
    assert.equal(v.planLabel, 'No active plan')
    assert.equal(v.needsPlan, true)
    assert.equal(v.canChoosePlan, true)
  })

  it('does not sell a plan to a tenant waiting on activation', () => {
    const v = presentAccount(account({ source: 'none', subscription: 'none', pending_activation: true }), 'ready')
    assert.equal(v.needsPlan, false)
    assert.equal(v.canChoosePlan, false)
  })

  it('claims nothing while loading', () => {
    const v = presentAccount(null, 'loading')
    assert.equal(v.planLabel, '')
    assert.equal(v.subscription.label, '')
    assert.equal(v.needsPlan, false)
    assert.equal(v.canChoosePlan, false)
    assert.equal(v.billingNotice, null)
  })

  it('does not treat a failed request as no plan', () => {
    const v = presentAccount(null, 'error')
    assert.equal(v.planLabel, 'Plan unavailable')
    assert.equal(v.needsPlan, false)
    assert.equal(v.canChoosePlan, false)
  })
})

describe('line, features and subscription stay separate', () => {
  it('keeps the line on and features on while billing is unverified', () => {
    const v = presentAccount(account({ plan: 'business', feature_plan: 'business' }), 'ready', 'missing')
    assert.deepEqual(v.phoneLine, { label: 'On', tone: 'success' })
    assert.equal(v.features.label, 'Business')
    assert.deepEqual(v.subscription, { label: 'Unverified', tone: 'warn' })
    assert.notEqual(v.subscription.label, 'Active')
  })

  it('does not offer a second subscription when billing is unverified', () => {
    const v = presentAccount(account(), 'ready', 'missing')
    assert.equal(v.needsPlan, false)
    assert.equal(v.canChoosePlan, false)
    assert.match(v.billingNotice.title, /verify your subscription/)
    assert.doesNotMatch(v.billingNotice.body, /suspended|cancelled|canceled/)
  })

  it('says a provider outage is not a verdict', () => {
    const v = presentAccount(account(), 'ready', 'unavailable')
    assert.equal(v.subscription.label, 'Not verified right now')
    assert.equal(v.canChoosePlan, false)
  })

  it('reports a tenant with no number apart from its plan', () => {
    const v = presentAccount(account({ phone_line: 'none' }), 'ready', 'ok')
    assert.equal(v.phoneLine.label, 'No number yet')
    assert.equal(v.subscription.label, 'Active')
  })

  it('reports a line that is off while the subscription is active', () => {
    const v = presentAccount(account({ phone_line: 'off' }), 'ready', 'ok')
    assert.equal(v.phoneLine.label, 'Off')
    assert.equal(v.subscription.label, 'Active')
  })
})

describe('complimentary accounts', () => {
  const comp = over => account({ source: 'complimentary', has_provider_subscription: false, ...over })

  it('cannot buy a plan themselves', () => {
    for (const plan of [null, 'pro']) {
      const v = presentAccount(comp({ plan, feature_plan: plan }), 'ready', 'none')
      assert.equal(v.canChoosePlan, false)
      assert.equal(v.needsPlan, false)
    }
  })

  it('are told how to talk about a paid plan', () => {
    const v = presentAccount(comp(), 'ready', 'none')
    assert.equal(v.subscription.label, 'Complimentary')
    assert.match(v.billingNotice.body, /support@openlines\.ai/)
  })

  it('show complimentary with the features they actually have', () => {
    const v = presentAccount(comp({ plan: 'pro', feature_plan: 'pro' }), 'ready', 'none')
    assert.equal(v.planLabel, 'Pro (complimentary)')
    assert.equal(v.features.label, 'Pro')
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
