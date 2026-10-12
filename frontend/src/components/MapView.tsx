import {
  type GeoJSONSource,
  LngLatBounds,
  Map as MapLibreMap,
  type MapLayerMouseEvent,
  Marker,
  NavigationControl,
  Popup,
  ScaleControl,
  setWorkerUrl,
  type Subscription,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
// MapLibre finds its (self-contained) worker relative to its own file, which breaks once
// Vite pre-bundles it. Point it at the worker explicitly; works in dev and in the build.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useEffect, useRef, useState } from 'react'
import type { Checkpoint, PlanResponse } from '../api/types'
import { heatmapColor, heatmapFeatures, heatmapIntensity, heatmapRadius, type HeatVariable, weightProperty } from '../lib/heatmap'
import { riskColorMatch, riskGradient, riskLabel, solidGradient } from '../lib/risk'
import type { TruckPosition } from '../lib/truck'
import { formatDateTime } from '../lib/time'

setWorkerUrl(workerUrl)

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const CHECKPOINTS = 'checkpoints'
const HEATMAP = 'forecast-heatmap'
const MUTED = '#8792a2'

export type CheckpointFocus = { routeId: string; index: number }

type Props = {
  plan: PlanResponse | null
  selectedRouteId: string | null
  onSelectRoute: (id: string) => void
  focus: CheckpointFocus | null
  hour: number
  variable: HeatVariable
  truck: TruckPosition | null
}

const routeSource = (id: string) => `route-${id}`
const casingLayer = (id: string) => `route-${id}-casing`
const lineLayer = (id: string) => `route-${id}-line`

export function MapView({ plan, selectedRouteId, onSelectRoute, focus, hour, variable, truck }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const popupRef = useRef<Popup | null>(null)
  const truckRef = useRef<Marker | null>(null)
  const [loaded, setLoaded] = useState(false)
  // Layer event handlers are registered once per plan; read the latest callback through a ref.
  const onSelectRef = useRef(onSelectRoute)
  useEffect(() => {
    onSelectRef.current = onSelectRoute
  }, [onSelectRoute])

  // Create the map once.
  useEffect(() => {
    const map = new MapLibreMap({
      container: container.current!,
      style: STYLE_URL,
      center: [-98.5, 38.5],
      zoom: 3.6,
      attributionControl: { compact: true },
    })
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new ScaleControl({ unit: 'imperial' }), 'bottom-right')
    map.on('load', () => {
      // The forecast heatmap sits under the basemap's labels; the routes and checkpoints go on top.
      // It's created once: a new plan replaces its data, and the slider only changes its weight.
      const firstLabel = map.getStyle().layers.find((layer) => layer.type === 'symbol')?.id
      map.addSource(HEATMAP, { type: 'geojson', data: emptyCollection() })
      map.addLayer(
        {
          id: HEATMAP,
          type: 'heatmap',
          source: HEATMAP,
          maxzoom: 11,
          paint: {
            'heatmap-weight': ['get', weightProperty('risk', 0)],
            'heatmap-color': heatmapColor(),
            'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 9.5, 1, 11, 0],
          },
        },
        firstLabel,
      )
      map.addSource(CHECKPOINTS, { type: 'geojson', data: emptyCollection() })
      map.addLayer({
        id: CHECKPOINTS,
        type: 'circle',
        source: CHECKPOINTS,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 4, 8, 6, 11, 8],
          'circle-color': riskColorMatch(MUTED),
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.5,
        },
      })
      setLoaded(true)
    })
    // Lets the e2e test check how the slider updates the map. Dev server only.
    if (import.meta.env.DEV) (window as unknown as { __map?: MapLibreMap }).__map = map
    popupRef.current = new Popup({ closeButton: false, closeOnClick: false, maxWidth: '260px', offset: 10 })
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      setLoaded(false)
    }
  }, [])

  // Draw a new plan: one line source per route (lineMetrics enables line-progress gradients).
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded || !plan) return
    const subscriptions: Subscription[] = []
    const markers: Marker[] = []

    for (const route of plan.routes) {
      map.addSource(routeSource(route.id), {
        type: 'geojson',
        lineMetrics: true,
        data: { type: 'Feature', properties: { id: route.id }, geometry: { type: 'LineString', coordinates: route.geometry } },
      })
      map.addLayer(
        {
          id: casingLayer(route.id),
          type: 'line',
          source: routeSource(route.id),
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#ffffff', 'line-width': 7 },
        },
        CHECKPOINTS,
      )
      map.addLayer(
        {
          id: lineLayer(route.id),
          type: 'line',
          source: routeSource(route.id),
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-width': 4, 'line-gradient': solidGradient(MUTED) },
        },
        CHECKPOINTS,
      )
      subscriptions.push(
        map.on('click', lineLayer(route.id), () => onSelectRef.current(route.id)),
        map.on('mouseenter', lineLayer(route.id), () => (map.getCanvas().style.cursor = 'pointer')),
        map.on('mouseleave', lineLayer(route.id), () => (map.getCanvas().style.cursor = '')),
      )
    }

    const features = plan.routes.flatMap((route) =>
      route.checkpoints.map((c, index) => ({
        type: 'Feature' as const,
        properties: { route: route.id, index, level: c.level },
        geometry: { type: 'Point' as const, coordinates: [c.lon, c.lat] },
      })),
    )
    map.getSource<GeoJSONSource>(CHECKPOINTS)?.setData({ type: 'FeatureCollection', features })

    // The heatmap's grid spacing is fixed per plan, so its radius and intensity are set here.
    map.getSource<GeoJSONSource>(HEATMAP)?.setData(heatmapFeatures(plan.heatmap))
    map.setPaintProperty(HEATMAP, 'heatmap-radius', heatmapRadius(plan.heatmap))
    map.setPaintProperty(HEATMAP, 'heatmap-intensity', heatmapIntensity(plan.heatmap))

    const showCheckpoint = (event: MapLayerMouseEvent) => {
      const props = event.features?.[0]?.properties
      const route = plan.routes.find((r) => r.id === props?.route)
      const checkpoint = route?.checkpoints[props?.index]
      if (!route || !checkpoint) return
      map.getCanvas().style.cursor = 'pointer'
      popupRef.current?.setLngLat([checkpoint.lon, checkpoint.lat]).setDOMContent(checkpointPopup(route.id, checkpoint)).addTo(map)
    }
    subscriptions.push(
      map.on('mouseenter', CHECKPOINTS, showCheckpoint),
      map.on('click', CHECKPOINTS, showCheckpoint),
      map.on('mouseleave', CHECKPOINTS, () => {
        map.getCanvas().style.cursor = ''
        popupRef.current?.remove()
      }),
    )

    truckRef.current = new Marker({ element: truckMarker() })
    markers.push(
      truckRef.current,
      new Marker({ element: endpointMarker('A', 'Start') }).setLngLat([plan.request.origin.lon, plan.request.origin.lat]).addTo(map),
      new Marker({ element: endpointMarker('B', 'Destination') })
        .setLngLat([plan.request.destination.lon, plan.request.destination.lat])
        .addTo(map),
    )

    const bounds = new LngLatBounds()
    for (const route of plan.routes) for (const point of route.geometry) bounds.extend(point)
    // Keep the routes clear of the legend (top left), and of the timeline (bottom) with the scale
    // and attribution that sit above it.
    // Only elements that float over the map count (on phones the timeline sits below the map instead).
    const overlay = (selector: string) => {
      const el = container.current?.parentElement?.querySelector<HTMLElement>(selector)
      return el && getComputedStyle(el).position === 'absolute' ? el.offsetHeight : 0
    }
    const top = overlay('.legend') + 40
    const bottom = overlay('.timeline') + overlay('.maplibregl-ctrl-bottom-right') + 32
    map.fitBounds(bounds, { padding: { top, bottom, left: 64, right: 64 }, duration: 600 })

    return () => {
      subscriptions.forEach((s) => s.unsubscribe())
      markers.forEach((m) => m.remove())
      truckRef.current = null
      popupRef.current?.remove()
      for (const route of plan.routes) {
        if (map.getLayer(lineLayer(route.id))) map.removeLayer(lineLayer(route.id))
        if (map.getLayer(casingLayer(route.id))) map.removeLayer(casingLayer(route.id))
        if (map.getSource(routeSource(route.id))) map.removeSource(routeSource(route.id))
      }
      map.getSource<GeoJSONSource>(CHECKPOINTS)?.setData(emptyCollection())
      map.getSource<GeoJSONSource>(HEATMAP)?.setData(emptyCollection())
    }
  }, [plan, loaded])

  // The slider and variable toggle: point the existing layer at another hour's weights.
  // No new layer, no setData and no network; MapLibre re-evaluates the weights in its worker.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    map.setPaintProperty(HEATMAP, 'heatmap-weight', ['get', weightProperty(variable, hour)])
  }, [hour, variable, loaded])

  // The selected route's truck at the slider time. (Its marker is made with the plan, above.)
  useEffect(() => {
    const map = mapRef.current
    const marker = truckRef.current
    if (!map || !marker) return
    if (!truck) {
      marker.remove()
      return
    }
    marker.setLngLat(truck.at).addTo(map)
    marker.getElement().dataset.status = truck.status
  }, [truck, plan, loaded])

  // Selection: the selected route is drawn on top, coloured by risk; the others are muted.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded || !plan) return
    const ordered = [...plan.routes].sort((a, b) => Number(a.id === selectedRouteId) - Number(b.id === selectedRouteId))
    for (const route of ordered) {
      const selected = route.id === selectedRouteId
      map.setPaintProperty(lineLayer(route.id), 'line-gradient', selected ? riskGradient(route.checkpoints) : solidGradient(MUTED))
      map.setPaintProperty(lineLayer(route.id), 'line-width', selected ? 6 : 4)
      map.setPaintProperty(lineLayer(route.id), 'line-opacity', selected ? 1 : 0.75)
      map.setPaintProperty(casingLayer(route.id), 'line-width', selected ? 10 : 7)
      // Keep the checkpoints above every route line.
      map.moveLayer(casingLayer(route.id), CHECKPOINTS)
      map.moveLayer(lineLayer(route.id), CHECKPOINTS)
    }
    map.setFilter(CHECKPOINTS, ['==', ['get', 'route'], selectedRouteId ?? ''])
  }, [plan, selectedRouteId, loaded])

  // A checkpoint picked in the side panel: fly to it and pin its popup.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded || !plan || !focus) return
    const checkpoint = plan.routes.find((r) => r.id === focus.routeId)?.checkpoints[focus.index]
    if (!checkpoint) return
    map.flyTo({ center: [checkpoint.lon, checkpoint.lat], zoom: Math.max(map.getZoom(), 8), duration: 700 })
    popupRef.current?.setLngLat([checkpoint.lon, checkpoint.lat]).setDOMContent(checkpointPopup(focus.routeId, checkpoint)).addTo(map)
  }, [focus, plan, loaded])

  return <div ref={container} className="map" role="region" aria-label="Route map" />
}

