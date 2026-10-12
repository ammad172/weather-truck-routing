import { useMutation } from '@tanstack/react-query'
import { memo, useCallback, useMemo, useState } from 'react'
import { plan as requestPlan } from './api/client'
import type { PlanResponse } from './api/types'
import { ForecastTimeline } from './components/ForecastTimeline'
import { Legend } from './components/Legend'
import { type CheckpointFocus, MapView } from './components/MapView'
import { RoutePanel as RoutePanelView } from './components/RoutePanel'
import { TripForm } from './components/TripForm'
import { type HeatVariable, hourTime } from './lib/heatmap'
import { localZoneName } from './lib/time'
import { truckPosition } from './lib/truck'
import './App.css'

// The panel's props don't change while the slider moves, so skip re-rendering its tables.
const RoutePanel = memo(RoutePanelView)

export default function App() {
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [focus, setFocus] = useState<CheckpointFocus | null>(null)
  const [hour, setHour] = useState(0)
  const [variable, setVariable] = useState<HeatVariable>('risk')

  const planning = useMutation({
    mutationFn: requestPlan,
    onSuccess: (result) => {
      setPlan(result)
      setSelectedRouteId(result.recommendation.route_id)
      setFocus(null)
      setHour((h) => Math.min(h, result.heatmap.hours))
    },
  })

  const selectRoute = useCallback((id: string) => {
    setSelectedRouteId(id)
    setFocus(null)
  }, [])

  const selectedRoute = plan?.routes.find((r) => r.id === selectedRouteId) ?? null
  const truck = useMemo(
    () => (plan && selectedRoute ? truckPosition(selectedRoute, Date.parse(hourTime(plan.heatmap, hour))) : null),
    [plan, selectedRoute, hour],
  )
  const arrivalHour = useMemo(() => {
    const arrival = selectedRoute?.checkpoints.at(-1)?.eta
    return plan && arrival ? (Date.parse(arrival) - Date.parse(plan.heatmap.start)) / 3_600_000 : null
  }, [plan, selectedRoute])

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
            {plan && <span className="callout-note"> The routes below are from your previous plan.</span>}
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

      <main className={`map-area${plan ? ' has-timeline' : ''}`}>
        <MapView
          plan={plan}
          selectedRouteId={selectedRouteId}
          onSelectRoute={selectRoute}
          focus={focus}
          hour={hour}
          variable={variable}
          truck={truck}
        />
        {planning.isPending && (
          <div className="map-overlay" role="status">
            <span className="spinner" aria-hidden="true" /> Finding routes and forecasts…
          </div>
        )}
        {!plan && !planning.isPending && (
          <div className="map-hint">Enter a trip to compare up to three truck routes.</div>
        )}
        <Legend variable={variable} showHeatmap={!!plan} />
        {plan && (
          <ForecastTimeline
            heatmap={plan.heatmap}
            hour={hour}
            onHourChange={setHour}
            variable={variable}
            onVariableChange={setVariable}
            arrivalHour={arrivalHour}
            routeId={selectedRouteId}
            truck={truck}
          />
        )}
      </main>
    </div>
  )
}
