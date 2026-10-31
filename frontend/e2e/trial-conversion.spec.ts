// Drives the real signup wizard with the real gtag.js. The API, Stripe and Supabase
// are stubbed, and every outbound Google hit is recorded and blocked, so a run
// provisions nothing and sends nothing to Google Ads. Passing here means the tag
// builds the right request; it does not show that Google Ads accepted one.
import { expect, test, type BrowserContext, type Page } from '@playwright/test'

const LABEL = 'ZEN5CKaqnNEcEO3Gi6FE'
const GCLID = 'TESTGCLID_e2e_123'
const API = 'http://api.test'

const STRIPE_STUB = `
window.Stripe = function () {
  const el = () => ({ mount(){}, unmount(){}, destroy(){}, update(){}, on(){ return this }, off(){ return this },
    getValue: async () => ({ complete: true, value: { name: 'Test', address: { country: 'CA' } } }) });
  const made = {};
  return {
    elements: () => ({ create: (t) => (made[t] = el()), getElement: (t) => made[t] || el(), update(){}, submit: async () => ({}) }),
    createToken(){}, createPaymentMethod(){}, confirmCardPayment(){},
    confirmSetup: async () => ({ setupIntent: { payment_method: 'pm_test' } }),
    registerAppInfo(){}, _registerWrapper(){},
  };
};`

const CARD_TRIAL = {
  trial_activation: 'card',
  trial: { plan: 'pro', status: 'trialing', trial_ends_at: '2026-11-06T00:00:00+00:00' },
}
const provisioned = (tenant_id: string, extra: object = {}) => ({
  tenant_id, phone_number: '+14165550100', assistant_id: 'a', status: 'live', dashboard_url: '', ...extra,
})

interface Mock {
  provision: { status?: number; delayMs?: number; body: object }[]
  tenantTrial?: object
}

interface Harness {
  hits: string[]
  setupCardCalls: () => number
}

async function stubNetwork(context: BrowserContext, mock: Mock): Promise<Harness> {
  const hits: string[] = []
  let setupCards = 0
  const cors = {
    'access-control-allow-origin': '*',
    'access-control-allow-headers': '*',
    'access-control-allow-methods': '*',
  }

  await context.route('**/*', async route => {
    const request = route.request()
    const url = request.url()
    if (url.startsWith('http://localhost')) return route.continue()
    if (url.includes('googletagmanager.com/gtag/js')) return route.continue()
    if (url.includes('js.stripe.com')) {
      return route.fulfill({ contentType: 'text/javascript', body: STRIPE_STUB })
    }
    if (url.startsWith(API)) {
      if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors })
      if (url.includes('/setup-card')) {
        setupCards += 1
        return route.fulfill({ headers: cors, json: { client_secret: 'seti_x_secret_y', card_setup_token: 'tok' } })
      }
      if (url.includes('/onboarding/provision')) {
        const next = mock.provision.shift()
        if (!next) throw new Error('unexpected provision call')
        if (next.delayMs) await new Promise(r => setTimeout(r, next.delayMs))
        return route.fulfill({ status: next.status ?? 200, headers: cors, json: next.body })
      }
      if (url.includes('/onboarding/status/')) {
        return route.fulfill({ headers: cors, json: { trial: mock.tenantTrial ?? null } })
      }
      return route.fulfill({ status: 404, headers: cors, json: {} })
    }
    if (url.startsWith('http://supabase.test')) {
      return route.fulfill({ status: 400, headers: cors, json: { error: 'stubbed' } })
    }
    if (url.includes(LABEL)) hits.push(url)
    return route.abort()
  })
  return { hits, setupCardCalls: () => setupCards }
}

const conversionCalls = (page: Page) => page.evaluate(() => {
  const layer = (window as unknown as { dataLayer?: ArrayLike<unknown>[] }).dataLayer ?? []
  return Array.from(layer)
    .map(entry => Array.from(entry))
    .filter(entry => entry[0] === 'event' && entry[1] === 'conversion')
    .map(entry => entry[2] as Record<string, unknown>)
})

