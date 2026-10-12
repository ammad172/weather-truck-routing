# Frontend

React + TypeScript (Vite) with MapLibre GL for the map and TanStack Query for API calls. See the root [README](../README.md) for the full project.

```powershell
npm install
npm run dev          # http://localhost:5173; /api is proxied to Django on :8000
npm test             # unit tests (Vitest), run in America/Chicago to exercise local time
npm run typecheck
npm run lint
npm run build
npm run e2e          # end-to-end tests in Chromium, replaying recorded API responses (no live calls)
```

Before the first `npm run e2e`, run `npx playwright install chromium` once.

## End-to-end tests

The e2e tests start their own Django server (port 8001) and Vite server (port 5174), and drive Chromium through the real app. They never reuse a server that's already running. They have three modes:

| Command | HERE and Open-Meteo | Runs |
|---|---|---|
| `npm run e2e` | **Replayed** from `e2e/fixtures/`. No live calls, no key needed. | `plan.spec.ts`, `heatmap.spec.ts` |
| `E2E_RECORD=1 npm run e2e` | Live, and every response is saved as a new fixture set (needs the HERE key in `backend/.env`) | the same specs |
| `E2E_LIVE=1 npm run e2e` | Live, nothing saved: a smoke test that the real APIs still work | `live.spec.ts` only |

- **How replay works:** Django swaps its HTTP transport for one that answers from the fixture files and has no network access, so an unrecorded request fails with "No recorded fixture for …" in the server log. HERE responses are stored per request, without the API key. Open-Meteo responses are stored per location, so replay doesn't depend on how the backend batches its requests.
- **Frozen time:** the recorded requests contain the departure hour and the forecast window. Replay therefore freezes "now", in Django (`FROZEN_NOW`, honoured only with `DJANGO_DEBUG=1`) and in the browser (`page.clock.setFixedTime`), to the recording time in `e2e/fixtures/recording.json`.
- **Re-record** when the API requests change, for example new parameters or a different test trip. A record or live run makes about 450 Open-Meteo location calls. The free tier allows 600 a minute and 5,000 an hour.
- **Basemap:** the tiles still load from OpenFreeMap, which needs no key and has no quota.
- **Real GPU:** `E2E_GPU=1` runs Chromium on the real GPU for realistic frame timings. By default, headless Chromium renders WebGL in software.

## Structure

- `src/api/`: API types (mirroring the Django response) and the fetch client.
- `src/lib/time.ts`: **every** date and time shown to the user goes through this file, in the browser's local timezone. The API itself works in UTC.
- `src/lib/risk.ts`: risk colors and labels, and the `line-gradient` expression that colors a route by its checkpoints' risk.
- `src/components/MapView.tsx`: MapLibre map: routes, checkpoints, popups and route selection.
- `src/components/TripForm.tsx` and `PlaceInput.tsx`: the trip form, with accessible place autosuggest.
- `src/components/RoutePanel.tsx`: the recommendation, route cards and the checkpoint table.
- `src/lib/heatmap.ts`, `ForecastTimeline.tsx` and `Legend.tsx`: the forecast heatmap (calibrated blur and neighbour-max smoothing), the 0–48 h slider and the legend.
- `src/lib/truck.ts`: the truck's position on the selected route at the slider time.
