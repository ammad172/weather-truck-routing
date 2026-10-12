# Plan: Weather-Aware Truck Routing (React + Django)

## Context
Take-home assessment (spec: `ASSIGNMENT.md` and the PDF in `docs/`, both kept local and git-ignored). The core priorities are the routing/weather/risk/recommendation logic and a smooth map and heatmap. Spec says "prioritize correctness and clarity over extra features" — so the plan keeps scope tight, puts the risk logic in pure, heavily tested functions, and makes the 0–48h slider purely client-side so it stays smooth.

Implementation should happen in a **new Claude Code session started from `C:\Projects\weather-truck-routing`** (so Playwright MCP is loaded). Copy this plan into the repo as `PLAN.md` as step 0.

## Stack & external services
| Concern | Choice | Why |
|---|---|---|
| Backend | Django 5 + Django REST Framework, Python 3.12, `httpx` | Required stack; httpx for concurrent provider calls |
| Frontend | Vite + React + TypeScript, TanStack Query | Fast dev, typed API contracts |
| Map | **MapLibre GL JS** + **OpenFreeMap Positron** style (`https://tiles.openfreemap.org/styles/positron`) | WebGL; native `heatmap` layer updates via `setData` → smooth slider. OpenFreeMap needs no key or signup, has no request limits, and allows commercial use. Requires OpenStreetMap/OpenMapTiles attribution, which MapLibre shows automatically. Positron's light grey base keeps routes and heatmap readable |
| Routing | **HERE Routing v8, `transportMode=truck`, `alternatives=2`**, with `truck[grossWeight]` from load weight | Truck-aware, returns up to 3 routes + per-span durations; free tier. Wrapped behind a `RoutingProvider` interface so Mapbox/ORS can be swapped in |
| Geocoding | HERE Autosuggest/Geocode (same key), proxied via Django | Keeps key server-side |
| Weather | **Open-Meteo** hourly forecast (`wind_speed_10m`, `rain`, `snowfall`, `precipitation`; `wind_speed_unit=mph`, `precipitation_unit=inch`, `timezone=UTC`) | Free, no key, 16-day horizon, multi-coordinate batch requests |
| Hosting | One Render web service (Docker): Django serves the built React app via WhiteNoise | One URL, no CORS, simplest to demo |

**HERE account facts (checked 2026-10-12):** Base Plan signup **requires a credit card on file**, and you are charged only if you go over a service's free monthly allowance. Third-party trackers list roughly 5,000 free Routing transactions per month and 30,000 for Geocoding & Search. HERE's own pricing page doesn't publish numbers, so confirm them in the console after signup. With caching, development plus a demo uses a few hundred calls. `alternatives` accepts 0–6, but HERE returns *up to* that many; it is not guaranteed. **The key lives only in the backend environment (`HERE_API_KEY`).** The browser calls `/api/geocode` and `/api/plan`, never HERE directly.

**No-card fallback provider:** openrouteservice `driving-hgv` (free key, no card). ORS only gives native alternatives for trips under 100 km, so with ORS all 3 routes come from the via-point strategy below. It plugs into the same `RoutingProvider` interface.

**Guaranteeing 3 routes:** if the provider returns fewer than 3, generate extra candidates by re-routing through a via-point offset perpendicular to the route midpoint (±~10% of trip length), dedupe routes with >90% shared geometry, and label them clearly. If a corridor really has only 1–2 distinct roads, show what exists and explain why, rather than inventing near-duplicates.

## Core logic (backend `routing/` app, pure functions, no I/O)
1. **Checkpoint sampling** (`sampling.py`): walk the decoded polyline, place a checkpoint at origin, every N miles (N ∈ {10, 25, 50}, picked by the user in a selector on the form and sent as `interval_mi`), and at destination. Each checkpoint stores `mile` and `segment_miles`, the stretch of road it represents. That stretch runs halfway to the previous checkpoint and halfway to the next, so the segments add up exactly to the route length.
2. **ETA per checkpoint** (`eta.py`): interpolate time along the route using the provider's per-span durations (fallback: distance-proportional on total duration). ETA = departure + elapsed. Weather is then read at **the forecast hour nearest the ETA**.
3. **Risk classification** (`risk.py`), levels `LOW=0, MODERATE=1, HIGH=2, SEVERE=3, NO_TRAVEL=4`:
   - Wind: `<25` L, `[25,35)` M, `[35,45)` H, `[45,55)` S, `≥55` NT
   - Rain (in/hr): `<0.10` L, `[0.10,0.25)` M, `[0.25,0.50)` H, `[0.50,1.00]` S, `>1.00` NT
   - Snow (in/hr): `<0.5` L, `[0.5,1.0)` M, `[1.0,2.0)` H, `[2.0,3.0]` S, `>3.0` NT
   - Load overrides on wind: `≥55` → NT for any load; `[45,55)` and `>30,000 lb` → NT; `[35,45)` and `>40,000 lb` → Severe
   - Checkpoint level = **max** of the wind, rain and snow levels, keeping the "driving factor" so the UI can explain it.
   - The spec's ranges share their endpoints, so they are resolved as above. This is written down in the README "Assumptions" section.
4. **Route summary** (`recommend.py`): per route, `no_travel_miles`, `severe_miles`, `high_miles`, distance-weighted `avg_risk` (0–4), `duration`, `distance`.
5. **Recommendation:** sort routes lexicographically by `(no_travel_miles, severe_miles, high_miles, round(avg_risk, 2), duration)`. No Travel miles rank first (strictly worse than Severe), then the spec's order. Return a human-readable reason, e.g. "Route B: 0 Severe miles vs 25 on A". If every route has No Travel segments, still rank them but return a prominent warning.

