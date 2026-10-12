import { describe, expect, it } from 'vitest'
import type { Checkpoint, RiskLevel } from '../api/types'
import { riskGradient, riskSpans } from './risk'

const cp = (mile: number, level: RiskLevel): Checkpoint => ({
  mile,
  level,
  segment_miles: 0,
  lat: 0,
  lon: 0,
  eta: '2026-10-13T13:00:00+00:00',
  forecast_hour: '2026-10-13T13:00:00+00:00',
  weather: { wind_mph: 0, rain_in_hr: 0, snow_in_hr: 0 },
  level_label: '',
  factor: null,
  load_adjusted: false,
})

describe('riskSpans', () => {
  it('splits halfway between checkpoints, as the backend counts risk miles', () => {
    expect(riskSpans([cp(0, 0), cp(50, 3), cp(100, 0)])).toEqual([
      { from: 0, to: 0.25, level: 0 },
      { from: 0.25, to: 0.75, level: 3 },
      { from: 0.75, to: 1, level: 0 },
    ])
  })

  it('merges neighbouring checkpoints with the same level', () => {
    expect(riskSpans([cp(0, 1), cp(25, 1), cp(50, 1), cp(100, 2)])).toEqual([
      { from: 0, to: 0.75, level: 1 },
      { from: 0.75, to: 1, level: 2 },
    ])
  })

  it('handles a single checkpoint and none', () => {
    expect(riskSpans([cp(0, 2)])).toEqual([{ from: 0, to: 1, level: 2 }])
    expect(riskSpans([])).toEqual([])
  })
})

describe('riskGradient', () => {
  it('builds a hard-edged step expression on line-progress', () => {
    expect(riskGradient([cp(0, 0), cp(50, 3), cp(100, 0)])).toEqual([
      'step',
      ['line-progress'],
      '#2f9e44',
      0.25,
      '#d6332a',
      0.75,
      '#2f9e44',
    ])
  })

  it('is a single colour for a uniform route, still with the one stop `step` requires', () => {
    expect(riskGradient([cp(0, 0), cp(100, 0)])).toEqual(['step', ['line-progress'], '#2f9e44', 1, '#2f9e44'])
    expect(riskGradient([])).toEqual(['step', ['line-progress'], '#2f9e44', 1, '#2f9e44'])
  })

  it('always has an input, a base output and at least one stop/output pair', () => {
    for (const checkpoints of [[], [cp(0, 1)], [cp(0, 0), cp(50, 3), cp(100, 0)]]) {
      const expression = riskGradient(checkpoints)
      expect(expression.length).toBeGreaterThanOrEqual(5)
      expect((expression.length - 3) % 2).toBe(0)
    }
  })
})
