import { describe, expect, it } from 'vitest'
import type { Heatmap } from '../api/types'
import { bandLabels, bandOf, heatmapColor, heatmapFeatures, heatmapIntensity, heatmapRadius, heatSites, levelWeight, rgba, worstByHour } from './heatmap'

const heatmap = (overrides: Partial<Heatmap> = {}): Heatmap => ({
  start: '2026-10-13T13:00:00+00:00',
  hours: 2,
  cell_deg: 0.2,
  points: [
    [-97, 33],
    [-97, 40],
  ],
  risk: [
    [0, 1, null],
    [0, 3, 4],
  ],
  wind_mph: [
    [10, 30, null],
    [24.9, 45, 60],
  ],
  rain_in_hr: [
    [0, 0.1, null],
    [0, 1, 1.01],
  ],
  snow_in_hr: [
    [0, 0, null],
    [0.5, 3, 3.1],
  ],
  ...overrides,
})

describe('bandOf', () => {
  it('puts shared edges in the higher band, like the backend', () => {
    expect(bandOf('wind', 24.9)).toBe(0)
    expect(bandOf('wind', 25)).toBe(1)
    expect(bandOf('wind', 55)).toBe(4)
    expect(bandOf('rain', 0.25)).toBe(2)
    expect(bandOf('snow', 2)).toBe(3)
  })

  it('makes rain and snow No Travel only strictly above the top edge', () => {
    expect(bandOf('rain', 1)).toBe(3)
    expect(bandOf('rain', 1.01)).toBe(4)
    expect(bandOf('snow', 3)).toBe(3)
    expect(bandOf('snow', 3.1)).toBe(4)
  })
})

describe('heatmapFeatures', () => {
  it('stores a weight per variable and hour, with 0 for no forecast', () => {
    const [south, north] = heatmapFeatures(heatmap()).features
    // The northernmost point is the reference, so its weights are unscaled.
    expect(north.properties).toMatchObject({ risk0: 0.2, risk1: 0.8, risk2: 1, wind0: 0.2, wind1: 0.8, rain2: 1, snow0: 0.4 })
    expect(south.properties!.risk2).toBe(0)
    expect(south.properties!.wind2).toBe(0)
  })

  it('scales southern weights down to offset Mercator row spacing', () => {
    const [south] = heatmapFeatures(heatmap()).features
    const expected = Math.cos((40 * Math.PI) / 180) / Math.cos((33 * Math.PI) / 180)
    expect(south.properties!.risk1).toBeCloseTo(0.4 * expected, 3)
  })

  it('has hours + 1 frames per variable', () => {
    const [point] = heatmapFeatures(heatmap()).features
    expect(Object.keys(point.properties!)).toHaveLength(4 * 3)
  })
})

describe('calibration', () => {
  it('sums to the point weight inside a uniform grid, on and between cells', () => {
    // Numerically sum MapLibre's kernel over a grid of equal-weight points at zoom 6.
    const h = heatmap()
    const zoom = 6
    const radiusExpr = heatmapRadius(h) as unknown as [string, unknown, unknown, number, number, number, number]
    const radius = radiusExpr[4] * 2 ** zoom
    const intensity = heatmapIntensity(h)
    const sx = (h.cell_deg * 512 * 2 ** zoom) / 360
    const sy = sx / Math.cos((40 * Math.PI) / 180)
    const weight = 0.6
    const densityAt = (x: number, y: number) => {
      let density = 0
      for (let i = -20; i <= 20; i++)
        for (let j = -20; j <= 20; j++) {
          const d = Math.hypot(i * sx - x, j * sy - y) / radius
          density += weight * intensity * (1 / Math.sqrt(2 * Math.PI)) * Math.exp(-4.5 * d * d)
        }
      return density
    }
    // On a cell, between two rows, and in the middle of four cells: within 4%, well inside a
    // colour's flat stretch on the ramp (+-0.06).
    for (const [x, y] of [
      [0, 0],
      [0, sy / 2],
      [sx / 2, sy / 2],
    ])
      expect(Math.abs(densityAt(x, y) / weight - 1)).toBeLessThan(0.04)
  })

  it('grows the radius by 2x per zoom level', () => {
    const [, , , z0, r0, z12, r12] = heatmapRadius(heatmap()) as unknown as number[]
    expect(z0).toBe(0)
    expect(z12).toBe(12)
    expect(r12 / r0).toBe(4096)
  })
})

