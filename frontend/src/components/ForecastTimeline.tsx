import { type CSSProperties, useEffect, useMemo, useState } from 'react'
import type { Heatmap } from '../api/types'
import { HEAT_VARIABLE_KEYS, HEAT_VARIABLES, type HeatVariable, hourTime, worstByHour } from '../lib/heatmap'
import { riskColor, riskLabel } from '../lib/risk'
import type { TruckPosition } from '../lib/truck'
import { formatDayTime } from '../lib/time'

const PLAY_STEP_MS = 650
const TICKS = [0, 12, 24, 36, 48]

type Props = {
  heatmap: Heatmap
  hour: number
  onHourChange: (hour: number) => void
  variable: HeatVariable
  onVariableChange: (variable: HeatVariable) => void
  /** Hours after the slider's start when the selected route arrives. */
  arrivalHour: number | null
  routeId: string | null
  truck: TruckPosition | null
}

export function ForecastTimeline({ heatmap, hour, onHourChange, variable, onVariableChange, arrivalHour, routeId, truck }: Props) {
  const [playing, setPlaying] = useState(false)
  const last = heatmap.hours
  const worst = useMemo(() => worstByHour(heatmap, variable), [heatmap, variable])
  const label = `+${hour} h after departure · ${formatDayTime(hourTime(heatmap, hour))}`

  // Play advances an hour per step and stops at the end.
  const running = playing && hour < last
  useEffect(() => {
    if (!running) return
    const timer = setTimeout(() => onHourChange(hour + 1), PLAY_STEP_MS)
    return () => clearTimeout(timer)
  }, [running, hour, onHourChange])

  const togglePlay = () => {
    if (!running && hour >= last) onHourChange(0)
    setPlaying(!running)
  }

  return (
    <section className="timeline" aria-label="Forecast timeline">
      <div className="timeline-head">
        <button
          type="button"
          className="play"
          onClick={togglePlay}
          aria-label={running ? 'Pause forecast' : 'Play forecast'}
          aria-pressed={running}
        >
          <span aria-hidden="true" className={running ? 'icon-pause' : 'icon-play'} />
        </button>
        <div className="timeline-readout">
          <output htmlFor="forecast-hour" className="timeline-label">
            {label}
          </output>
          {truck && routeId && <span className="timeline-truck">{truckText(routeId, truck)}</span>}
        </div>
        <fieldset className="variable-toggle">
          <legend className="visually-hidden">Show on map</legend>
          {HEAT_VARIABLE_KEYS.map((key) => (
            <label key={key} className={key === variable ? 'selected' : undefined} title={HEAT_VARIABLES[key].note}>
              <input type="radio" name="heat-variable" value={key} checked={key === variable} onChange={() => onVariableChange(key)} />
              {HEAT_VARIABLES[key].label}
            </label>
          ))}
        </fieldset>
      </div>

      <div className="scrubber">
        {/* The track is the forecast itself: one cell per hour, coloured by the worst level in the corridor. */}
        <div className="scrubber-rail">
          <ol className="hour-strip" aria-hidden="true" style={{ '--hours': last } as CSSProperties}>
            {worst.map((level, h) => (
              <li
                key={h}
                className={h === hour ? 'current' : undefined}
                style={{ background: level === null ? undefined : riskColor(level) }}
                title={`+${h} h: worst ${level === null ? 'no forecast' : riskLabel(level)}`}
              />
            ))}
          </ol>
          {arrivalHour !== null && arrivalHour <= last && (
            <span className="arrival-mark" style={{ left: `${(arrivalHour / last) * 100}%` }} aria-hidden="true">
              <span>Arrives</span>
            </span>
          )}
          <input
            id="forecast-hour"
            type="range"
            min={0}
            max={last}
            step={1}
            value={hour}
            onChange={(e) => {
              setPlaying(false)
              onHourChange(Number(e.target.value))
            }}
            aria-label="Hours after departure"
            aria-valuetext={label}
          />
        </div>
        <ol className="scrubber-ticks" aria-hidden="true">
          {TICKS.filter((t) => t <= last).map((t) => (
            <li key={t} style={{ left: `${(t / last) * 100}%` }}>
              {t === 0 ? 'Departure' : `+${t} h`}
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

function truckText(routeId: string, truck: TruckPosition): string {
  if (truck.status === 'not-departed') return `Route ${routeId}: not yet departed`
  if (truck.status === 'arrived') return `Route ${routeId}: arrived`
  return `Route ${routeId}: truck at mile ${Math.round(truck.mile)}`
}
