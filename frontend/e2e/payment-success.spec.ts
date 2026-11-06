import { expect, test, type Page } from '@playwright/test'

// /payment-success footer. The API host is fake (playwright.config.ts) and every
// request is fulfilled here, so nothing reaches a real backend, Stripe or Square.

const SQUARE_REF = '7acfb74c-f58a-4923-978c-b2877a6021e3'
const STRIPE_SESSION = 'cs_test_a1B2c3D4e5F6g7H8'

async function mockProcessor(page: Page, answer: (url: URL) => { status: number; body?: unknown }) {
  const seen: string[] = []
  await page.route('http://api.test/payments/processor**', route => {
    const url = new URL(route.request().url())
    seen.push(url.search)
    const { status, body } = answer(url)
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body ?? {}) })
  })
  return seen
}

const footer = (page: Page) => page.getByTestId('payment-footer')

test('Square return link: our payment record says Square', async ({ page }) => {
  const seen = await mockProcessor(page, url =>
    url.searchParams.get('ref') === SQUARE_REF ? { status: 200, body: { processor: 'square' } }
      : { status: 200, body: { processor: null } })
  await page.goto(`/payment-success?ref=${SQUARE_REF}`)
  await expect(footer(page)).toHaveText('Processed by Square · Powered by Open Lines')
  expect(seen).toEqual([`?ref=${SQUARE_REF}`])
})

test('Stripe return link: our payment record says Stripe', async ({ page }) => {
  const seen = await mockProcessor(page, url =>
    url.searchParams.get('session_id') === STRIPE_SESSION ? { status: 200, body: { processor: 'stripe' } }
      : { status: 200, body: { processor: null } })
  await page.goto(`/payment-success?session_id=${STRIPE_SESSION}`)
  await expect(footer(page)).toHaveText('Secured by Stripe · Powered by Open Lines')
  expect(seen).toEqual([`?session_id=${STRIPE_SESSION}`])
})

test('direct visit: no lookup, neutral footer', async ({ page }) => {
  const seen = await mockProcessor(page, () => ({ status: 200, body: { processor: 'stripe' } }))
  await page.goto('/payment-success')
  await expect(footer(page)).toHaveText('Powered by Open Lines')
  await page.waitForTimeout(500)
  expect(seen).toEqual([])
  await expect(page.getByText(/Stripe|Square/)).toHaveCount(0)
})

for (const [name, path] of [
  ['unknown Square ref', `/payment-success?ref=00000000-0000-4000-8000-000000000000`],
  ['unknown Stripe session', `/payment-success?session_id=cs_test_unknownunknown`],
  ['a made-up processor parameter', `/payment-success?processor=square`],
] as const) {
  test(`${name}: neutral footer`, async ({ page }) => {
    await mockProcessor(page, () => ({ status: 200, body: { processor: null } }))
    await page.goto(path)
    await page.waitForTimeout(500)
    await expect(footer(page)).toHaveText('Powered by Open Lines')
  })
}

test('API unavailable: neutral footer', async ({ page }) => {
  await mockProcessor(page, () => ({ status: 503 }))
  await page.goto(`/payment-success?ref=${SQUARE_REF}`)
  await page.waitForTimeout(500)
  await expect(footer(page)).toHaveText('Powered by Open Lines')
})

test('an unexpected answer is not shown', async ({ page }) => {
  await mockProcessor(page, () => ({ status: 200, body: { processor: 'paypal' } }))
  await page.goto(`/payment-success?session_id=${STRIPE_SESSION}`)
  await page.waitForTimeout(500)
  await expect(footer(page)).toHaveText('Powered by Open Lines')
})