## Heatmap (0–48 h slider)
- Backend builds a corridor grid: points along the union of all 3 routes every ~10 mi, plus offsets of ±15 and ±30 mi perpendicular to the route. This is capped at about 400 points, deduped on a 0.1° grid.
- One batched Open-Meteo request (chunks of ~100 coords, run concurrently) returns 49 hourly values per point, starting from the current hour.
- The response sends compact arrays (`points[]`, `risk[point][hour]` as small ints, plus raw wind/precip/snow). The slider only swaps the GeoJSON weights client-side and **never refetches**. `setData` is throttled with `requestAnimationFrame`.
- The heatmap shows forecast risk at the slider hour. A toggle switches between risk, wind, precipitation and snow.

## API
- `GET /api/geocode?q=` → suggestions
- `POST /api/plan` with `{origin, destination, departure_iso, weight_lb, interval_mi}` → `{routes:[{id, geometry, summary, checkpoints:[{lat, lon, mile, eta, wind, rain, snow, level, factor}]}], recommendation:{route_id, reason, ranking}, heatmap:{origin_time, points, hours:49, risk, wind, precip, snow}}`
- Validation: departure from now to 14 days ahead, weight from 1 to 80,000 lb, interval in {10, 25, 50}. Provider errors map to clear 4xx/502 messages.
- Caching (Django cache, locmem → Redis optional): geocode 24 h, route 1 h, weather on a rounded lat/lon + model-run hour for 30 min.

## Frontend layout
- Left panel: form (autosuggest origin/destination, datetime-local, weight in lb, interval selector), then route cards (recommended badge, duration, distance, Severe/High miles, avg risk, reason).
- Map: three route lines (recommended one bold, others muted; click to select), checkpoint circles colored by level with a popup (ETA, mile, wind/rain/snow, factor), heatmap layer under the routes, legend.
- Bottom: 0–48 h slider with timestamp and play/pause, plus a heatmap variable toggle.
- Use the **frontend-design** plugin for the visual pass, and **context7** for current MapLibre/DRF/HERE docs.
- **Times are always shown in the user's local timezone, never UTC.**
  - The API sends and receives ISO 8601 timestamps with an offset, in UTC.
  - The browser formats every ETA, forecast hour, slider label and departure with `Intl.DateTimeFormat` in its own timezone, and shows the short zone name (e.g. "2:30 PM CDT").
  - The `datetime-local` departure input is read as local time and sent as ISO with the browser's offset.
  - All formatting goes through one helper (`lib/time.ts`) so no component formats dates on its own.
  - This is checked with Vitest under a fixed non-UTC zone (`TZ=America/Chicago`).

## Repo layout
```
backend/  config/ (settings, urls)  routing/ (providers/here.py, providers/base.py,
          weather.py, sampling.py, eta.py, risk.py, recommend.py, heatmap.py,
          serializers.py, views.py, tests/)  requirements.txt  manage.py
frontend/ src/ (api/, components/MapView.tsx, RoutePanel.tsx, TripForm.tsx,
          ForecastSlider.tsx, lib/riskColors.ts, types.ts)  vite.config.ts
Dockerfile  render.yaml  .env.example  README.md  PLAN.md  ASSIGNMENT.md  docs/
```

## Build order (commit after each)
0. `git branch -m main`, add `.gitignore` (which excludes `ASSIGNMENT.md` and the PDF) and `PLAN.md`. Make the first commit and push.
1. Django skeleton, plus `risk.py`, `sampling.py`, `eta.py` and `recommend.py` **with tests first** (boundary values for every threshold, load overrides, ranking ties).
2. HERE provider and Open-Meteo client, with recorded JSON fixtures so tests run offline. Then the `/api/plan` endpoint and the 3-route guarantee.
3. Heatmap grid builder and payload.
4. React app: form → map → routes/checkpoints → route cards.
5. Heatmap layer, slider and legend. Profile the slider (target 60 fps on 400 pts × 49 h).
6. Dockerfile (multi-stage: Node builds `frontend/dist` → Python image; Django + WhiteNoise serve `/api/*` and the SPA with an `index.html` catch-all) and Render deploy as **one web service**. README covers setup, architecture diagram, assumptions, API keys and limits, plus a **cold-start note**: Render's free tier sleeps after ~15 min idle, so the first request can take ~30–60 s. Reviewers should open the URL once and wait, or the service runs on a paid instance during review.
7. Loom script outline in the README (not recorded by Claude).

## What you need to provide
- A **HERE developer API key** (free, platform.here.com). Put it in `backend/.env` as `HERE_API_KEY`. Never commit it.
- A **Render account** for hosting, and pushing to GitHub. Claude will ask before any deploy or push.

## Verification
- `pytest backend` covers every threshold boundary (24.9/25/34.9/35/44.9/45/54.9/55 mph; rain/snow edges), each load rule, ranking order and tie-breaks, sampling counts for 10/25/50 mi, and ETA monotonicity.
- `npm run build` and `npm run lint`/`tsc` pass.
- Manual and Playwright MCP end-to-end run on the local dev servers: Dallas TX → Denver CO, departing tomorrow 08:00, 42,000 lb, 25 mi. Check that 3 routes render, the checkpoints' ETAs increase, the recommended badge matches the ranking, and dragging the slider 0→48 updates the heatmap with no network requests (check the Network tab).
- A high-wind sanity test: mock a checkpoint at 47 mph with 35,000 lb and confirm it shows No Travel and the route is ranked last.
- Hosted URL loads and completes the same trip.
