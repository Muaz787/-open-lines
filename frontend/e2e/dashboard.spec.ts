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
  rejectToken?: boolean
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
  if (m.rejectToken) return json({ detail: 'Invalid or expired token' }, 401)
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

async function signIn(page: Page, context: BrowserContext, m: Mock, auth: AuthService = { status: 200 }) {
  await context.route('**/*', route => {
    const url = route.request().url()
    if (url.startsWith('http://localhost')) return route.continue()
    if (url.startsWith(API)) return answer(route, m)
    if (url.startsWith('http://supabase.test')) return answerAuth(route, auth)
    if (url.includes('js.stripe.com')) return route.fulfill({ contentType: 'text/javascript', body: STRIPE_STUB })
    return route.abort()
  })
  await context.addInitScript(([expiresIn]) => localStorage.setItem('sb-supabase-auth-token', JSON.stringify({
    access_token: 'stub', refresh_token: 'stub', token_type: 'bearer',
    expires_at: Math.floor(Date.now() / 1000) + expiresIn, expires_in: 3600,
    user: { id: 'u1', aud: 'authenticated', email: 'owner@example.com', app_metadata: {}, user_metadata: {} },
  })), [auth.tokenExpired ? -60 : 3600])
}

// What Supabase Auth does. `status` is its answer; 'down' means it can't be reached.
interface AuthService { status: number | 'down'; code?: string; tokenExpired?: boolean }

const AUTH_USER = { id: 'u1', aud: 'authenticated', email: 'owner@example.com', app_metadata: {}, user_metadata: {} }

function answerAuth(route: Route, auth: AuthService) {
  const headers = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' }
  if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers })
  if (auth.status === 'down') return route.abort()
  if (auth.status !== 200) return route.fulfill({ status: auth.status, headers: { ...headers, 'x-supabase-api-version': '2024-01-01', 'access-control-expose-headers': '*' }, json: { code: auth.code, message: 'stubbed' } })
  if (route.request().url().includes('/token')) {
    return route.fulfill({ headers, json: { access_token: 'stub', refresh_token: 'stub', token_type: 'bearer', expires_in: 3600, user: AUTH_USER } })
  }
  return route.fulfill({ headers, json: AUTH_USER })
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

for (const [name, account] of [['complimentary', { ...manualAccount, source: 'complimentary' }], ['manual', manualAccount]] as const) {
  test(`Usage offers a ${name} account no price or plan change`, async ({ page, context }) => {
    await signIn(page, context, mock({ account, provider: { has_subscription: false, provider_state: 'none' } }))
    await page.goto(`${BASE}/usage`)
    await expect(status(page)).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('of allowance used')).toBeVisible()
    await expect(page.getByText('Manage plan')).toHaveCount(0)
    await expect(page.getByText('Switch →')).toHaveCount(0)
    await expect(page.getByText(/\$\d+/)).toHaveCount(0)
  })
}

test('a paying account can still reach plan changes from Usage', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/usage`)
  await expect(page.getByText('Manage plan')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Switch →').first()).toBeVisible()
  await expect(page.getByText('$199 CAD/mo + tax')).toBeVisible()
})

test('an allowed complimentary account sees plans and the access promise', async ({ page, context }) => {
  await signIn(page, context, mock({
    account: { ...manualAccount, source: 'complimentary', paid_transition_open: true },
    provider: { has_subscription: false, provider_state: 'none' },
  }))
  await page.goto(`${BASE}/subscription`)
  await expect(page.getByText('You can now choose a paid plan')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Choose a Plan')).toBeVisible()
})

test('lead search narrows the list, survives reload and says when nothing matches', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/leads`)
  const search = page.getByRole('searchbox', { name: 'Search leads' })
  await search.fill('zzzz')
  await expect(page.getByText('No leads match your search.')).toBeVisible()
  await expect(page).toHaveURL(/q=zzzz/)
  await page.reload()
  await expect(page.getByRole('searchbox', { name: 'Search leads' })).toHaveValue('zzzz')
  await page.getByRole('searchbox', { name: 'Search leads' }).fill('')
  await expect(page.getByText('No leads match your search.')).toHaveCount(0)
})

test('Usage says which period it covers and how minutes are counted', async ({ page, context }) => {
  await signIn(page, context, mock({ account: { ...manualAccount, source: 'complimentary' }, provider: { has_subscription: false, provider_state: 'none' } }))
  await page.goto(`${BASE}/usage`)
  await expect(page.getByText(/doesn’t reset/)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(/rounded up/)).toBeVisible()
})

