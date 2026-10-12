import { defineConfig } from '@playwright/test'

// End-to-end tests run the real stack: Django (with the HERE key in backend/.env) plus Vite.
// They call the live HERE and Open-Meteo APIs, so they're a smoke test, not part of the unit suite.
const python = process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python'

export default defineConfig({
  testDir: 'e2e',
  // One at a time: the specs plan the same trip, so the second is served from the server's weather
  // cache instead of doubling the Open-Meteo calls (free tier: 600 locations a minute).
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 30_000 },
  use: {
    baseURL: 'http://127.0.0.1:5173',
    // A non-UTC zone, so the test proves times are shown in local time.
    timezoneId: 'America/Chicago',
    locale: 'en-US',
    viewport: { width: 1440, height: 900 },
    // Headless Chromium draws WebGL in software (SwiftShader), roughly 30 ms a frame for the map.
    // E2E_GPU=1 uses the real GPU instead, for timings closer to what users see (Windows: D3D11).
    launchOptions: process.env.E2E_GPU ? { args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'] } : {},
  },
  webServer: [
    {
      command: `${python} manage.py runserver 127.0.0.1:8000 --noreload`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/health',
      env: { DJANGO_DEBUG: '1' },
      reuseExistingServer: true,
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 5173 --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: true,
    },
  ],
})
