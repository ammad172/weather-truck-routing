import { expect, planDallasToDenver, test, trackErrors } from './support.ts'

test('plan a trip and explore the routes', async ({ page }, testInfo) => {
  const consoleErrors = trackErrors(page)

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Weather-Aware Truck Routing' })).toBeVisible()
  await expect(page.getByText('Times are shown in your timezone (America/Chicago)')).toBeVisible()

  await planDallasToDenver(page)

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

  // Changing the interval re-plans automatically, with about half the checkpoints at 50 mi.
  // (50 mi rather than 10: its weather cells are all among the 25 mi plan's, so the recorded
  // fixtures cover it without another ~110 Open-Meteo locations.)
  const replan = page.waitForResponse((r) => r.url().endsWith('/api/plan'))
  await page.getByText('50 mi', { exact: true }).click()
  expect((await replan).status()).toBe(200)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.locator('.trip-summary')).toContainText('checkpoint every 50 mi')
  await expect.poll(() => rows.count()).toBeLessThan(at25 * 0.6)

  expect(consoleErrors).toEqual([])
})
