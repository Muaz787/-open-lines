// The dashboard against a mocked tenant. Every API, Supabase and third-party request
// is fulfilled here or blocked, so a run changes nothing and reaches no account.
import { expect, test, type BrowserContext, type Page, type Route } from '@playwright/test'

const STRIPE_STUB = `window.Stripe = () => ({
  elements: () => ({ create: () => ({ mount() {}, destroy() {}, on() { return this }, update() {} }), update() {} }),
  createToken() {}, createPaymentMethod() {}, confirmCardPayment() {}, registerAppInfo() {}, _registerWrapper() {},
});`

const TENANT = '77777777-7777-4777-8777-777777777777'
const API = 'http://api.test'
const BASE = `/dashboard/${TENANT}`

const paidAccount = {
  plan: 'pro', feature_plan: 'pro', phone_line: 'on', source: 'subscription', subscription: 'active',
  has_provider_subscription: true, line_active: true, pending_activation: false,
}
const manualAccount = { ...paidAccount, source: 'manual', has_provider_subscription: false }

const LEAD = { id: 'l1', name: null, phone: '+15555550100', urgency: null, status: 'new', summary: 'Sample summary', created_at: '2026-10-30T12:00:00Z' }
const CALL = { id: 'c1', duration_secs: 60, created_at: '2026-10-30T12:00:00Z', leads: { name: 'Sample Caller', phone: '+15555550101', urgency: 'warm', summary: 'Sample call' } }
const STATS = (n: number) => ({ total_calls: n, total_leads: 1, minutes_handled: 3, appointments_booked: 0, series: { calls: [n], leads: [1], minutes: [3], appointments: [0] } })

interface Mock {
  account: object
  provider: object
  failCalls?: boolean
  failStats?: boolean
  failProvider?: boolean
  holdProvider?: boolean
  releaseProvider?: () => void
  statsRequests: string[]
  mutations: string[]
}

const mock = (over: Partial<Mock> = {}): Mock => ({
  account: paidAccount,
  provider: { has_subscription: true, provider_state: 'ok', plan: 'pro', status: 'active' },
  statsRequests: [],
  mutations: [],
  ...over,
})

async function answer(route: Route, m: Mock) {
  const request = route.request()
  const url = request.url()
  const headers = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' }
  const json = (body: unknown, status = 200) => route.fulfill({ status, headers, json: body })
  if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
  if (request.method() !== 'GET') { m.mutations.push(url); return json({}) }
  if (url.includes('/onboarding/status/')) {
    return json({ id: TENANT, business_name: 'Sample Salon', subscription_plan: 'pro', subscription_status: 'active', account: m.account, trial: null })
  }
  if (url.includes('/notification-options/')) {
    const channel = { available: true, enabled: false, destination: '' }
    return json({ channels: { email: channel, sms: channel, whatsapp: channel }, dashboard_only: false, suggested_email: '', explicitly_set: true })
  }
  if (url.includes('/knowledge/entries/')) return json({ entries: [] })
  if (url.includes('/stats')) {
    m.statsRequests.push(url)
    if (m.failStats) return json({}, 500)
    return json(STATS(url.includes('30d') ? 5 : 2))
  }
  if (url.includes('/analytics')) {
    if (m.failCalls) return json({}, 500)
    return json({ total_calls: 1, avg_duration_secs: 60, urgency_breakdown: { hot: 0, warm: 1, cold: 0, unknown: 0 }, calls_by_day: {} })
  }
  if (url.includes('/calls/')) return m.failCalls ? json({}, 500) : json([CALL])
  if (url.includes('/subscription-details/')) {
    if (m.failProvider) return json({}, 500)
    if (m.holdProvider) await new Promise<void>(resolve => { m.releaseProvider = resolve })
    return json(m.provider)
  }
  if (url.includes('/billing/usage/')) return json({ plan: 'pro', minutes_included: 400, minutes_used: 36, minutes_remaining: 364, overage_minutes: 0, overage_cost_cents: 0, usage_pct: 9 })
  if (/\/leads\/[^/]+(\?|$)/.test(url)) return json([LEAD])
  return json([], 200)
}

async function signIn(page: Page, context: BrowserContext, m: Mock) {
  await context.route('**/*', route => {
    const url = route.request().url()
    if (url.startsWith('http://localhost')) return route.continue()
    if (url.startsWith(API)) return answer(route, m)
    if (url.includes('js.stripe.com')) return route.fulfill({ contentType: 'text/javascript', body: STRIPE_STUB })
    return route.abort()
  })
  await context.addInitScript(() => localStorage.setItem('sb-supabase-auth-token', JSON.stringify({
    access_token: 'stub', refresh_token: 'stub', token_type: 'bearer',
    expires_at: Math.floor(Date.now() / 1000) + 3600, expires_in: 3600,
    user: { id: 'u1', aud: 'authenticated', email: 'owner@example.com', app_metadata: {}, user_metadata: {} },
  })))
}

