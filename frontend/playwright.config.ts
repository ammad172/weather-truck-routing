import { defineConfig } from '@playwright/test'

// End-to-end tests run the real stack: Django (with the HERE key in backend/.env) plus Vite.
// They call the live HERE and Open-Meteo APIs, so they're a smoke test, not part of the unit suite.
const python = process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python'

export default defineConfig({
  testDir: 'e2e',
  timeout: 90_000,
  expect: { timeout: 30_000 },
  use: {
    baseURL: 'http://127.0.0.1:5173',
    // A non-UTC zone, so the test proves times are shown in local time.
    timezoneId: 'America/Chicago',
    locale: 'en-US',
    viewport: { width: 1440, height: 900 },
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