test('Settings marks unsaved edits and clears the mark after saving', async ({ page, context }) => {
  await signIn(page, context, mock())
  await page.goto(`${BASE}/settings`)
  const phone = page.locator('input[type=tel]').last()
  await phone.waitFor({ timeout: 20_000 })
  await expect(page.getByText('Unsaved changes')).toHaveCount(0)
  await phone.fill('+14165550100')
  await expect(page.getByText('Unsaved changes')).toBeVisible()
  await phone.locator('xpath=ancestor::section').getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Unsaved changes')).toHaveCount(0)
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

const authError = (page: Page) => page.getByRole('alert').filter({ hasText: 'We couldn’t confirm your sign-in.' })

for (const status of ['down', 429, 500, 503] as const) {
  test(`Settings offers a retry when auth answers ${status}, and shows no account content`, async ({ page, context }) => {
    const auth: AuthService = { status }
    await signIn(page, context, mock(), auth)
    await page.goto(`${BASE}/settings`)
    await expect(authError(page)).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('Call summary notifications')).toHaveCount(0)
    expect(page.url()).toContain('/settings')

    auth.status = 200
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(page.getByText('Call summary notifications')).toBeVisible()
    await expect(authError(page)).toHaveCount(0)
  })
}

for (const [status, code] of [[403, 'bad_jwt'], [403, 'session_expired'], [401, 'no_authorization'], [403, 'session_not_found']] as const) {
  test(`Settings goes to login when auth rejects the session with ${code}`, async ({ page, context }) => {
    await signIn(page, context, mock(), { status, code })
    await page.goto(`${BASE}/settings`)
    await page.waitForURL('**/login', { timeout: 20_000 })
    await expect(page.getByText('Call summary notifications')).toHaveCount(0)
  })
}

for (const [status, code] of [[400, 'validation_failed'], [401, undefined], [403, undefined], [404, undefined]] as const) {
  test(`an unrelated ${status} ${code ?? 'with no code'} from auth is not treated as signed out`, async ({ page, context }) => {
    const auth: AuthService = { status, code }
    await signIn(page, context, mock(), auth)
    await page.goto(`${BASE}/settings`)
    await expect(authError(page)).toBeVisible({ timeout: 20_000 })
    expect(page.url()).toContain('/settings')
    await expect(page.getByText('Call summary notifications')).toHaveCount(0)
  })
}

test('a retry that finds the session rejected goes to login', async ({ page, context }) => {
  const auth: AuthService = { status: 'down' }
  await signIn(page, context, mock(), auth)
  await page.goto(`${BASE}/settings`)
  await expect(authError(page)).toBeVisible({ timeout: 20_000 })
  auth.status = 403
  auth.code = 'bad_jwt'
  await page.getByRole('button', { name: 'Try again' }).click()
  await page.waitForURL('**/login', { timeout: 20_000 })
})

test('a token that cannot be refreshed during an outage keeps the user on the page', async ({ page, context }) => {
  const auth: AuthService = { status: 'down', tokenExpired: true }
  await signIn(page, context, mock(), auth)
  await page.goto(`${BASE}/settings`)
  await expect(page.getByRole('status').filter({ hasText: 'Reconnecting' })).toBeVisible({ timeout: 10_000 })
  await expect(page.locator('.db-sidebar')).toHaveCount(0)
  await expect(authError(page)).toBeVisible({ timeout: 45_000 })
  await expect(page.getByRole('status').filter({ hasText: 'Reconnecting' })).toHaveCount(0)
  expect(page.url()).toContain('/settings')
  await expect(page.locator('.db-sidebar')).toHaveCount(0)

  auth.status = 200
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Call summary notifications')).toBeVisible({ timeout: 20_000 })
})

test('a refresh token the auth service rejects goes to login', async ({ page, context }) => {
  await signIn(page, context, mock(), { status: 400, code: 'refresh_token_not_found', tokenExpired: true })
  await page.goto(`${BASE}/settings`)
  await page.waitForURL('**/login', { timeout: 20_000 })
})

for (const [status, code] of [[500, 'unexpected_failure'], [429, 'over_request_rate_limit'], [400, 'validation_failed']] as const) {
  test(`a ${status} ${code} during a refresh keeps the session and offers a retry`, async ({ page, context }) => {
    const auth: AuthService = { status, code, tokenExpired: true }
    await signIn(page, context, mock(), auth)
    await page.goto(`${BASE}/settings`)
    await expect(authError(page)).toBeVisible({ timeout: 45_000 })
    await expect(page.getByRole('link', { name: 'Sign in again' })).toBeVisible()
    await expect(page.locator('.db-sidebar')).toHaveCount(0)
    expect(await page.evaluate(() => localStorage.getItem('sb-supabase-auth-token'))).toContain('refresh_token')
  })
}

test('a token the backend rejects still goes to login', async ({ page, context }) => {
  await signIn(page, context, mock({ rejectToken: true }))
  await page.goto(`${BASE}/settings`).catch(() => {}) // redirected while still loading
  // Each rejected request redirects, and those navigations cancel one another.
  await expect(page).toHaveURL(/\/login$/, { timeout: 20_000 })
  await expect(page.getByText('Call summary notifications')).toHaveCount(0)
})

test('a password change during an auth outage says so and changes nothing', async ({ page, context }) => {
  const auth: AuthService = { status: 200 }
  const m = mock()
  await signIn(page, context, m, auth)
  await page.goto(`${BASE}/settings`)
  await expect(page.getByText('Call summary notifications')).toBeVisible({ timeout: 20_000 })
  auth.status = 'down'
  const fields = page.locator('input[type=password]')
  const count = await fields.count()
  await fields.nth(count - 3).fill('current-password')
  await fields.nth(count - 2).fill('new-password')
  await fields.nth(count - 1).fill('new-password')
  await page.getByRole('button', { name: 'Update password' }).click()
  await expect(authError(page)).toBeVisible({ timeout: 20_000 })
  expect(m.mutations).toEqual([])
})
