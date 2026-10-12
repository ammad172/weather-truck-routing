import type { ExpressionSpecification } from '@maplibre/maplibre-gl-style-spec'
import type { Checkpoint, RiskLevel } from '../api/types'

export const RISK_LEVELS: { level: RiskLevel; label: string; color: string }[] = [
  { level: 0, label: 'Low', color: '#2f9e44' },
  { level: 1, label: 'Moderate', color: '#e8b10c' },
  { level: 2, label: 'High', color: '#f0750f' },
  { level: 3, label: 'Severe', color: '#d6332a' },
  { level: 4, label: 'No Travel', color: '#5f1d8f' },
]

export const riskColor = (level: RiskLevel): string => RISK_LEVELS[level].color
export const riskLabel = (level: RiskLevel): string => RISK_LEVELS[level].label

/** A stretch of route (as fractions of its length) drawn in one risk colour. */
export type RiskSpan = { from: number; to: number; level: RiskLevel }

/**
 * Split a route into coloured spans from its checkpoints. Each checkpoint covers the
 * road halfway to its neighbours (the same rule the backend uses for risk miles).
 * Adjacent spans of the same level are merged.
 */
export function riskSpans(checkpoints: Checkpoint[]): RiskSpan[] {
  const total = checkpoints.at(-1)?.mile ?? 0
  if (!total) return checkpoints.length ? [{ from: 0, to: 1, level: checkpoints[0].level }] : []
  const spans: RiskSpan[] = []
  checkpoints.forEach((c, i) => {
    const from = i === 0 ? 0 : (checkpoints[i - 1].mile + c.mile) / 2 / total
    const to = i === checkpoints.length - 1 ? 1 : (c.mile + checkpoints[i + 1].mile) / 2 / total
    const last = spans.at(-1)
    if (last && last.level === c.level) last.to = to
    else spans.push({ from, to, level: c.level })
  })
  return spans
}

/**
 * A MapLibre `line-gradient` expression that paints those spans with hard edges:
 * ["step", ["line-progress"], colour0, start1, colour1, ...].
 */
export function riskGradient(checkpoints: Checkpoint[]): ExpressionSpecification {
  const spans = riskSpans(checkpoints)
  const first = riskColor(spans[0]?.level ?? 0)
  const stops = spans.slice(1).flatMap((span) => [span.from, riskColor(span.level)])
  // `step` needs at least one stop, so a single-colour route gets a no-op stop at the very end.
  return ['step', ['line-progress'], first, ...(stops.length ? stops : [1, first])] as ExpressionSpecification
}

/** A single-colour `line-gradient` (for routes that aren't selected). */
export function solidGradient(color: string): ExpressionSpecification {
  return ['step', ['line-progress'], color, 1, color]
}

/** A MapLibre `match` expression colouring a feature by its numeric `level` property. */
export function riskColorMatch(fallback: string): ExpressionSpecification {
  const [low, moderate, high, severe, noTravel] = RISK_LEVELS
  return [
    'match',
    ['get', 'level'],
    low.level,
    low.color,
    moderate.level,
    moderate.color,
    high.level,
    high.color,
    severe.level,
    severe.color,
    noTravel.level,
    noTravel.color,
    fallback,
  ]
}
