import { expect, test, type Page } from '@playwright/test'

// /payment-success footer. The API host is fake (playwright.config.ts); any request
// to it is recorded and refused, so nothing reaches a real backend, Stripe or Square.

async function recordApiCalls(page: Page) {
  const calls: string[] = []
  await page.route('http://api.test/**', route => {
    calls.push(route.request().url())
    return route.abort()
  })
  return calls
}

for (const [name, path] of [
  ['Square return (bare redirect_url)', '/payment-success'],
  ['Stripe return (session_id)', '/payment-success?session_id=cs_test_a1B2c3D4e5F6g7H8'],
  ['direct visit', '/payment-success'],
  ['a made-up processor parameter', '/payment-success?processor=square'],
] as const) {
  test(`${name}: neutral footer, no processor named`, async ({ page }) => {
    const calls = await recordApiCalls(page)
    await page.goto(path)
    await expect(page.getByRole('heading', { name: 'Payment successful!' })).toBeVisible()
    await expect(page.getByText('Powered by Open Lines', { exact: true })).toBeVisible()
    await expect(page.getByText(/Stripe|Square/)).toHaveCount(0)
    await page.waitForTimeout(300)
    expect(calls).toEqual([])
  })
}
