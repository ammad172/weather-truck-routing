import type { Page } from '@playwright/test'
import { expect, planDallasToDenver, test, trackErrors } from './support.ts'

// The forecast heatmap, its slider and legend, on the same recorded trip as plan.spec.ts.

const HEATMAP = 'forecast-heatmap'

type MapProbe = {
  calls: { method: string; args: unknown[] }[]
  frames: number[]
}

/** Resolves once MapLibre has nothing left to load or render. */
const mapIdle = (page: Page) =>
  page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const map = (window as any).__map
        map.once('idle', () => resolve())
        map.triggerRepaint()
      }),
  )

const weightExpression = (page: Page) => page.evaluate((id) => (window as any).__map.getPaintProperty(id, 'heatmap-weight'), HEATMAP)

test('heatmap slider updates the layer in place, even when dragged fast', async ({ page }, testInfo) => {
  const errors = trackErrors(page)

  await page.goto('/')
  // Before a plan: the route legend only, no timeline.
  await expect(page.getByRole('region', { name: 'Map legend' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Forecast timeline' })).toHaveCount(0)

  await planDallasToDenver(page)

  const timeline = page.getByRole('region', { name: 'Forecast timeline' })
  const slider = page.getByRole('slider', { name: 'Hours after departure' })
  const label = timeline.locator('.timeline-label')
  await expect(slider).toHaveValue('0')
  await expect(label).toHaveText(/^\+0 h after departure · \w{3}, \d{1,2}:\d{2} [AP]M C[DS]T$/)
  for (const tick of ['Departure', '+12 h', '+24 h', '+36 h', '+48 h']) await expect(timeline.getByText(tick, { exact: true })).toBeVisible()
  await expect(timeline.locator('.hour-strip li')).toHaveCount(49)
  await expect(page.locator('.truck-marker')).toHaveCount(1)

  // The heatmap layer has the plan's points, sits under the routes, and starts at risk, hour 0.
  await expect.poll(() => page.evaluate((id) => (window as any).__map.querySourceFeatures(id).length, HEATMAP)).toBeGreaterThan(50)
  const order = await page.evaluate(() => (window as any).__map.getStyle().layers.map((l: { id: string }) => l.id) as string[])
  expect(order.indexOf(HEATMAP)).toBeLessThan(order.findIndex((id) => id.startsWith('route-')))
  expect(await weightExpression(page)).toEqual(['get', 'risk0'])
  await mapIdle(page)
  await page.screenshot({ path: testInfo.outputPath('1-heatmap-departure.png') })

  // Instrument the map from here on: every layer/source call, and frame timestamps.
  await page.evaluate((id) => {
    const map = (window as any).__map
    const probe: MapProbe = { calls: [], frames: [] }
    ;(window as any).__probe = probe
    for (const method of ['addLayer', 'removeLayer', 'addSource', 'removeSource', 'setPaintProperty', 'setLayoutProperty', 'setFilter']) {
      const original = map[method].bind(map)
      map[method] = (...args: unknown[]) => {
        probe.calls.push({ method, args: JSON.parse(JSON.stringify(args)) })
        return original(...args)
      }
    }
    const source = map.getSource(id)
    const setData = source.setData.bind(source)
    source.setData = (...args: unknown[]) => {
      probe.calls.push({ method: 'setData', args: [] })
      return setData(...args)
    }
    const tick = (t: number) => {
      probe.frames.push(t)
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }, HEATMAP)
  const requests: string[] = []
  page.on('request', (r) => requests.push(r.url()))

  // 1. A fast mouse drag: down on the thumb, sweep right, left and right again in small steps.
  const box = (await slider.boundingBox())!
  const thumb = 7 // half the thumb width; the thumb's centre travels from box.x + 7 to box.x + width - 7
  const xAt = (hour: number) => box.x + thumb + ((box.width - 2 * thumb) * hour) / 48
  const y = box.y + box.height / 2
  const now = () => page.evaluate(() => performance.now())
  const dragStart = await now()
  await page.mouse.move(xAt(0), y)
  await page.mouse.down()
  await page.mouse.move(xAt(48), y, { steps: 80 })
  await page.mouse.move(xAt(3), y, { steps: 80 })
  await page.mouse.move(xAt(40), y, { steps: 80 })
  await page.mouse.move(xAt(30), y, { steps: 20 })
  await page.mouse.up()
  const dragEnd = await now()
  await expect(slider).toHaveValue('30')
  await expect(label).toHaveText(/^\+30 h after departure · /)
  await expect.poll(() => weightExpression(page)).toEqual(['get', 'risk30'])

  // 2. Harder than any hand: 200 input events in one task, no awaits between them.
  await slider.evaluate((input: HTMLInputElement) => {
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    for (let i = 0; i < 200; i++) {
      setValue.call(input, String((i * 7) % 49))
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
    setValue.call(input, '17')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await expect(slider).toHaveValue('17')
  await expect(label).toHaveText(/^\+17 h after departure · /)
  await expect.poll(() => weightExpression(page)).toEqual(['get', 'risk17'])
  await mapIdle(page)

  // While all that was going on: no layer or source was created, removed or refilled, the only
  // paint change was the heatmap's weight, and nothing went over the network.
  const probe = await page.evaluate(() => (window as any).__probe as MapProbe)
  const other = probe.calls.filter((c) => !(c.method === 'setPaintProperty' && c.args[0] === HEATMAP && c.args[1] === 'heatmap-weight'))
  expect(other).toEqual([])
  const weightCalls = probe.calls.length
  expect(weightCalls).toBeGreaterThan(48)
  expect(requests).toEqual([])
  const longestGap = (frames: number[]) => Math.max(...frames.slice(1).map((t, i) => t - frames[i]))
  const dragFrames = probe.frames.filter((t) => t >= dragStart && t <= dragEnd)
  const longestDragFrame = longestGap(dragFrames)
  const burstFrame = longestGap(probe.frames.filter((t) => t > dragEnd))
  testInfo.annotations.push({
    type: 'timing',
    description:
      `mouse drag: 260 moves in ${(dragEnd - dragStart).toFixed(0)} ms, ${dragFrames.length} frames, longest frame ${longestDragFrame.toFixed(0)} ms; ` +
      `200-event burst: longest frame ${burstFrame.toFixed(0)} ms; ${weightCalls} weight updates in all`,
  })
  console.log(testInfo.annotations.at(-1)!.description)
  // The page kept painting through the drag. Generous: headless Chromium renders WebGL in software.
  expect(longestDragFrame).toBeLessThan(500)
  await page.screenshot({ path: testInfo.outputPath('2-heatmap-after-fast-drag.png') })

  // The keyboard works too: End jumps to +48 h, where the truck has arrived.
  await slider.focus()
  await page.keyboard.press('End')
  await expect(label).toHaveText(/^\+48 h after departure · /)
  await expect(timeline.locator('.timeline-truck')).toHaveText(/^Route [A-C]: arrived$/)
  await page.keyboard.press('Home')
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await expect(label).toHaveText(/^\+2 h after departure · /)

  // Mid-trip the truck is on the road.
  await slider.fill('6')
  await expect(timeline.locator('.timeline-truck')).toHaveText(/^Route [A-C]: truck at mile \d+$/)
  await expect(page.locator('.truck-marker')).toBeVisible()
  await mapIdle(page)
  await page.screenshot({ path: testInfo.outputPath('3-truck-mid-trip.png') })

  // The variable toggle repoints the same layer, and the legend shows that variable's bands.
  const before = (await page.evaluate(() => (window as any).__probe.calls.length)) as number
  await timeline.getByText('Wind', { exact: true }).click()
  await expect.poll(() => weightExpression(page)).toEqual(['get', 'wind6'])
  const legend = page.getByRole('region', { name: 'Map legend' })
  await expect(legend).toContainText('mph')
  await expect(legend.getByRole('listitem', { name: 'Moderate: 25–35 mph' })).toBeVisible()
  const toggleCalls = await page.evaluate((n) => (window as any).__probe.calls.slice(n), before)
  expect(toggleCalls).toEqual([{ method: 'setPaintProperty', args: [HEATMAP, 'heatmap-weight', ['get', 'wind6']] }])
  await mapIdle(page)
  await page.screenshot({ path: testInfo.outputPath('4-wind.png') })

  await timeline.getByText('Rain', { exact: true }).click()
  await expect.poll(() => weightExpression(page)).toEqual(['get', 'rain6'])
  await expect(legend).toContainText('in/hr')
  await timeline.getByText('Risk', { exact: true }).click()

  // Play steps forward an hour at a time; pause stops it.
  await page.getByRole('button', { name: 'Play forecast' }).click()
  await expect(label).toHaveText(/^\+8 h after departure · /, { timeout: 5000 })
  await page.getByRole('button', { name: 'Pause forecast' }).click()
  const paused = await slider.inputValue()
  await page.waitForTimeout(1500)
  expect(await slider.inputValue()).toBe(paused)
  expect(await weightExpression(page)).toEqual(['get', `risk${paused}`])

  // The worst hour on the strip, where the heatmap should show that level somewhere.
  const titles = await timeline.locator('.hour-strip li').evaluateAll((cells) => cells.map((c) => c.getAttribute('title') ?? ''))
  const rank = ['Low', 'Moderate', 'High', 'Severe', 'No Travel']
  const levelOf = (title: string) => rank.findIndex((name) => title.endsWith(`worst ${name}`))
  const worstHour = titles.reduce((best, title, h) => (levelOf(title) > levelOf(titles[best]) ? h : best), 0)
  await slider.fill(String(worstHour))
  await expect(label).toHaveText(new RegExp(`^\\+${worstHour} h after departure · `))
  await mapIdle(page)
  testInfo.annotations.push({ type: 'worst hour', description: titles[worstHour] })
  await page.screenshot({ path: testInfo.outputPath('5-worst-hour.png') })

  expect(requests.filter((url) => url.includes('/api/'))).toEqual([])
  expect(errors).toEqual([])
})
