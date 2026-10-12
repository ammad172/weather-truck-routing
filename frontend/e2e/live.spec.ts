import { expect, planDallasToDenver, test, trackErrors } from './support.ts'

// Live smoke test: the real HERE and Open-Meteo APIs, at the real time. Runs only with
// E2E_LIVE=1 (see playwright.config.ts). One plan costs about 350 Open-Meteo locations of the
// free tier's 600 a minute, so it's kept to a single trip.

test('a live plan comes back with routes, a recommendation and a heatmap', async ({ page }, testInfo) => {
  const errors = trackErrors(page)
  await page.goto('/')
  await planDallasToDenver(page)

  await expect(page.getByText(/^Recommended: Route [A-C]$/)).toBeVisible()
  await expect(page.getByRole('button', { name: /^Route [A-C]/ }).first()).toBeVisible()
  await expect(page.locator('.checkpoints tbody tr').first()).toContainText(/C[DS]T/)
  const timeline = page.getByRole('region', { name: 'Forecast timeline' })
  await expect(timeline.locator('.hour-strip li')).toHaveCount(49)
  await expect.poll(() => page.evaluate(() => (window as any).__map.querySourceFeatures('forecast-heatmap').length)).toBeGreaterThan(50)

  await page.screenshot({ path: testInfo.outputPath('live.png') })
  expect(errors).toEqual([])
})
