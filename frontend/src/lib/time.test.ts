import { describe, expect, it } from 'vitest'
import {
  formatDateTime,
  formatDuration,
  formatTime,
  localInputToIso,
  localZoneName,
  nextHour,
  toLocalInputValue,
} from './time'

// vitest.config.ts runs these in America/Chicago (UTC-5 in October, UTC-6 in January).

describe('local timezone', () => {
  it('runs in a non-UTC zone', () => {
    expect(localZoneName()).toBe('America/Chicago')
  })

  it('shows API times (UTC) in local time with the zone name', () => {
    expect(formatTime('2026-10-13T13:00:00+00:00')).toMatch(/^8:00\s?AM CDT$/)
    expect(formatDateTime('2026-10-14T01:22:53+00:00')).toMatch(/Tue, Oct 13, 8:22\s?PM CDT/)
  })

  it('switches to standard time in winter', () => {
    expect(formatTime('2027-01-13T13:00:00+00:00')).toMatch(/^7:00\s?AM CST$/)
  })
})

describe('departure input', () => {
  it('sends local wall time with the local offset', () => {
    expect(localInputToIso('2026-10-13T08:00')).toBe('2026-10-13T08:00:00-05:00')
    expect(localInputToIso('2027-01-13T08:00')).toBe('2027-01-13T08:00:00-06:00')
  })

  it('round-trips the same instant', () => {
    const iso = localInputToIso('2026-10-13T08:30')
    expect(new Date(iso).toISOString()).toBe('2026-10-13T13:30:00.000Z')
  })

  it('formats a Date for the input in local time', () => {
    expect(toLocalInputValue(new Date('2026-10-13T13:05:00Z'))).toBe('2026-10-13T08:05')
  })

  it('rejects garbage', () => {
    expect(() => localInputToIso('not a date')).toThrow()
  })

  it('defaults to the next whole local hour', () => {
    expect(toLocalInputValue(nextHour(new Date('2026-10-13T13:20:00Z')))).toBe('2026-10-13T09:00')
  })
})

describe('durations', () => {
  it('formats hours and zero-padded minutes', () => {
    expect(formatDuration(44573)).toBe('12h 23m')
    expect(formatDuration(3600 + 5 * 60)).toBe('1h 05m')
  })
})