async function goToCardStep(page: Page) {
  await page.goto(`/onboarding?gclid=${GCLID}&utm_source=google`)
  await page.getByRole('button', { name: "I don't have a website" }).click()
  await page.getByRole('button', { name: 'Start Setup →' }).click()
  await page.locator('input[name=business_name]').fill('Example Salon')
  await page.locator('textarea[name=business_description]').fill('A test business')
  await page.getByRole('button', { name: 'Continue →' }).click()
  await page.locator('input[name=email]').fill('owner@example.com')
  await page.locator('input[name=password]').fill('password123')
  await page.getByRole('button', { name: 'Continue →' }).click()
  await page.getByText('Choose your plan').waitFor()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: 'Continue →' }).click()
  await page.getByRole('button', { name: 'Start My Free Trial →' }).waitFor()
}

async function submitCard(page: Page) {
  await page.getByRole('button', { name: 'Start My Free Trial →' }).click()
  await page.waitForTimeout(2500)
}

test('page views, signup clicks and the login page record nothing', async ({ page, context }) => {
  const { hits } = await stubNetwork(context, { provision: [] })
  for (const path of ['/', '/login', '/salons']) {
    await page.goto(path)
    await page.waitForTimeout(1500)
    expect(await conversionCalls(page)).toEqual([])
  }
  await page.goto('/onboarding')
  await page.getByRole('button', { name: "I don't have a website" }).click()
  await page.getByRole('button', { name: 'Start Setup →' }).click()
  expect(await conversionCalls(page)).toEqual([])
  expect(hits).toEqual([])
})

test('a card trial records one attributed conversion with no value or personal data', async ({ page, context }) => {
  const tenant = '11111111-1111-4111-8111-111111111111'
  const { hits } = await stubNetwork(context, { provision: [{ body: provisioned(tenant, CARD_TRIAL) }] })
  await goToCardStep(page)
  await submitCard(page)

  expect(await conversionCalls(page)).toEqual([
    { send_to: `AW-18323006317/${LABEL}`, transaction_id: tenant },
  ])
  await expect.poll(() => hits.length).toBeGreaterThan(0)
  for (const hit of hits) {
    const params = new URL(hit).searchParams
    expect(params.get('oid')).toBe(tenant)
    expect(params.get('value') ?? '0').toBe('0')
    expect(hit).not.toMatch(/owner(%40|@)example|Example(\+|%20)Salon|4165550100/)
  }
  const cookies = await context.cookies()
  expect(cookies.find(c => c.name === '_gcl_aw')?.value).toContain(GCLID)

  const sent = hits.length
  await page.reload()
  await page.waitForTimeout(2000)
  expect(await conversionCalls(page)).toEqual([])
  expect(hits.length).toBe(sent)
})

test('the no-card fallback after a Stripe failure records one conversion', async ({ page, context }) => {
  const tenant = '55555555-5555-4555-8555-555555555555'
  await stubNetwork(context, { provision: [{ body: provisioned(tenant, { trial_activation: 'fallback' }) }] })
  await goToCardStep(page)
  await submitCard(page)
  expect(await conversionCalls(page)).toEqual([
    { send_to: `AW-18323006317/${LABEL}`, transaction_id: tenant },
  ])
})

