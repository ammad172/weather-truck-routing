import type { Route } from '../api/types'

export type TruckPosition = {
  /** [lon, lat] */
  at: [number, number]
  mile: number
  status: 'not-departed' | 'en-route' | 'arrived'
}

/**
 * Where the truck is on a route at a given time, from its checkpoint ETAs: the mile is
 * interpolated between the two checkpoints either side of the time, then placed along the
 * route line (so the marker follows the road rather than cutting between checkpoints).
 */
export function truckPosition(route: Route, time: number): TruckPosition | null {
  const checkpoints = route.checkpoints
  if (!checkpoints.length || route.geometry.length < 2) return null
  const etas = checkpoints.map((c) => Date.parse(c.eta))
  const last = checkpoints.length - 1
  const totalMiles = checkpoints[last].mile

  let mile: number
  let status: TruckPosition['status'] = 'en-route'
  if (time <= etas[0]) {
    // Up to and including the departure instant, the truck is still at the start.
    mile = 0
    status = 'not-departed'
  } else if (time >= etas[last]) {
    mile = totalMiles
    status = 'arrived'
  } else {
    const i = etas.findIndex((eta) => eta > time) // first checkpoint still ahead
    const t = (time - etas[i - 1]) / (etas[i] - etas[i - 1])
    mile = checkpoints[i - 1].mile + t * (checkpoints[i].mile - checkpoints[i - 1].mile)
  }
  return { at: pointAlong(route.geometry, totalMiles ? mile / totalMiles : 0), mile, status }
}

/** The point a fraction (0..1) of the way along a [lon, lat] line, measured by distance. */
export function pointAlong(line: [number, number][], fraction: number): [number, number] {
  const lengths = [0]
  for (let i = 1; i < line.length; i++) lengths.push(lengths[i - 1] + distance(line[i - 1], line[i]))
  const target = Math.min(Math.max(fraction, 0), 1) * lengths[lengths.length - 1]
  const i = lengths.findIndex((d) => d >= target)
  if (i <= 0) return line[0]
  const span = lengths[i] - lengths[i - 1]
  const t = span ? (target - lengths[i - 1]) / span : 0
  return [line[i - 1][0] + t * (line[i][0] - line[i - 1][0]), line[i - 1][1] + t * (line[i][1] - line[i - 1][1])]
}

/** Equirectangular distance in degrees; only ratios matter here, and segments are short. */
function distance([lon1, lat1]: [number, number], [lon2, lat2]: [number, number]): number {
  const x = (lon2 - lon1) * Math.cos((((lat1 + lat2) / 2) * Math.PI) / 180)
  return Math.hypot(x, lat2 - lat1)
}