describe('lone hazards', () => {
  // An 11 x 11 lattice at 0.2 deg around (40N, 97W), all Low except one Severe cell.
  const size = 11
  const points: [number, number][] = []
  for (let i = 0; i < size; i++) for (let j = 0; j < size; j++) points.push([-98 + j * 0.2, 39 + i * 0.2])
  const centre = Math.floor((size * size) / 2)
  const edge = 5 // the middle of the bottom row: the corridor's edge
  const withSevereAt = (cell: number) =>
    heatmap({
      hours: 0,
      points,
      risk: points.map((_, p) => [p === cell ? 3 : 0]),
      wind_mph: points.map(() => [0]),
      rain_in_hr: points.map(() => [0]),
      snow_in_hr: points.map(() => [0]),
    })
  const lone = withSevereAt(centre)

  /** Density MapLibre would compute at a lon/lat, at zoom 7, from the features' weights. */
  function densityAt(lon: number, lat: number, h: Heatmap = lone): number {
    const zoom = 7
    const world = 512 * 2 ** zoom
    const project = ([x, y]: number[]) => [((x + 180) / 360) * world, (world / (2 * Math.PI)) * Math.log(Math.tan(Math.PI / 4 + (y * Math.PI) / 360))]
    const radius = (heatmapRadius(h) as unknown as number[])[4] * 2 ** zoom
    const intensity = heatmapIntensity(h)
    const [px, py] = project([lon, lat])
    return heatmapFeatures(h).features.reduce((sum, f) => {
      const [fx, fy] = project(f.geometry.coordinates)
      const d = Math.hypot(fx - px, fy - py) / radius
      return sum + (f.properties!.risk0 as number) * intensity * (1 / Math.sqrt(2 * Math.PI)) * Math.exp(-4.5 * d * d)
    }, 0)
  }
  /** The level whose weight is nearest the density (Low is 0.2, so ~0.197 is Low too). */
  const bandAt = (density: number) => Math.max(0, Math.round(density * 5 - 1))

  it('spreads a lone hazard to its neighbours', () => {
    const near = heatSites(lone)[centre].from
    expect(near).toHaveLength(9)
    const weights = heatmapFeatures(lone).features.map((f) => f.properties!.risk0 as number)
    // Severe is 0.8 before the latitude scaling (at most 3% on this 2-degree grid).
    expect(near.every((n) => weights[n] > 0.77)).toBe(true)
    expect(weights[0]).toBeLessThan(0.21)
  })

  it('still reads as Severe at its own cell on the map', () => {
    const [lon, lat] = points[centre]
    expect(bandAt(densityAt(lon, lat))).toBe(3)
  })

  it('reads as Severe on the corridor edge too, thanks to the ghost ring', () => {
    const [lon, lat] = points[edge]
    expect(bandAt(densityAt(lon, lat, withSevereAt(edge)))).toBe(3)
  })

  it('rings the corridor with ghosts that copy the worst level next to them', () => {
    const sites = heatSites(lone)
    // An 11 x 11 block has a ring of 13 x 13 - 11 x 11 = 48 ghost cells.
    expect(sites.filter((s) => s.point === null)).toHaveLength(48)
    const below = sites.find((s) => s.point === null && s.at[0] === points[edge][0] && s.at[1] === 38.8)!
    expect(below.from).toEqual([4, 5, 6])
  })

  it('leaves ghosts next to Low cells empty, so the clear corridor keeps a soft edge', () => {
    const features = heatmapFeatures(withSevereAt(edge)).features
    const ghostAt = (lon: number, lat: number) =>
      features.find((f) => f.geometry.coordinates[0] === lon && f.geometry.coordinates[1] === lat)!.properties!.risk0
    expect(ghostAt(points[edge][0], 38.8)).toBeGreaterThan(0.77) // beside the Severe cell
    expect(ghostAt(points[0][0], 38.8)).toBe(0) // beside Low cells only
  })

  it('reads as Low two cells away, and the Low field stays Low between cells', () => {
    const [lon, lat] = points[centre]
    expect(bandAt(densityAt(lon + 0.4, lat + 0.4))).toBe(0)
    expect(bandAt(densityAt(lon - 0.7, lat + 0.5))).toBe(0)
  })
})

describe('heatmapColor', () => {
  it('has ascending density stops from transparent to No Travel', () => {
    const expr = heatmapColor() as unknown as unknown[]
    const stops = expr.slice(3).filter((_, i) => i % 2 === 0) as number[]
    expect(stops[0]).toBe(0)
    expect(stops.at(-1)).toBe(1)
    for (let i = 1; i < stops.length; i++) expect(stops[i]).toBeGreaterThan(stops[i - 1])
  })

  it('is flat around each level weight', () => {
    const expr = heatmapColor() as unknown as unknown[]
    const pairs: [number, string][] = []
    for (let i = 3; i < expr.length; i += 2) pairs.push([expr[i] as number, expr[i + 1] as string])
    const colourAt = (density: number) => pairs.filter(([d]) => d <= density).at(-1)![1]
    expect(colourAt(levelWeight(3) - 0.05)).toBe(colourAt(levelWeight(3) + 0.05))
    expect(colourAt(levelWeight(3))).toContain('214, 51, 42')
  })
})

describe('worstByHour', () => {
  it('takes the worst level in the corridor each hour', () => {
    expect(worstByHour(heatmap(), 'risk')).toEqual([0, 3, 4])
    expect(worstByHour(heatmap(), 'snow')).toEqual([1, 3, 4])
  })

  it('is null for an hour with no forecast anywhere', () => {
    const h = heatmap({ risk: [[null], [null]], hours: 0 })
    expect(worstByHour(h, 'risk')).toEqual([null])
  })
})

describe('legend helpers', () => {
  it('labels bands with the right edge symbol', () => {
    expect(bandLabels('wind')).toEqual(['< 25', '25–35', '35–45', '45–55', '≥ 55'])
    expect(bandLabels('rain').at(-1)).toBe('> 1')
    expect(bandLabels('risk')).toEqual(['Low', 'Moderate', 'High', 'Severe', 'No Travel'])
  })

  it('converts hex to rgba', () => {
    expect(rgba('#d6332a', 0.5)).toBe('rgba(214, 51, 42, 0.5)')
  })
})