const ROUTES = ['', '/leads', '/calls', '/knowledge-base', '/call-handling', '/calendar', '/integrations', '/payments', '/settings', '/subscription', '/usage']

for (const route of ROUTES) {
  test(`${route || '/'} loads, survives reload and changes nothing`, async ({ page, context }) => {
    const m = mock()
    const crashes: string[] = []
    page.on('pageerror', e => crashes.push(`${e.message} ${(e.stack ?? '').split('\n').slice(1, 3).join(' ')}`))
    await signIn(page, context, m)
    await page.goto(BASE + route)
    await expect(page.locator('.db-sidebar')).toBeVisible({ timeout: 20_000 })
    await page.reload()
    await expect(page.locator('.db-sidebar')).toBeVisible({ timeout: 20_000 })
    expect(crashes).toEqual([])
    expect(m.mutations).toEqual([])
  })
}

test('a paid plan reads the same on every surface', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/usage`)
  await expect(page.getByRole('link', { name: /Billing/ }).locator('.db-nav-badge')).toHaveText('Active')
  await expect(page.locator('.db-content')).toContainText('Active')
  await page.goto(`${BASE}/subscription`)
  await expect(page.locator('.db-content')).not.toContainText('No active subscription')
})

test('a manual plan is never shown as a paid subscription', async ({ page, context }) => {
  await signIn(page, context, mock({ account: manualAccount, provider: { has_subscription: false, provider_state: 'none' } }))
  await page.goto(BASE)
  await expect(page.getByRole('link', { name: /Billing/ }).locator('.db-nav-badge')).toHaveText('Manual')
  await expect(page.locator('.db-sub-compact')).toContainText('Pro (manual access)')
  await expect(status(page)).not.toContainText('Active')
  await page.goto(`${BASE}/subscription`)
  await expect(page.getByText('No paid subscription', { exact: true })).toBeVisible()
  await expect(page.getByText(/support@openlines\.ai/)).toBeVisible()
  await expect(page.getByText('Choose a Plan')).toHaveCount(0)
  await expect(page.getByText('Change Plan')).toHaveCount(0)
})

const status = (page: Page) => page.getByTestId('account-status')

test('an unverified subscription is labelled on every page, with the line still on', async ({ page, context }) => {
  await signIn(page, context, mock({
    account: { ...paidAccount, plan: 'business', feature_plan: 'business' },
    provider: { has_subscription: false, provider_state: 'missing' },
  }))
  for (const route of ['', '/usage', '/subscription']) {
    await page.goto(BASE + route)
    await expect(status(page)).toContainText('Phone line')
    await expect(status(page)).toContainText('On')
    await expect(status(page)).toContainText('Features')
    await expect(status(page)).toContainText('Business')
    await expect(status(page)).toContainText('Unverified')
    await expect(status(page)).not.toContainText('Active')
    await expect(page.getByRole('link', { name: /Billing/ }).locator('.db-nav-badge')).toHaveText('Unverified')
    await expect(page.locator('.db-clinic-tag')).toContainText('Phone line: On')
  }
})

test('an unverified subscription offers no way to buy a second one', async ({ page, context }) => {
  await signIn(page, context, mock({ provider: { has_subscription: false, provider_state: 'missing' } }))
  await page.goto(`${BASE}/subscription`)
  await expect(page.getByText('We couldn’t verify your subscription')).toBeVisible()
  await expect(page.getByText('Choose a Plan')).toHaveCount(0)
  await expect(page.getByText('Change Plan')).toHaveCount(0)
})

test('nothing says Active while Stripe is still answering', async ({ page, context }) => {
  const m = mock({ holdProvider: true })
  await signIn(page, context, m)
  await page.goto(`${BASE}/usage`)
  await expect(status(page)).toContainText('Checking…')
  await expect(page.getByRole('link', { name: /Billing/ }).locator('.db-nav-badge')).toHaveText('Checking…')
  m.releaseProvider?.()
  await expect(status(page)).toContainText('Active')
})

test('a Stripe outage reads as not verified, not as a lost subscription', async ({ page, context }) => {
  await signIn(page, context, mock({ failProvider: true }))
  await page.goto(`${BASE}/usage`)
  await expect(status(page)).toContainText('Not verified right now')
  await expect(status(page)).not.toContainText('Unverified')
})

test('a tenant with no number reads apart from its subscription', async ({ page, context }) => {
  await signIn(page, context, mock({ account: { ...paidAccount, phone_line: 'none' } }))
  await page.goto(`${BASE}/usage`)
  await expect(status(page)).toContainText('No number yet')
  await expect(status(page)).toContainText('Active')
})

test('a complimentary account cannot buy a plan', async ({ page, context }) => {
  const m = mock({
    account: { ...manualAccount, source: 'complimentary' },
    provider: { has_subscription: false, provider_state: 'none' },
  })
  await signIn(page, context, m)
  await page.goto(`${BASE}/subscription`)
  await expect(page.getByText('Complimentary account')).toBeVisible()
  await expect(status(page)).toContainText('Complimentary')
  await expect(page.getByText('Choose a Plan')).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'support@openlines.ai' }).or(page.getByText(/support@openlines\.ai/))).toBeVisible()
  await expect(page.getByText('Choose a plan', { exact: false })).toHaveCount(0)
  await page.goto(BASE)
  await expect(page.getByText('No active plan')).toHaveCount(0)
  expect(m.mutations).toEqual([])
})

test('an account with no plan can still choose one', async ({ page, context }) => {
  await signIn(page, context, mock({
    account: { ...paidAccount, plan: null, feature_plan: null, source: 'none', subscription: 'none', has_provider_subscription: false },
    provider: { has_subscription: false, provider_state: 'none' },
  }))
  await page.goto(`${BASE}/subscription`)
  await expect(page.getByText('Choose a Plan', { exact: true })).toBeVisible()
})

test('the overview period survives reload and Back/Forward', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(BASE)
  await page.getByRole('button', { name: '30d' }).click()
  await expect(page).toHaveURL(/period=30d/)
  await expect(page.locator('.db-stat-num').first()).toHaveText('5')
  await page.reload()
  await expect(page.locator('.db-stat-num').first()).toHaveText('5')
  await page.goBack()
  await expect(page.locator('.db-stat-num').first()).toHaveText('2')
  await page.goForward()
  await expect(page.locator('.db-stat-num').first()).toHaveText('5')
})

test('an edited period in the URL falls back safely', async ({ page, context }) => {
  const m = mock()
  await signIn(page, context, m)
  await page.goto(`${BASE}?period=999d`)
  await expect(page.locator('.db-stat-num').first()).toHaveText('2')
  expect(m.statsRequests.every(u => u.includes('period=7d'))).toBe(true)
})

test('a filter with no matches says so and can be cleared', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/calls?quality=hot`)
  await expect(page.getByText('No hot calls in the last 30 days.')).toBeVisible()
  await expect(page.getByText('after your first inbound call')).toHaveCount(0)
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(page.getByText('Sample Caller')).toBeVisible()
})

