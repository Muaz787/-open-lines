// Guards the homepage and pricing page against unsupported claims coming back,
// and keeps every price and trial term tied to lib/plans.ts and the actual offer.
import { expect, test, type Page } from '@playwright/test'
import { PLANS } from '../src/lib/plans'

const REMOVED = [
  '45,000', '33,600', '2,800', 'Answer latency', '0Missed calls', 'Live right now',
  'new today', 'Shahid', 'Hartwell', 'learns from every', 'Smarter every call',
  'Turnover risk', 'join the waitlist', 'Cheaper than a missed call',
  'Save up to', 'every lead', 'Nothing slips',
]

async function open(page: Page, path: string) {
  await page.context().route('**/*', route =>
    route.request().url().startsWith('http://localhost') ? route.continue() : route.abort())
  await page.goto(path)
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(1000)
  return (await page.locator('body').textContent()) ?? ''
}

for (const path of ['/', '/pricing']) {
  test(`${path} has none of the removed claims`, async ({ page }) => {
    const text = await open(page, path)
    for (const claim of REMOVED) expect(text, claim).not.toContain(claim)
  })
}

for (const width of [360, 390, 768]) {
  test(`the comparison table fits at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await open(page, '/')
    const table = await page.locator('.cmp-table-wrap').boundingBox()
    const cells = page.locator('.cmp-ours')
    for (let i = 0; i < await cells.count(); i++) {
      const cell = await cells.nth(i).boundingBox()
      expect(cell!.x + cell!.width).toBeLessThanOrEqual(table!.x + table!.width + 1)
    }
    await page.locator('.cmp-table-wrap').screenshot({ path: `test-results/cmp-${width}.png` })
  })
}

for (const path of ['/salons', '/barbers']) {
  test(`${path} makes only supported claims and states the offer`, async ({ page }) => {
    const text = await open(page, path)
    const removed = [
      'Four out of five', '80%', 'answered in 1 ring', 'answers every call', 'Answers instantly',
      'never lose', 'Never lose', 'rarely realise', 'never guesses', 'no double-booking',
      'walk-in waits', 'how busy you are', 'who’s in today', 'Who’s in today', 'reminder',
      'Studio Luxe', 'Fade Co.', 'every call gets', 'Works with your booking software',
    ]
    for (const claim of removed) expect(text, claim).not.toContain(claim)
    expect(text).toContain('Card required')
    expect(text).toContain(`from $${PLANS[0].price} CAD a month plus tax`)
    expect(text).toContain('under 10 minutes')
    expect(text).toContain('sample data')
    expect(text).toContain('virtual receptionist')
  })
}

test('every homepage industry example is labelled as sample data', async ({ page }) => {
  await open(page, '/')
  for (const label of ['Realtors', 'Dental', 'Legal', 'Beauty']) {
    await page.getByRole('button', { name: label, exact: true }).click()
    await expect(page.locator('.ind-head')).toContainText('sample data')
    await expect(page.locator('.ind-head .live-dot')).toHaveCount(0)
  }
})

test('homepage pricing matches the plans and states the trial terms', async ({ page }) => {
  const text = await open(page, '/')
  const starter = PLANS[0]
  expect(text).toContain(`$${starter.price} CAD a month plus tax`)
  expect(text).toContain(`${starter.minutes} minutes included`)
  expect(text).toContain('$0.69 CAD per minute')
  expect(text).toContain('Card required')
  expect(text).toContain('includes 60 minutes')
  expect(text).toContain(`From $${starter.priceYear} CAD + tax`)
  expect(text).toContain('$43,680 CAD*')
  expect(text).toContain('NOC 14101')
  expect(text).toContain('under 10 minutes')
})

test('pricing page states the currency and describes the live trial', async ({ page }) => {
  const text = await open(page, '/pricing')
  expect(text).toContain('Prices in CAD, plus tax')
  expect(text).toContain('7-day free trial')
  expect(text).toContain('A card is required')
})

test('marketing pages show the legal company name, support contact and fire no conversion', async ({ page }) => {
  for (const path of ['/', '/salons']) {
    const text = await open(page, path)
    expect(text).toContain('Open Lines Technologies Inc.')
    expect(text).toContain('support@openlines.ai')
    const conversions = await page.evaluate(() => {
      const layer = (window as unknown as { dataLayer?: ArrayLike<unknown>[] }).dataLayer ?? []
      return Array.from(layer).map(e => Array.from(e)).filter(e => e[1] === 'conversion').length
    })
    expect(conversions).toBe(0)
  }
})
