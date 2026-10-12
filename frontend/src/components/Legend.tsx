import { bandLabels, HEAT_VARIABLES, type HeatVariable, rgba } from '../lib/heatmap'
import { RISK_LEVELS } from '../lib/risk'

const BAR_ALPHA = 0.7

/**
 * One legend for both layers. The five columns line up: each risk colour, its name, the
 * same colour in the heatmap, and (for wind, rain or snow) the values that fall in it.
 */
export function Legend({ variable, showHeatmap }: { variable: HeatVariable; showHeatmap: boolean }) {
  const info = HEAT_VARIABLES[variable]
  const bands = bandLabels(variable)
  // Soft edges between bands, like the heatmap's blending.
  const gradient = RISK_LEVELS.map((r, i) => {
    const from = (i / RISK_LEVELS.length) * 100
    const to = ((i + 1) / RISK_LEVELS.length) * 100
    return `${rgba(r.color, BAR_ALPHA)} ${from + 3}% ${to - 3}%`
  }).join(', ')

  return (
    <section className="legend" aria-label="Map legend">
      <span className="legend-key">Route</span>
      <ul className="legend-levels" aria-label="Risk levels">
        {RISK_LEVELS.map((r) => (
          <li key={r.level}>
            <span className="legend-line" style={{ background: r.color }} aria-hidden="true" />
            {r.label}
          </li>
        ))}
      </ul>
      {showHeatmap && (
        <>
          <span className="legend-key">
            {info.label}
            {info.unit && <span className="legend-unit">{info.unit}</span>}
          </span>
          <div className="legend-heat">
            <div className="legend-bar" style={{ background: `linear-gradient(to right, ${gradient})` }} aria-hidden="true" />
            {variable !== 'risk' && (
              <ul className="legend-bands" aria-label={`${info.label} bands in ${info.unit}`}>
                {bands.map((band, i) => (
                  <li key={band} aria-label={`${RISK_LEVELS[i].label}: ${band} ${info.unit}`}>
                    {band}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  )
}