for (const [name, delayMs] of [['instant', 0], ['slow', 1500]] as const) {
  test(`a ${name} failed signup records nothing and the card step can be retried`, async ({ page, context }) => {
    const tenant = '22222222-2222-4222-8222-222222222222'
    const { hits, setupCardCalls } = await stubNetwork(context, {
      provision: [
        { status: 400, delayMs, body: { detail: 'Your payment session expired.' } },
        { body: provisioned(tenant, CARD_TRIAL) },
      ],
    })
    await goToCardStep(page)
    const setupCardsBefore = setupCardCalls()
    await submitCard(page)
    await expect(page.getByText('Your payment session expired.')).toBeVisible()
    expect(await conversionCalls(page)).toEqual([])
    expect(hits).toEqual([])

    // The regression: an instant failure left this stuck on "Setting up…".
    const retry = page.getByRole('button', { name: 'Start My Free Trial →' })
    await expect(retry).toBeEnabled({ timeout: 10_000 })
    expect(setupCardCalls()).toBeGreaterThan(setupCardsBefore) // fresh SetupIntent

    await submitCard(page)
    const calls = await conversionCalls(page)
    expect(calls).toHaveLength(1)
    expect(calls[0].transaction_id).toBe(tenant)
  })
}

test('a repeated success for one tenant does not record again', async ({ page, context }) => {
  const tenant = '33333333-3333-4333-8333-333333333333'
  const { hits } = await stubNetwork(context, {
    provision: [{ body: provisioned(tenant, CARD_TRIAL) }, { body: provisioned(tenant, CARD_TRIAL) }],
  })
  await goToCardStep(page)
  await submitCard(page)
  await expect.poll(() => hits.length).toBeGreaterThan(0)
  await page.waitForTimeout(1500)
  const sent = hits.length

  await goToCardStep(page)
  await submitCard(page)
  expect(await conversionCalls(page)).toEqual([])
  expect(hits.length).toBe(sent)
})

test('a delayed trial records only after the dashboard confirms activation', async ({ page, context }) => {
  const tenant = '44444444-4444-4444-8444-444444444444'
  const mock: Mock = {
    provision: [{
      body: provisioned(tenant, { onboarding_state: 'regulatory_required', phone_number: '' }),
    }],
    tenantTrial: { trial_pending_activation: true, card_trial: false },
  }
  const { hits } = await stubNetwork(context, mock)
  await goToCardStep(page)
  await submitCard(page)
  expect(await conversionCalls(page)).toEqual([])

  await page.evaluate(() => localStorage.setItem('sb-supabase-auth-token', JSON.stringify({
    access_token: 'stub', refresh_token: 'stub', token_type: 'bearer',
    expires_at: Math.floor(Date.now() / 1000) + 3600, expires_in: 3600,
    user: { id: 'u1', aud: 'authenticated', email: 'owner@example.com', app_metadata: {}, user_metadata: {} },
  })))

  await page.goto(`/dashboard/${tenant}`)
  await page.waitForTimeout(2500)
  expect(await conversionCalls(page)).toEqual([])

  mock.tenantTrial = { trial_pending_activation: false, card_trial: true, trial_active: true }
  await page.reload()
  await expect.poll(() => conversionCalls(page), { timeout: 15_000 }).toEqual([
    { send_to: `AW-18323006317/${LABEL}`, transaction_id: tenant },
  ])

  await page.waitForTimeout(1500)
  const sent = hits.length
  await page.reload()
  await page.waitForTimeout(2500)
  expect(await conversionCalls(page)).toEqual([])
  expect(hits.length).toBe(sent)
})

test('an existing customer on the dashboard never records', async ({ page, context }) => {
  const tenant = '66666666-6666-4666-8666-666666666666'
  await stubNetwork(context, { provision: [], tenantTrial: { card_trial: true, trial_active: true } })
  await page.goto('/login')
  await page.evaluate(() => localStorage.setItem('sb-supabase-auth-token', JSON.stringify({
    access_token: 'stub', refresh_token: 'stub', token_type: 'bearer',
    expires_at: Math.floor(Date.now() / 1000) + 3600, expires_in: 3600,
    user: { id: 'u1', aud: 'authenticated', email: 'owner@example.com', app_metadata: {}, user_metadata: {} },
  })))
  await page.goto(`/dashboard/${tenant}`)
  await page.waitForTimeout(3000)
  expect(page.url()).toContain('/dashboard/')
  expect(await conversionCalls(page)).toEqual([])
})
