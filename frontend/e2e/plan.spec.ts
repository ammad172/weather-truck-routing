import { expect, type Page, test } from '@playwright/test'

async function pickPlace(page: Page, label: string, query: string, expected: RegExp) {
  const input = page.getByRole('combobox', { name: label })
  await input.fill(query)
  const option = page.getByRole('option', { name: expected }).first()
  await option.click()
  await expect(input).toHaveValue(expected)
}

test('plan a trip and explore the routes', async ({ page }, testInfo) => {
  // Any app error fails the test. The one exception: the third-party basemap asks for a few
  // glyph ranges (fonts for rare scripts) that OpenFreeMap doesn't host; those 404s are harmless.
  const basemapGlyph = /tiles\.openfreemap\.org\/fonts\//
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource')) consoleErrors.push(message.text().split('\n')[0])
  })
  page.on('pageerror', (error) => consoleErrors.push(error.message.split('\n')[0]))
  page.on('response', (response) => {
    if (response.status() >= 400 && !basemapGlyph.test(response.url())) consoleErrors.push(`HTTP ${response.status()} ${response.url()}`)
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Weather-Aware Truck Routing' })).toBeVisible()
  await expect(page.getByText('Times are shown in your timezone (America/Chicago)')).toBeVisible()

  await pickPlace(page, 'From', 'Dallas', /Dallas, TX/)
  await pickPlace(page, 'To', 'Denver', /Denver, CO/)
  await page.getByLabel('Load weight').fill('42000')
  await page.getByRole('button', { name: 'Plan routes' }).click()

  // Recommendation and route cards.
  await expect(page.getByText(/^Recommended: Route [A-C]$/)).toBeVisible()
  // The map really rendered the routes (a WebGL canvas with our route layers loaded).
  await expect
    .poll(() => page.evaluate(() => document.querySelectorAll('.maplibregl-canvas').length))
    .toBe(1)
  const cards = page.getByRole('button', { name: /^Route [A-C]/ })
  await expect(cards).toHaveCount(3)
  await expect(page.getByRole('button', { name: /Recommended/ })).toHaveAttribute('aria-pressed', 'true')

  // Times are local (Chicago), never UTC.
  const summary = page.locator('.trip-summary')
  await expect(summary).toContainText(/C[DS]T/)
  await expect(page.locator('.sidebar')).not.toContainText('UTC')

  // Checkpoint table for the selected route; 25 mi default interval.
  const rows = page.locator('.checkpoints tbody tr')
  const at25 = await rows.count()
  expect(at25).toBeGreaterThan(20)
  await expect(rows.first()).toContainText(/C[DS]T/)

  await page.screenshot({ path: testInfo.outputPath('plan.png') })

  // Selecting another route updates the selection and its checkpoint table.
  const other = cards.filter({ hasNot: page.getByText('Recommended') }).first()
  const otherName = (await other.locator('.route-name').textContent())!
  await other.click()
  await expect(other).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('heading', { name: `${otherName} checkpoints` })).toBeVisible()

  // A checkpoint row opens its popup on the map, in local time.
  await rows.nth(5).click()
  const popup = page.locator('.checkpoint-popup')
  await expect(popup).toBeVisible()
  await expect(popup).toContainText(/Arrives .* C[DS]T/)
  await page.screenshot({ path: testInfo.outputPath('checkpoint.png') })

  // Changing the interval re-plans automatically, with more checkpoints at 10 mi.
  // (If this fails with an alert about a rate limit, Open-Meteo's free 600-locations/minute
  // limit was hit by back-to-back cold runs; wait a minute and re-run.)
  const replan = page.waitForResponse((r) => r.url().endsWith('/api/plan'))
  await page.getByText('10 mi', { exact: true }).click()
  expect((await replan).status()).toBe(200)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.locator('.trip-summary')).toContainText('checkpoint every 10 mi')
  await expect.poll(() => rows.count()).toBeGreaterThan(at25 * 2)

  expect(consoleErrors).toEqual([])
})
