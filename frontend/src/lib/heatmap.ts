import type { ExpressionSpecification } from '@maplibre/maplibre-gl-style-spec'
import type { Heatmap, RiskLevel } from '../api/types'
import { RISK_LEVELS } from './risk'

// The corridor heatmap. Every point carries one pre-computed weight per variable and hour
// (properties "risk0" ... "snow48"), so moving the slider only swaps the `heatmap-weight`
// expression to ["get", "<variable><hour>"]; the GeoJSON is built once per plan.

export type HeatVariable = 'risk' | 'wind' | 'rain' | 'snow'

type VariableInfo = {
  label: string
  /** Band edges for Moderate, High, Severe, No Travel (as in backend/routing/risk.py). */
  edges?: [number, number, number, number]
  unit?: string
  /** Rain and snow are only No Travel strictly *above* the top edge. */
  strictTop?: boolean
  note: string
}

export const HEAT_VARIABLES: Record<HeatVariable, VariableInfo> = {
  risk: { label: 'Risk', note: 'Worst of wind, rain and snow, with the load rules' },
  wind: { label: 'Wind', edges: [25, 35, 45, 55], unit: 'mph', note: 'Wind bands before the load rules' },
  rain: { label: 'Rain', edges: [0.1, 0.25, 0.5, 1], unit: 'in/hr', strictTop: true, note: 'Rain bands' },
  snow: { label: 'Snow', edges: [0.5, 1, 2, 3], unit: 'in/hr', strictTop: true, note: 'Snow bands' },
}

export const HEAT_VARIABLE_KEYS = Object.keys(HEAT_VARIABLES) as HeatVariable[]

/** The band a raw value falls in, with the same edge rules as the backend. */
export function bandOf(variable: Exclude<HeatVariable, 'risk'>, value: number): RiskLevel {
  const { edges, strictTop } = HEAT_VARIABLES[variable]
  const [moderate, high, severe, noTravel] = edges!
  if (strictTop ? value > noTravel : value >= noTravel) return 4
  if (value >= severe) return 3
  if (value >= high) return 2
  if (value >= moderate) return 1
  return 0
}

/** The level shown for a point and hour, or null where there's no forecast. */
export function levelAt(heatmap: Heatmap, variable: HeatVariable, point: number, hour: number): RiskLevel | null {
  if (variable === 'risk') return heatmap.risk[point][hour]
  const series = { wind: heatmap.wind_mph, rain: heatmap.rain_in_hr, snow: heatmap.snow_in_hr }[variable]
  const value = series[point][hour]
  return value === null ? null : bandOf(variable, value)
}

/**
 * Heatmap weight for a level: Low 0.2 ... No Travel 1.0, and 0 for no forecast, so a
 * clear corridor still shows as a faint green and missing data shows as nothing.
 */
export const levelWeight = (level: RiskLevel | null): number => (level === null ? 0 : (level + 1) / 5)

/** The ISO time of a slider position: the heatmap starts at the departure hour. */
export function hourTime(heatmap: Heatmap, hour: number): string {
  return new Date(Date.parse(heatmap.start) + hour * 3_600_000).toISOString()
}

export const weightProperty = (variable: HeatVariable, hour: number) => `${variable}${hour}`

/** A place the heatmap draws: a corridor point, or a ghost just outside the corridor's edge. */
export type HeatSite = {
  /** [lon, lat] */
  at: [number, number]
  /** The corridor point itself, or null for a ghost. */
  point: number | null
  /** Corridor points whose worst level this site shows (itself and its lattice neighbours). */
  from: number[]
}

/**
 * Every corridor point, plus a ring of ghost sites on the empty lattice cells around the corridor.
 * Heatmap points all sit on one lattice of `cell_deg` spacing, so neighbours are the 8 cells around.
 */
export function heatSites(heatmap: Heatmap): HeatSite[] {
  const cell = heatmap.cell_deg
  const key = (i: number, j: number) => `${i},${j}`
  const cellOf = ([lon, lat]: [number, number]) => [Math.round(lat / cell), Math.round(lon / cell)]
  const byCell = new Map(heatmap.points.map((p, n) => [key(...(cellOf(p) as [number, number])), n]))
  const around = (i: number, j: number) => {
    const found: number[] = []
    for (let di = -1; di <= 1; di++)
      for (let dj = -1; dj <= 1; dj++) {
        const n = byCell.get(key(i + di, j + dj))
        if (n !== undefined) found.push(n)
      }
    return found
  }
  const sites: HeatSite[] = heatmap.points.map((at, point) => ({ at, point, from: around(...(cellOf(at) as [number, number])) }))
  const ghosts = new Set<string>()
  for (const p of heatmap.points) {
    const [i, j] = cellOf(p)
    for (let di = -1; di <= 1; di++)
      for (let dj = -1; dj <= 1; dj++) {
        const k = key(i + di, j + dj)
        if (byCell.has(k) || ghosts.has(k)) continue
        ghosts.add(k)
        sites.push({ at: [round((j + dj) * cell), round((i + di) * cell)], point: null, from: around(i + di, j + dj) })
      }
  }
  return sites
}

/**
 * One feature per heat site with a weight per variable and hour.
 *
 * A heatmap adds up overlapping kernels, so a lone stormy cell among clear ones would be
 * averaged down a band or two. To keep hazards visible, each site shows the worst level among
 * itself and its neighbours: a lone hazard becomes a 3 x 3 block, which keeps its colour at its
 * centre. The ghost ring does the same for hazards on the corridor's edge, which would otherwise
 * have no neighbours outward and fade to about half. Both overstate a hazard's extent by up to
 * one cell, the cautious direction. Ghosts next to Low cells stay empty, so the clear corridor
 * keeps its soft edge.
 *
 * Weights are also scaled by cos(lat) / cos(maxLat) because Mercator spreads the grid's rows
 * further apart toward the pole; without it, a long north-south corridor would fade southward.
 */
