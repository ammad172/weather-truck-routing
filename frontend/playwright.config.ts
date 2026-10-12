import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from '@playwright/test'

// End-to-end tests run the real stack, Django plus Vite, on their own ports.
//
//   npm run e2e               replay: HERE and Open-Meteo answered from e2e/fixtures, no live calls
//   E2E_RECORD=1 npm run e2e  record: the same specs against the live APIs, saving new fixtures
//   E2E_LIVE=1 npm run e2e    live smoke test only (e2e/live.spec.ts), live APIs, nothing saved
//
// Replay freezes "now" (in Django and in the browser) to the recording time, because the
// recorded requests contain the departure hour and the forecast window.
const mode = process.env.E2E_LIVE ? 'live' : process.env.E2E_RECORD ? 'record' : 'replay'
const fixtures = resolve(import.meta.dirname, 'e2e/fixtures')
const recording = resolve(fixtures, 'recording.json')

if (mode === 'record' && !process.env.E2E_FROZEN_NOW) {
  // A fresh recording, frozen at the current minute. Workers inherit E2E_FROZEN_NOW, so this
  // runs once per `playwright test`.
  const now = new Date()
  now.setSeconds(0, 0)
  process.env.E2E_FROZEN_NOW = now.toISOString()
  rmSync(fixtures, { recursive: true, force: true })
  mkdirSync(fixtures, { recursive: true })
  writeFileSync(recording, JSON.stringify({ now: process.env.E2E_FROZEN_NOW }, null, 2) + '\n')
}
if (mode === 'replay' && !process.env.E2E_FROZEN_NOW) {
  if (!existsSync(recording)) throw new Error('No e2e fixtures yet: record them once with E2E_RECORD=1 npm run e2e')
  process.env.E2E_FROZEN_NOW = JSON.parse(readFileSync(recording, 'utf8')).now
}

const python = process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python'
const API_PORT = 8001
const WEB_PORT = 5174

const backendEnv: Record<string, string> = {
  DJANGO_DEBUG: '1',
  // Every run starts with an empty cache, so live runs really call the APIs and replays are hermetic.
  CACHE_BACKEND: 'locmem',
  ...(mode === 'live'
    ? {}
    : {
        HTTP_FIXTURES: mode,
        HTTP_FIXTURES_DIR: fixtures,
        FROZEN_NOW: process.env.E2E_FROZEN_NOW!.replace('Z', '+00:00'),
      }),
  // Replay needs no key; a fake one means even a request that somehow went out would be refused.
  ...(mode === 'replay' ? { HERE_API_KEY: 'replay-mode-has-no-key' } : {}),
}

export default defineConfig({
  testDir: 'e2e',
  testMatch: mode === 'live' ? 'live.spec.ts' : '*.spec.ts',
  testIgnore: mode === 'live' ? [] : ['live.spec.ts'],
  // One at a time: in record and live modes the specs plan the same trip, so the second is served
  // from the server's cache instead of doubling the Open-Meteo calls (free tier: 600 locations a minute).
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 30_000 },
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    // A non-UTC zone, so the tests prove times are shown in local time.
    timezoneId: 'America/Chicago',
    locale: 'en-US',
    viewport: { width: 1440, height: 900 },
    // Headless Chromium draws WebGL in software (SwiftShader), roughly 30 ms a frame for the map.
    // E2E_GPU=1 uses the real GPU instead, for timings closer to what users see (Windows: D3D11).
    launchOptions: process.env.E2E_GPU ? { args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'] } : {},
  },
  webServer: [
    {
      command: `${python} manage.py runserver 127.0.0.1:${API_PORT} --noreload`,
      cwd: '../backend',
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: backendEnv,
      // Never reuse a server someone else started: it could be making live calls.
      reuseExistingServer: false,
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { API_PROXY_TARGET: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
    },
  ],
})
