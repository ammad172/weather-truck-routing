import { useMutation } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { plan as requestPlan } from './api/client'
import type { PlanResponse } from './api/types'
import { type CheckpointFocus, MapView } from './components/MapView'
import { RoutePanel } from './components/RoutePanel'
import { TripForm } from './components/TripForm'
import { RISK_LEVELS } from './lib/risk'
import { localZoneName } from './lib/time'
import './App.css'

export default function App() {
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [focus, setFocus] = useState<CheckpointFocus | null>(null)

  const planning = useMutation({
    mutationFn: requestPlan,
    onSuccess: (result) => {
      setPlan(result)
      setSelectedRouteId(result.recommendation.route_id)
      setFocus(null)
    },
  })

  const selectRoute = useCallback((id: string) => {
    setSelectedRouteId(id)
    setFocus(null)
  }, [])

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="brand">
          <h1>Weather-Aware Truck Routing</h1>
          <p>Compare routes by forecast weather at the time you'll be there, your load, and travel time.</p>
        </header>

        <TripForm onSubmit={(request) => planning.mutate(request)} pending={planning.isPending} hasPlan={!!plan} />

        {planning.isError && (
          <div className="callout danger" role="alert">
            {planning.error.message}
          </div>
        )}

        {plan && (
          <RoutePanel plan={plan} selectedRouteId={selectedRouteId} onSelectRoute={selectRoute} onFocusCheckpoint={setFocus} />
        )}

        <footer className="sidebar-footer">
          <p>Times are shown in your timezone ({localZoneName()}).</p>
          <p>Routing &amp; geocoding: HERE · Weather: Open-Meteo · Map: OpenFreeMap, © OpenStreetMap contributors</p>
        </footer>
      </aside>

      <main className="map-area">
        <MapView plan={plan} selectedRouteId={selectedRouteId} onSelectRoute={selectRoute} focus={focus} />
        {planning.isPending && (
          <div className="map-overlay" role="status">
            <span className="spinner" aria-hidden="true" /> Finding routes and forecasts…
          </div>
        )}
        {!plan && !planning.isPending && (
          <div className="map-hint">Enter a trip to compare up to three truck routes.</div>
        )}
        <ul className="legend" aria-label="Risk levels">
          {RISK_LEVELS.map((r) => (
            <li key={r.level}>
              <span style={{ background: r.color }} aria-hidden="true" />
              {r.label}
            </li>
          ))}
        </ul>
      </main>
    </div>
  )
}
