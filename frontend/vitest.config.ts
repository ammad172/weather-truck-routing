import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    // Run in a non-UTC zone with DST so local-time formatting is really exercised.
    env: { TZ: 'America/Chicago' },
  },
})
