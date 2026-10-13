import type { Page } from '@playwright/test'
import { expect, pickPlace, test } from './support.ts'

// How the app reports failures. /api/plan is answered by the browser itself (page.route) with each
// failure; place suggestions still come from the recorded fixtures, so nothing calls a live API.

async function fillTrip(page: Page) {
  await page.goto('/')
  await pickPlace(page, 'From', 'Dallas', /Dallas, TX/)
  await pickPlace(page, 'To', 'Denver', /Denver, CO/)
}

const json = (status: number, body: unknown) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })

const cases = [
  {
    name: 'a dropped connection',
    reply: null, // the request never gets a response
    message: "Couldn't reach the server. Check your connection and try again.",
  },
  {
    name: 'From and To at the same place',
    reply: json(400, { detail: 'From and To are less than 1 mile apart. Choose two different places.' }),
    message: 'From and To are less than 1 mile apart.',
  },
  {
    name: 'a field error',
    reply: json(400, { departure: ["Departure can't be in the past."] }),
    message: "Departure: Departure can't be in the past.",
  },
  {
    name: 'no truck route',
    reply: json(422, { detail: 'HERE found no truck route between these places.' }),
    message: 'HERE found no truck route between these places.',
  },
  {
    name: 'a used-up weather quota',
    reply: json(503, { detail: "The free weather service's hourly limit has been reached. Please try again after the top of the hour." }),
    message: 'hourly limit has been reached',
  },
  {
    name: 'a proxy error page (not JSON)',
    reply: { status: 502, contentType: 'text/html', body: '<html><body>Bad Gateway</body></html>' },
    message: 'The server had a problem. Please try again.',
  },
]

for (const { name, reply, message } of cases) {
  test(`plan failure: ${name}`, async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (e) => pageErrors.push(e.message))
    await page.route('**/api/plan', (route) => (reply ? route.fulfill(reply) : route.abort('internetdisconnected')))
    await fillTrip(page)

    await page.getByRole('button', { name: 'Plan routes' }).click()
    const alert = page.getByRole('alert')
    await expect(alert).toContainText(message)
    // Nothing half-drawn, the form is usable again, and the app didn't crash.
    await expect(page.getByRole('region', { name: 'Forecast timeline' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Plan routes' })).toBeEnabled()
    expect(pageErrors).toEqual([])
  })
}

test('a failed re-plan keeps the previous routes and says so', async ({ page }, testInfo) => {
  let fail = false
  await page.route('**/api/plan', (route) =>
    fail ? route.fulfill(json(503, { detail: 'The free weather service is busy. Please wait about a minute and try again.' })) : route.continue(),
  )
  await fillTrip(page)
  await page.getByRole('button', { name: 'Plan routes' }).click()
  await expect(page.getByText(/^Recommended: Route [A-C]$/)).toBeVisible()

  fail = true
  await page.locator('form').getByText('50 mi', { exact: true }).click() // not the map's scale bar, which can read "50 mi" too
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('busy')
  await expect(alert).toContainText('The routes below are from your previous plan.')
  // The earlier plan (25 mi) is still on screen.
  await expect(page.getByText(/^Recommended: Route [A-C]$/)).toBeVisible()
  await expect(page.locator('.trip-summary')).toContainText('checkpoint every 25 mi')
  await page.screenshot({ path: testInfo.outputPath('replan-failed.png') })
})
