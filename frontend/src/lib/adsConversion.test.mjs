// Run with `npm test`. Exercises the real module with window/localStorage stubs.
import assert from 'node:assert/strict'
import { beforeEach, describe, it } from 'node:test'
import {
  ADS_TRIAL_SIGNUP_CONVERSION,
  resolvePendingTrialConversion,
  trackPaidSubscriptionConversion,
  trackTrialSignupConversion,
} from './adsConversion.ts'

const TENANT = '3f2b8c1e-7a4d-4e21-9b6f-1c2d3e4f5a6b'
const card = { tenant_id: TENANT, trial_activation: 'card' }
const fallback = { tenant_id: TENANT, trial_activation: 'fallback' }
const regulated = { tenant_id: TENANT, onboarding_state: 'regulatory_required' }

let calls
let store

beforeEach(() => {
  calls = []
  store = new Map()
  delete process.env.NEXT_PUBLIC_GOOGLE_ADS_PAID_CONVERSION
  globalThis.window = { gtag: (...args) => calls.push(args) }
  globalThis.localStorage = {
    getItem: k => store.get(k) ?? null,
    setItem: (k, v) => void store.set(k, v),
    removeItem: k => void store.delete(k),
  }
})

describe('activated trial', () => {
  for (const [name, result] of Object.entries({ card, fallback })) {
    it(`fires for a ${name} trial with only the destination and transaction id`, () => {
      trackTrialSignupConversion({ ...result, email: 'owner@example.com', phone_number: '+14165550100' })
      assert.deepEqual(calls, [['event', 'conversion', {
        send_to: ADS_TRIAL_SIGNUP_CONVERSION,
        transaction_id: TENANT,
      }]])
    })
  }
})

describe('no activated trial', () => {
  it('does not fire without trial_activation', () => {
    trackTrialSignupConversion({ tenant_id: TENANT, onboarding_state: 'provisioning' })
    assert.equal(calls.length, 0)
    assert.equal(store.size, 0)
  })

  it('does not fire without a tenant id', () => {
    trackTrialSignupConversion({ tenant_id: '', trial_activation: 'card' })
    assert.equal(calls.length, 0)
  })
})

describe('delayed (regulated) trial', () => {
  it('waits at signup, then fires once when activation is confirmed', () => {
    trackTrialSignupConversion(regulated)
    assert.equal(calls.length, 0)
    resolvePendingTrialConversion(TENANT, false)
    assert.equal(calls.length, 0)
    resolvePendingTrialConversion(TENANT, true)
    resolvePendingTrialConversion(TENANT, true)
    assert.equal(calls.length, 1)
    assert.equal(calls[0][2].transaction_id, TENANT)
  })

  it('never fires for a tenant not pending in this browser', () => {
    resolvePendingTrialConversion(TENANT, true)
    assert.equal(calls.length, 0)
  })

  it('stays pending if gtag is missing, then fires', () => {
    trackTrialSignupConversion(regulated)
    delete globalThis.window.gtag
    resolvePendingTrialConversion(TENANT, true)
    globalThis.window.gtag = (...args) => calls.push(args)
    resolvePendingTrialConversion(TENANT, true)
    assert.equal(calls.length, 1)
  })

  it('shares de-duplication with the immediate path', () => {
    trackTrialSignupConversion(card)
    store.set(`ol_ads_trial_pending:${TENANT}`, '1')
    resolvePendingTrialConversion(TENANT, true)
    assert.equal(calls.length, 1)
    assert.equal(store.has(`ol_ads_trial_pending:${TENANT}`), false)
  })
})

describe('duplicates', () => {
  it('fires once across card and fallback responses for one tenant', () => {
    trackTrialSignupConversion(fallback)
    trackTrialSignupConversion(card)
    assert.equal(calls.length, 1)
  })

  it('still fires for a different tenant', () => {
    trackTrialSignupConversion(card)
    trackTrialSignupConversion({ ...card, tenant_id: 'another-tenant' })
    assert.equal(calls.length, 2)
  })

  it('reuses the same transaction id when storage is unavailable', () => {
    globalThis.localStorage = {
      getItem() { throw new Error('blocked') },
      setItem() { throw new Error('blocked') },
      removeItem() { throw new Error('blocked') },
    }
    trackTrialSignupConversion(card)
    trackTrialSignupConversion(card)
    assert.equal(calls[0][2].transaction_id, TENANT)
    assert.equal(calls[1][2].transaction_id, TENANT)
  })

  it('does not mark a tenant sent when gtag is missing, so a later call can fire', () => {
    delete globalThis.window.gtag
    trackTrialSignupConversion(card)
    assert.equal(store.size, 0)
    globalThis.window.gtag = (...args) => calls.push(args)
    trackTrialSignupConversion(card)
    assert.equal(calls.length, 1)
  })
})

describe('paid subscription', () => {
  it('does nothing until its own label is configured', () => {
    trackPaidSubscriptionConversion(TENANT, 199, 'CAD')
    assert.equal(calls.length, 0)
  })

  it('refuses the trial label', () => {
    process.env.NEXT_PUBLIC_GOOGLE_ADS_PAID_CONVERSION = ADS_TRIAL_SIGNUP_CONVERSION
    trackPaidSubscriptionConversion(TENANT, 199, 'CAD')
    assert.equal(calls.length, 0)
  })

  it('sends value and currency to the configured label', () => {
    process.env.NEXT_PUBLIC_GOOGLE_ADS_PAID_CONVERSION = 'AW-18323006317/paidlabel'
    trackPaidSubscriptionConversion(TENANT, 199, 'CAD')
    assert.deepEqual(calls[0][2], {
      send_to: 'AW-18323006317/paidlabel',
      value: 199,
      currency: 'CAD',
      transaction_id: TENANT,
    })
  })
})
