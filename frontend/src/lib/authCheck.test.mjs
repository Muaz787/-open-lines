// Run with `npm test`.
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { classifyAuth } from './authCheck.ts'

describe('classifyAuth', () => {
  it('accepts a confirmed user', () => {
    assert.equal(classifyAuth(true), 'ok')
  })

  it('treats an answer of "no session" as expired', () => {
    assert.equal(classifyAuth(false), 'expired')
    assert.equal(classifyAuth(false, null), 'expired')
    assert.equal(classifyAuth(false, { name: 'AuthSessionMissingError', status: 400 }), 'expired')
  })

  for (const status of [400, 401, 403, 404]) {
    it(`treats a ${status} from the auth service as expired`, () => {
      assert.equal(classifyAuth(false, { name: 'AuthApiError', status }), 'expired')
    })
  }

  for (const status of [0, 408, 429, 500, 502, 503, 504]) {
    it(`treats a ${status} as unavailable, not expired`, () => {
      assert.equal(classifyAuth(false, { name: 'AuthApiError', status }), 'unavailable')
    })
  }

  it('treats a network failure as unavailable', () => {
    assert.equal(classifyAuth(false, { name: 'AuthRetryableFetchError', status: 0 }), 'unavailable')
    assert.equal(classifyAuth(false, { name: 'AuthRetryableFetchError', status: 400 }), 'unavailable')
    assert.equal(classifyAuth(false, new TypeError('Failed to fetch')), 'unavailable')
  })
})
