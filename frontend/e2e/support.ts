import { test as base, expect, type Page } from '@playwright/test'

/**
 * The browser's clock, frozen to the fixture recording time in replay and record modes (see
 * playwright.config.ts), so the default departure matches the recorded requests. Timers still run.
 */
export const test = base.extend({
  page: async ({ page }, run) => {
    const frozen = process.env.E2E_FROZEN_NOW
    if (frozen && !process.env.E2E_LIVE) await page.clock.setFixedTime(new Date(frozen))
    await run(page)
  },
})

export { expect }

export async function pickPlace(page: Page, label: string, query: string, expected: RegExp) {
  const input = page.getByRole('combobox', { name: label })
  await input.fill(query)
  await page.getByRole('option', { name: expected }).first().click()
  await expect(input).toHaveValue(expected)
}

/**
 * Collects app errors: console errors, page errors and failed responses. The one exception is the
 * third-party basemap asking for glyph ranges (fonts for rare scripts) OpenFreeMap doesn't host.
 */
export function trackErrors(page: Page): string[] {
  const basemapGlyph = /tiles\.openfreemap\.org\/fonts\//
  const errors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) errors.push(m.text().split('\n')[0])
  })
  page.on('pageerror', (e) => errors.push(e.message.split('\n')[0]))
  page.on('response', (r) => {
    if (r.status() >= 400 && !basemapGlyph.test(r.url())) errors.push(`HTTP ${r.status()} ${r.url()}`)
  })
  return errors
}

/** Plans Dallas → Denver with a 42,000 lb load (the recorded trip) and waits for the result. */
export async function planDallasToDenver(page: Page) {
  await pickPlace(page, 'From', 'Dallas', /Dallas, TX/)
  await pickPlace(page, 'To', 'Denver', /Denver, CO/)
  await page.getByLabel('Load weight').fill('42000')
  const planned = page.waitForResponse((r) => r.url().endsWith('/api/plan'))
  await page.getByRole('button', { name: 'Plan routes' }).click()
  // A 503 here in live or record mode is Open-Meteo's free-tier rate limit; wait and re-run.
  expect((await planned).status()).toBe(200)
}