export function heatmapFeatures(heatmap: Heatmap): GeoJSON.FeatureCollection<GeoJSON.Point> {
  const refCos = Math.cos(toRad(maxLat(heatmap)))
  return {
    type: 'FeatureCollection',
    features: heatSites(heatmap).map(({ at, point, from }) => {
      const scale = refCos / Math.cos(toRad(at[1]))
      const properties: Record<string, number> = {}
      for (const variable of HEAT_VARIABLE_KEYS)
        for (let hour = 0; hour <= heatmap.hours; hour++) {
          // A point with no forecast stays empty rather than borrowing a neighbour's.
          let worst: RiskLevel | null = null
          if (point === null || levelAt(heatmap, variable, point, hour) !== null)
            for (const n of from) {
              const level = levelAt(heatmap, variable, n, hour)
              if (level !== null && (worst === null || level > worst)) worst = level
            }
          if (point === null && worst === 0) worst = null
          properties[weightProperty(variable, hour)] = round(levelWeight(worst) * scale)
        }
      return { type: 'Feature', properties, geometry: { type: 'Point', coordinates: at } }
    }),
  }
}

// MapLibre's heatmap kernel is a Gaussian with sigma = radius / 3 and peak 1/sqrt(2*pi), so
// on a regular grid (spacing sx by sy pixels) the summed density is
//     weight * intensity * (2*pi / 9) / sqrt(2*pi) * radius^2 / (sx * sy)  ~=  weight * intensity * 0.2785 * r^2 / (sx * sy).
// The radius is 1.5x the row spacing (sy = sx / cos(lat)): wide enough that the cells blend
// (the density ripples by about 3%), narrow enough that a 3 x 3 block keeps 99% of its level at
// its centre. Intensity = cos(lat) / (0.2785 * 1.5^2) makes the density equal the weight, so the
// colour ramp can put each risk colour at exactly its level's weight.
const KERNEL = Math.sqrt(2 * Math.PI) / 9
const RADIUS_PER_ROW = 1.5

/** `heatmap-radius`: 1.5x the grid's row spacing in pixels at every zoom. */
export function heatmapRadius(heatmap: Heatmap): ExpressionSpecification {
  const rowPxAtZoom0 = (heatmap.cell_deg * 512) / 360 / Math.cos(toRad(maxLat(heatmap)))
  const r0 = RADIUS_PER_ROW * rowPxAtZoom0
  return ['interpolate', ['exponential', 2], ['zoom'], 0, r0, 12, r0 * 2 ** 12]
}

/** `heatmap-intensity` that makes the corridor's density equal each point's weight. */
export function heatmapIntensity(heatmap: Heatmap): number {
  return Math.cos(toRad(maxLat(heatmap))) / (KERNEL * RADIUS_PER_ROW ** 2)
}

/** Opacity of a band's colour in the heatmap; Low is a tint so the basemap stays readable. */
const BAND_ALPHA = [0.24, 0.62, 0.66, 0.7, 0.74]
/** Half-width of each band's flat stretch on the density ramp, so small blending errors keep the true colour. */
const PLATEAU = 0.06

/** `heatmap-color`: transparent at zero density, then each risk colour flat around its level's weight. */
export function heatmapColor(): ExpressionSpecification {
  // Below Low's flat stretch the tint fades out gradually: that's the corridor's soft edge.
  const stops: (number | string)[] = [0, rgba(RISK_LEVELS[0].color, 0), 0.03, rgba(RISK_LEVELS[0].color, 0)]
  RISK_LEVELS.forEach(({ level, color }) => {
    const at = levelWeight(level)
    stops.push(at - PLATEAU, rgba(color, BAND_ALPHA[level]))
    if (at + PLATEAU < 1) stops.push(at + PLATEAU, rgba(color, BAND_ALPHA[level]))
  })
  stops.push(1, rgba(RISK_LEVELS[4].color, BAND_ALPHA[4]))
  return ['interpolate', ['linear'], ['heatmap-density'], ...stops] as ExpressionSpecification
}

/** The worst level anywhere in the corridor, per hour: the strip behind the slider. */
export function worstByHour(heatmap: Heatmap, variable: HeatVariable): (RiskLevel | null)[] {
  return Array.from({ length: heatmap.hours + 1 }, (_, hour) => {
    let worst: RiskLevel | null = null
    for (let point = 0; point < heatmap.points.length; point++) {
      const level = levelAt(heatmap, variable, point, hour)
      if (level !== null && (worst === null || level > worst)) worst = level
    }
    return worst
  })
}

/** Band labels for the legend, e.g. ["< 25", "25", "35", "45", "≥ 55"] read under each colour. */
export function bandLabels(variable: HeatVariable): string[] {
  const { edges, strictTop } = HEAT_VARIABLES[variable]
  if (!edges) return RISK_LEVELS.map((r) => r.label)
  const [moderate, high, severe, noTravel] = edges
  return [`< ${moderate}`, `${moderate}–${high}`, `${high}–${severe}`, `${severe}–${noTravel}`, `${strictTop ? '>' : '≥'} ${noTravel}`]
}

/** "#d6332a" -> "rgba(214, 51, 42, 0.7)" */
export function rgba(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

const toRad = (deg: number) => (deg * Math.PI) / 180
const round = (n: number) => Math.round(n * 1000) / 1000
const maxLat = (heatmap: Heatmap) => heatmap.points.reduce((max, [, lat]) => Math.max(max, Math.abs(lat)), 0)