test('the calendar tab survives reload', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/calendar?appointments=past`)
  const past = page.getByRole('button', { name: /Past/ })
  await expect(past).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(past).toHaveAttribute('aria-pressed', 'true')
})

test('call rows open from the keyboard', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/calls`)
  const row = page.locator('.db-lead-main').first()
  await expect(row).toHaveAttribute('aria-expanded', 'false')
  await row.focus()
  await page.keyboard.press('Enter')
  await expect(row).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press(' ')
  await expect(row).toHaveAttribute('aria-expanded', 'false')
})

test('a failed request is an error with a retry, not an empty list', async ({ page, context }) => {
  const m = mock({ failCalls: true })
  await signIn(page, context, m)
  await page.goto(`${BASE}/calls`)
  await expect(page.getByText('We couldn’t load your calls.')).toBeVisible()
  await expect(page.getByText('No calls')).toHaveCount(0)
  m.failCalls = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Sample Caller')).toBeVisible()
})

test('failed stats do not show as zeros', async ({ page, context }) => {
  await signIn(page, context, mock({ failStats: true }))
  await page.goto(BASE)
  await expect(page.getByText('We couldn’t load your performance numbers.')).toBeVisible()
  await expect(page.locator('.db-stat-card')).toHaveCount(0)
})

test('the active nav item is marked and leads show honest labels', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/leads`)
  await expect(page.locator('.db-sidebar [aria-current="page"]')).toContainText('Leads')
  await expect(page.getByText('Unknown caller')).toBeVisible()
})

test('clearing the knowledge base sits behind Advanced', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/knowledge-base`)
  const clear = page.getByRole('button', { name: 'Clear Knowledge Base' })
  await expect(clear).toBeHidden()
  await page.getByText('Advanced', { exact: true }).click()
  await expect(clear).toBeVisible()
})

for (const width of [390, 768, 1024, 1440]) {
  test(`no sideways scroll at ${width}px`, async ({ page, context }) => {
    await page.setViewportSize({ width, height: 844 })
    await signIn(page, context, mock())
    for (const route of ['', '/calls', '/subscription', '/usage']) {
      await page.goto(BASE + route)
      await page.waitForTimeout(1000)
      expect(await page.evaluate(() => innerWidth)).toBe(width)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
      expect(overflow, `${route} at ${width}`).toBeLessThanOrEqual(0)
    }
  })
}