function emptyCollection(): GeoJSON.FeatureCollection {
  return { type: 'FeatureCollection', features: [] }
}

function truckMarker(): HTMLElement {
  const el = document.createElement('div')
  el.className = 'truck-marker'
  el.setAttribute('aria-label', 'Truck position at the slider time')
  el.title = 'Truck position at the slider time'
  return el
}

function endpointMarker(letter: string, label: string): HTMLElement {
  const el = document.createElement('div')
  el.className = 'endpoint-marker'
  el.textContent = letter
  el.setAttribute('aria-label', label)
  el.title = label
  return el
}

/** Popup body built with DOM nodes (no HTML strings). */
function checkpointPopup(routeId: string, c: Checkpoint): HTMLElement {
  const root = document.createElement('div')
  root.className = 'checkpoint-popup'
  const add = (tag: string, className: string, text: string) => {
    const el = document.createElement(tag)
    el.className = className
    el.textContent = text
    root.appendChild(el)
    return el
  }
  const level = add('div', `popup-level level-${c.level}`, riskLabel(c.level))
  if (c.factor) level.textContent += ` · ${c.factor}${c.load_adjusted ? ' + load' : ''}`
  add('div', 'popup-title', `Route ${routeId} · mile ${Math.round(c.mile)}`)
  add('div', 'popup-row', `Arrives ${formatDateTime(c.eta)}`)
  const w = c.weather
  add(
    'div',
    'popup-row',
    w.wind_mph === null
      ? 'No forecast for this hour'
      : `Wind ${w.wind_mph.toFixed(0)} mph · Rain ${w.rain_in_hr?.toFixed(2)} in/hr · Snow ${w.snow_in_hr?.toFixed(2)} in/hr`,
  )
  add('div', 'popup-note', `Forecast for ${formatDateTime(c.forecast_hour)}`)
  return root
}
