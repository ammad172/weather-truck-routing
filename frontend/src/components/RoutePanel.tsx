import type { PlanResponse, Route } from '../api/types'
import { riskColor, riskLabel, riskSpans } from '../lib/risk'
import { formatDateTime, formatDayTime, formatDuration } from '../lib/time'
import type { CheckpointFocus } from './MapView'

type Props = {
  plan: PlanResponse
  selectedRouteId: string | null
  onSelectRoute: (id: string) => void
  onFocusCheckpoint: (focus: CheckpointFocus) => void
}

export function RoutePanel({ plan, selectedRouteId, onSelectRoute, onFocusCheckpoint }: Props) {
  const { request, recommendation, notes } = plan
  const byId = new Map(plan.routes.map((r) => [r.id, r]))
  const ranked = recommendation.ranking.map((id) => byId.get(id)).filter((r): r is Route => !!r)
  const selected = selectedRouteId ? byId.get(selectedRouteId) : undefined

  return (
    <section className="results" aria-label="Route options">
      <header className="trip-summary">
        <h2>
          {short(request.origin.label)} → {short(request.destination.label)}
        </h2>
        <p>
          Departs {formatDateTime(request.departure)} · {request.weight_lb.toLocaleString()} lb load · checkpoint
          every {request.interval_mi} mi
        </p>
      </header>

      <div className="recommendation" role="status">
        <div className="recommendation-title">Recommended: Route {recommendation.route_id}</div>
        <p>{recommendation.reason}</p>
      </div>
      {recommendation.warning && (
        <div className="callout danger" role="alert">
          {recommendation.warning}
        </div>
      )}
      {notes.map((note) => (
        <div key={note} className="callout info">
          {note}
        </div>
      ))}

      <ol className="route-cards">
        {ranked.map((route) => (
          <li key={route.id}>
            <RouteCard
              route={route}
              recommended={route.id === recommendation.route_id}
              selected={route.id === selectedRouteId}
              onSelect={() => onSelectRoute(route.id)}
            />
          </li>
        ))}
      </ol>

      {selected && <CheckpointTable route={selected} onFocus={(index) => onFocusCheckpoint({ routeId: selected.id, index })} />}
    </section>
  )
}

function RouteCard({ route, recommended, selected, onSelect }: { route: Route; recommended: boolean; selected: boolean; onSelect: () => void }) {
  const s = route.summary
  const arrival = route.checkpoints.at(-1)?.eta
  return (
    <button type="button" className={`route-card${selected ? ' selected' : ''}`} aria-pressed={selected} onClick={onSelect}>
      <div className="route-card-head">
        <span className="route-name">Route {route.id}</span>
        {recommended && <span className="badge recommended">Recommended</span>}
        {route.source === 'via-point' && (
          <span className="badge muted" title="Found by routing through a point beside the fastest route">
            Generated
          </span>
        )}
        <span className="worst" style={{ color: riskColor(s.worst_level) }}>
          Worst: {riskLabel(s.worst_level)}
        </span>
      </div>
      <div className="route-card-meta">
        <span>{formatDuration(route.duration_s)}</span>
        <span>{Math.round(route.distance_mi).toLocaleString()} mi</span>
        {arrival && <span>Arrives {formatDayTime(arrival)}</span>}
      </div>
      <RiskBar route={route} />
      <dl className="route-stats">
        <Stat label="No Travel" value={`${s.no_travel_miles.toFixed(0)} mi`} level={s.no_travel_miles > 0 ? 4 : null} />
        <Stat label="Severe" value={`${s.severe_miles.toFixed(0)} mi`} level={s.severe_miles > 0 ? 3 : null} />
        <Stat label="High" value={`${s.high_miles.toFixed(0)} mi`} level={s.high_miles > 0 ? 2 : null} />
        <Stat label="Avg risk" value={`${s.avg_risk.toFixed(2)} / 4`} level={null} />
      </dl>
    </button>
  )
}

function Stat({ label, value, level }: { label: string; value: string; level: 2 | 3 | 4 | null }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd style={level !== null ? { color: riskColor(level) } : undefined}>{value}</dd>
    </div>
  )
}

/** The route as a strip, each stretch coloured by its checkpoint's risk. */
function RiskBar({ route }: { route: Route }) {
  const spans = riskSpans(route.checkpoints)
  const summary = spans.map((s) => `${riskLabel(s.level)} ${Math.round((s.to - s.from) * 100)}%`).join(', ')
  return (
    <div className="risk-bar" role="img" aria-label={`Risk along the route: ${summary}`}>
      {spans.map((span, i) => (
        <span key={i} style={{ flexGrow: span.to - span.from, background: riskColor(span.level) }} />
      ))}
    </div>
  )
}

function CheckpointTable({ route, onFocus }: { route: Route; onFocus: (index: number) => void }) {
  return (
    <section className="checkpoints" aria-label={`Route ${route.id} checkpoints`}>
      <h3>Route {route.id} checkpoints</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Mile</th>
              <th scope="col">Arrives</th>
              <th scope="col">Risk</th>
              <th scope="col">Wind</th>
              <th scope="col">Rain</th>
              <th scope="col">Snow</th>
            </tr>
          </thead>
          <tbody>
            {route.checkpoints.map((c, i) => (
              <tr key={i} tabIndex={0} onClick={() => onFocus(i)} onKeyDown={(e) => e.key === 'Enter' && onFocus(i)}>
                <td>{Math.round(c.mile)}</td>
                <td>{formatDayTime(c.eta)}</td>
                <td>
                  <span className="level-dot" style={{ background: riskColor(c.level) }} aria-hidden="true" />
                  {riskLabel(c.level)}
                </td>
                <td>{c.weather.wind_mph === null ? '–' : `${c.weather.wind_mph.toFixed(0)} mph`}</td>
                <td>{c.weather.rain_in_hr === null ? '–' : c.weather.rain_in_hr.toFixed(2)}</td>
                <td>{c.weather.snow_in_hr === null ? '–' : c.weather.snow_in_hr.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="table-note">Rain and snow in inches per hour. Select a row to show it on the map.</p>
    </section>
  )
}

/** "Dallas, TX, United States" -> "Dallas, TX" */
function short(label: string): string {
  return label.replace(/, (United States|Canada|Mexico)$/, '')
}
