import { expect, planDallasToDenver, test } from './support.ts'

// A phone: the map is on top of the page, with the timeline below it rather than over it.
test.use({ viewport: { width: 390, height: 844 } })

test('on a phone the timeline sits below the map and the whole trip fits', async ({ page }, testInfo) => {
  await page.goto('/')
  await planDallasToDenver(page)
  await expect(page.getByText(/^Recommended: Route [A-C]$/)).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, 0))

  const map = (await page.getByRole('region', { name: 'Route map' }).boundingBox())!
  const timeline = (await page.getByRole('region', { name: 'Forecast timeline' }).boundingBox())!
  expect(timeline.y).toBeGreaterThanOrEqual(map.y + map.height - 1)

  // Both ends of the trip are inside the map, clear of the legend.
  const legend = (await page.getByRole('region', { name: 'Map legend' }).boundingBox())!
  await page.waitForTimeout(800) // fitBounds animation
  for (const label of ['Start', 'Destination']) {
    const marker = (await page.getByLabel(label, { exact: true }).boundingBox())!
    expect(marker.y).toBeGreaterThanOrEqual(map.y)
    expect(marker.y + marker.height).toBeLessThanOrEqual(map.y + map.height)
    expect(marker.x + marker.width).toBeLessThanOrEqual(map.x + map.width)
    const overlapsLegend = marker.y < legend.y + legend.height && marker.x < legend.x + legend.width
    expect(overlapsLegend).toBe(false)
  }
  await page.screenshot({ path: testInfo.outputPath('phone.png') })
})
