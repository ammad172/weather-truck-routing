# Frontend

React + TypeScript (Vite) with MapLibre GL for the map and TanStack Query for API calls. See the root [README](../README.md) for the full project.

```powershell
npm install
npm run dev          # http://localhost:5173; /api is proxied to Django on :8000
npm test             # unit tests (Vitest), run in America/Chicago to exercise local time
npm run typecheck
npm run lint
npm run build
npm run e2e          # starts Django + Vite and drives Chromium; calls the live HERE/Open-Meteo APIs
```

Before the first `npm run e2e`, run `npx playwright install chromium` once.

## Structure

- `src/api/`: API types (mirroring the Django response) and the fetch client.
- `src/lib/time.ts`: **every** date and time shown to the user goes through this file, in the browser's local timezone. The API itself works in UTC.
- `src/lib/risk.ts`: risk colors and labels, and the `line-gradient` expression that colors a route by its checkpoints' risk.
- `src/components/MapView.tsx`: MapLibre map: routes, checkpoints, popups and route selection.
- `src/components/TripForm.tsx` and `PlaceInput.tsx`: the trip form, with accessible place autosuggest.
- `src/components/RoutePanel.tsx`: the recommendation, route cards and the checkpoint table.
