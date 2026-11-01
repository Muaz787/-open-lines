// Run with `npm test`.
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { classifyAuth, isWrongPassword, keepSessionUnlessRejected } from './authCheck.ts'

const apiError = (status, code, message = 'stubbed') => ({ name: 'AuthApiError', status, code, message })

describe('classifyAuth', () => {
  it('accepts a confirmed user', () => {
    assert.equal(classifyAuth(true), 'ok')
  })

  it('treats an answer of "no session" as expired', () => {
    assert.equal(classifyAuth(false), 'expired')
    assert.equal(classifyAuth(false, null), 'expired')
    assert.equal(classifyAuth(false, { name: 'AuthSessionMissingError', status: 400 }), 'expired')
  })

  for (const [status, code] of [
    [403, 'bad_jwt'], // the real response to a bad token
    [401, 'no_authorization'],
    [403, 'session_expired'],
    [404, 'session_not_found'],
    [400, 'refresh_token_not_found'],
    [400, 'refresh_token_already_used'],
    [403, 'user_not_found'],
    [403, 'user_banned'],
  ]) {
    it(`treats ${code} as expired`, () => {
      assert.equal(classifyAuth(false, apiError(status, code)), 'expired')
    })
  }

  for (const [status, code] of [
    [400, undefined],
    [401, undefined], // a disabled API key answers this way
    [403, undefined],
    [404, undefined],
    [400, 'validation_failed'],
    [403, 'over_request_rate_limit'],
    [403, 'email_not_confirmed'],
    [422, 'unexpected_failure'],
  ]) {
    it(`does not read an unrelated ${status} ${code ?? '(no code)'} as signed out`, () => {
      assert.equal(classifyAuth(false, apiError(status, code)), 'unavailable')
    })
  }

  for (const status of [0, 408, 429, 500, 502, 503, 504]) {
    it(`treats a ${status} as unavailable`, () => {
      assert.equal(classifyAuth(false, apiError(status)), 'unavailable')
    })
  }

  it('treats a network failure as unavailable', () => {
    assert.equal(classifyAuth(false, { name: 'AuthRetryableFetchError', status: 0 }), 'unavailable')
    assert.equal(classifyAuth(false, new TypeError('Failed to fetch')), 'unavailable')
  })

  it('never lets a confirmed user fall through to a rejection', () => {
    assert.equal(classifyAuth(true, apiError(403, 'bad_jwt')), 'ok')
  })
})

describe('keepSessionUnlessRejected', () => {
  const REFRESH = 'https://auth.test/auth/v1/token?grant_type=refresh_token'
  const reply = (status, body) => new Response(body === undefined ? null : JSON.stringify(body), { status })

  for (const code of ['refresh_token_not_found', 'refresh_token_already_used', 'session_expired', 'user_banned']) {
    it(`passes ${code} through, so the session ends`, async () => {
      assert.equal((await keepSessionUnlessRejected(REFRESH, reply(400, { code }))).status, 400)
    })
  }

  for (const [status, body] of [[500, { code: 'unexpected_failure' }], [429, { code: 'over_request_rate_limit' }], [400, { code: 'validation_failed' }], [401, { message: 'Legacy API keys are disabled' }], [500, undefined]]) {
    it(`reports a ${status} ${body?.code ?? ''} as temporary`, async () => {
      assert.equal((await keepSessionUnlessRejected(REFRESH, reply(status, body))).status, 503)
    })
  }

  it('leaves successful refreshes and every other request alone', async () => {
    assert.equal((await keepSessionUnlessRejected(REFRESH, reply(200, { access_token: 'x' }))).status, 200)
    assert.equal((await keepSessionUnlessRejected('https://auth.test/auth/v1/user', reply(500, {}))).status, 500)
    assert.equal((await keepSessionUnlessRejected('https://auth.test/auth/v1/token?grant_type=password', reply(400, {}))).status, 400)
  })
})

describe('isWrongPassword', () => {
  it('needs Supabase to say so', () => {
    assert.equal(isWrongPassword(apiError(400, 'invalid_credentials')), true)
    assert.equal(isWrongPassword(apiError(400, undefined)), false)
    assert.equal(isWrongPassword(apiError(429, 'over_request_rate_limit')), false)
    assert.equal(isWrongPassword({ name: 'AuthRetryableFetchError', status: 0 }), false)
  })
})
