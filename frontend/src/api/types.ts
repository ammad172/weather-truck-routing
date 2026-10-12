// Mirrors the Django API (see the README's API section). All times are ISO 8601 in UTC
// with an explicit offset; the UI converts them for display with lib/time.ts.

export type RiskLevel = 0 | 1 | 2 | 3 | 4

export type Place = { label: string; lat: number; lon: number }

export type Checkpoint = {
  mile: number
  segment_miles: number
  lat: number
  lon: number
  eta: string
  forecast_hour: string
  weather: { wind_mph: number | null; rain_in_hr: number | null; snow_in_hr: number | null }
  level: RiskLevel
  level_label: string
  factor: 'wind' | 'rain' | 'snow' | null
  load_adjusted: boolean
}

export type RouteSummary = {
  no_travel_miles: number
  severe_miles: number
  high_miles: number
  avg_risk: number
  worst_level: RiskLevel
  worst_level_label: string
}

export type Route = {
  id: string
  source: 'provider' | 'via-point'
  distance_mi: number
  duration_s: number
  summary: RouteSummary
  /** [lon, lat] pairs */
  geometry: [number, number][]
  checkpoints: Checkpoint[]
}

export type Heatmap = {
  start: string
  hours: number
  cell_deg: number
  /** [lon, lat] pairs */
  points: [number, number][]
  /** [point][hour]; null where there is no forecast */
  risk: (RiskLevel | null)[][]
  wind_mph: (number | null)[][]
  rain_in_hr: (number | null)[][]
  snow_in_hr: (number | null)[][]
}

export type PlanResponse = {
  request: {
    origin: Place
    destination: Place
    departure: string
    weight_lb: number
    gross_weight_lb: number
    interval_mi: Interval
  }
  routes: Route[]
  recommendation: { route_id: string; ranking: string[]; reason: string; warning: string | null }
  heatmap: Heatmap
  notes: string[]
}

export const INTERVALS = [10, 25, 50] as const
export type Interval = (typeof INTERVALS)[number]

export type PlanRequest = {
  /** A picked suggestion, or free text the server geocodes. */
  origin: Place | string
  destination: Place | string
  departure: string
  weight_lb: number
  interval_mi: Interval
}
