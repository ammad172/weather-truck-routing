import { describe, expect, it } from 'vitest'
import type { Checkpoint, Route } from '../api/types'
import { pointAlong, truckPosition } from './truck'

const cp = (mile: number, eta: string): Checkpoint => ({
  mile,
  eta,
  segment_miles: 0,
  lat: 0,
  lon: 0,
  forecast_hour: eta,
  weather: { wind_mph: 0, rain_in_hr: 0, snow_in_hr: 0 },
  level: 0,
  level_label: 'Low',
  factor: null,
  load_adjusted: false,
})

// A straight east-west line along the equator: 0 -> 2 degrees, checkpoints at miles 0, 50, 100.
const route = {
  id: 'A',
  geometry: [
    [0, 0],
    [1, 0],
    [2, 0],
  ],
  checkpoints: [cp(0, '2026-10-13T12:00:00Z'), cp(50, '2026-10-13T13:00:00Z'), cp(100, '2026-10-13T15:00:00Z')],
} as Route

const at = (iso: string) => Date.parse(iso)

describe('truckPosition', () => {
  it('waits at the start before departure', () => {
    expect(truckPosition(route, at('2026-10-13T11:00:00Z'))).toEqual({ at: [0, 0], mile: 0, status: 'not-departed' })
  })

  it('is still at the start at the departure instant', () => {
    expect(truckPosition(route, at('2026-10-13T12:00:00Z'))).toEqual({ at: [0, 0], mile: 0, status: 'not-departed' })
  })

  it('interpolates the mile between checkpoint ETAs', () => {
    const p = truckPosition(route, at('2026-10-13T14:00:00Z'))!
    expect(p.mile).toBe(75)
    expect(p.status).toBe('en-route')
    expect(p.at[0]).toBeCloseTo(1.5)
  })

  it('stays at the destination after arrival', () => {
    expect(truckPosition(route, at('2026-10-14T00:00:00Z'))).toMatchObject({ at: [2, 0], mile: 100, status: 'arrived' })
  })

  it('handles a route without checkpoints', () => {
    expect(truckPosition({ ...route, checkpoints: [] }, 0)).toBeNull()
  })
})

describe('pointAlong', () => {
  it('measures by distance, not by vertex count', () => {
    const line: [number, number][] = [
      [0, 0],
      [0.5, 0],
      [3, 0],
    ]
    expect(pointAlong(line, 0.5)[0]).toBeCloseTo(1.5)
    expect(pointAlong(line, 0)).toEqual([0, 0])
    expect(pointAlong(line, 1)).toEqual([3, 0])
  })
})