test('a call row stays readable on a phone', async ({ page, context }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page, context, mock())
  await page.goto(`${BASE}/calls`)
  await expect(page.locator('.db-lead-phone-inline').first()).toBeVisible()
  const phone = await page.locator('.db-lead-phone-inline').first().boundingBox()
  const badge = await page.locator('.db-lead-main .db-urg-warm').first().boundingBox()
  expect(phone!.y + phone!.height <= badge!.y || phone!.x + phone!.width <= badge!.x).toBe(true)
})

test('the sidebar reports the real line state', async ({ page, context }) => {
  await signIn(page, context, mock({ account: { ...paidAccount, phone_line: 'off' } }))
  await page.goto(`${BASE}/usage`)
  await expect(page.locator('.db-clinic-tag')).toHaveText('Phone line: Off')
})

test('30d survives the 30-second refresh', async ({ page, context }) => {
  const m = mock()
  await page.clock.install()
  await signIn(page, context, m)
  await page.goto(`${BASE}?period=30d`)
  await expect(page.locator('.db-stat-num').first()).toHaveText('5')
  m.statsRequests.length = 0
  await page.clock.fastForward(31_000)
  await expect.poll(() => m.statsRequests.length).toBeGreaterThan(0)
  expect(m.statsRequests.every(u => u.includes('period=30d'))).toBe(true)
  await expect(page.locator('.db-stat-num').first()).toHaveText('5')
})

test('filters persist across pages and reload', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/calls`)
  await page.getByRole('button', { name: '7d' }).click()
  await expect(page).toHaveURL(/period=7/)
  await page.getByRole('button', { name: /WARM|Warm/ }).first().click()
  await expect(page).toHaveURL(/quality=warm/)
  await page.reload()
  await expect(page).toHaveURL(/period=7/)
  await expect(page).toHaveURL(/quality=warm/)
  await expect(page.getByText('Sample Caller')).toBeVisible()
})

test('matching periods ask for the same range on overview and calls', async ({ page, context }) => {
  const m = mock()
  await signIn(page, context, m)
  await page.goto(BASE)
  await expect(page.locator('.db-stat-num').first()).toHaveText('2')
  expect(m.statsRequests.at(-1)).toContain('period=7d')
  await page.goto(`${BASE}/calls?period=7`)
  await expect(page.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true')
})

test('mobile navigation opens and moves between pages', async ({ page, context }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page, context, mock())
  await page.goto(`${BASE}/usage`)
  await page.getByRole('button', { name: /menu/i }).click()
  await page.getByRole('link', { name: 'Calls' }).click()
  await expect(page).toHaveURL(/\/calls/)
  await expect(page.getByText('Sample Caller')).toBeVisible()
})

// Review images only: set DASHBOARD_SHOTS to a folder to capture every route.
if (process.env.DASHBOARD_SHOTS) {
  const shots = process.env.DASHBOARD_SHOTS
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]] as const) {
    test(`capture ${name} screenshots`, async ({ page, context }) => {
      await page.setViewportSize({ width, height })
      await signIn(page, context, mock())
      for (const route of ROUTES) {
        await page.goto(BASE + route)
        await page.waitForTimeout(1200)
        await page.screenshot({ path: `${shots}/${name}${route.replace('/', '-') || '-overview'}.png` })
      }
    })
  }
  const none = { has_subscription: false, provider_state: 'none' }
  const states: Record<string, Partial<Mock>> = {
    active: {},
    trial: { account: { ...paidAccount, subscription: 'trialing' }, provider: { has_subscription: true, provider_state: 'ok', plan: 'pro', status: 'trialing' } },
    past_due: { account: { ...paidAccount, subscription: 'past_due' }, provider: { has_subscription: true, provider_state: 'ok', plan: 'pro', status: 'past_due' } },
    manual: { account: manualAccount, provider: none },
    complimentary: { account: { ...manualAccount, source: 'complimentary' }, provider: none },
    unverified: { provider: { has_subscription: false, provider_state: 'missing' } },
    none: { account: { ...paidAccount, plan: null, source: 'none', subscription: 'none', has_provider_subscription: false }, provider: none },
  }
  for (const [state, over] of Object.entries(states)) {
    test(`capture billing state ${state}`, async ({ page, context }) => {
      await signIn(page, context, mock(over))
      for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]] as const) {
        await page.setViewportSize({ width, height })
        await page.goto(`${BASE}/subscription`)
        await page.waitForTimeout(1200)
        await page.screenshot({ path: `${shots}/billing-${state}-${name}.png` })
      }
    })
  }
}
