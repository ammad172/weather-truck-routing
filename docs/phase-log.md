# Phase log

A running record of what each phase delivered, the decisions behind it, and what's next. It's for anyone resuming the work: a new Claude Code session, or a reviewer. The plan itself is in [PLAN.md](../PLAN.md); the README holds setup, the API and assumptions.

**Resume from:** `C:\Projects\weather-truck-routing`. Start Claude Code there so the project's Playwright MCP server loads. The frontend-design and context7 plugins are installed at user level and load on session start.

**Local-only files (git-ignored):**
- `ASSIGNMENT.md` and `docs/*.pdf`: the assessment brief.
- `backend/.env`: the HERE key.

---

## Phase 0: setup (2026-10-12)

- **Tools:** git, Node 24, npm, gh. Python 3.12 is installed per user and is now on the user PATH.
- **GitHub:** logged in with `gh` (browser login). Public repo `ammad172/weather-truck-routing` on branch `main`.
- **Claude Code:** Playwright MCP is registered at local scope for this folder. The frontend-design and context7 plugins are installed.
- **API keys:** HERE API key in `backend/.env`. Open-Meteo needs no key; **we use the free tier only, with no paid key, by decision.**

## Phase 1: core risk logic (`0893137`)

- Built `risk.py`, `sampling.py`, `eta.py` and `recommend.py` as pure functions, with tests.
- **Decision: band boundaries.** A value on an endpoint shared by two bands goes to the higher band. Rain above 1.00 and snow above 3.0 in/hr are No Travel, so exactly 1.00 and 3.0 are still Severe. Documented in the README.
- **Decision: ranking order.** No Travel miles rank before Severe miles, then High miles, average risk, and travel time. Miles are compared at 0.1 and average risk at 0.01, so tiny differences count as ties.
- **Decision: risk miles.** Each checkpoint covers half the gap to each neighbour, so risk miles always add up to the route length.

## Phase 2: providers and `/api/plan` (`a8eca0a`, `832dc10`)

- **HERE Routing v8:** truck mode, with gross weight = load plus an assumed 35,000 lb for the empty truck. Uses `speedLimit` spans for travel time per stretch of road. Also HERE geocoding.
- **Third route fallback:** routes through a point beside the fastest route when HERE returns fewer than 3. Detours with 90% or more overlap, or over 1.5× the fastest time, are rejected. The detour requests run in parallel; that brought a cold fallback trip down from 5.6 s to 2.7 s.
- **Weather:** Open-Meteo hourly wind, rain and snowfall in mph and inches, read at each checkpoint's ETA hour.
- **Tests:** recorded fixtures keep them offline. Error messages never contain the key, and tests check that.

## Phase 3: heatmap data (`42d1a30`)

- **Heatmap:** 49 hourly frames starting at the **departure hour**. The slider is labelled "hours after departure". Risk at each point uses the trip's load.
- **Discovery: Open-Meteo bills per location.** The free tier allows 600 a minute and 10,000 a day. That shaped everything after it.
- **Caching:** per location, covering the departure day plus 2 days, in a compact form. Django's in-memory cache was raised from its default of 300 entries, which had been silently evicting entries. Successful batches are kept when another batch fails.
- **Forecast range:** requests stop at Open-Meteo's last forecast hour (23:00 UTC, 15 days out). Departures can be at most 13 days ahead.

## Phase 4: React UI (`809b1e3`)

- **Stack:** Vite 8, React 19 and TypeScript 6 (strict), MapLibre GL 6 on OpenFreeMap Positron, TanStack Query.
- **Form:** accessible place autosuggest. The 10/25/50-mile selector re-plans as soon as it changes.
- **Map and panel:** the selected route is colored by risk with a `line-gradient` step on `line-progress`. Checkpoint popups, route cards with risk bars, and a checkpoint table.
- **Times:** all user-facing times go through `src/lib/time.ts` in the browser's timezone. Vitest runs in America/Chicago, and the e2e test asserts "CDT" appears and "UTC" never does.
- **Bugs the Playwright e2e test caught:**
  - MapLibre's worker URL breaks under Vite pre-bundling. Fixed with `setWorkerUrl` plus a `?url` import.
  - A one-color `step` expression is invalid and dropped every route layer. Fixed, and covered by a unit test.

## After Phase 4: weather budget hardening

- **The trigger:** back-to-back cold e2e runs hit Open-Meteo's per-minute limit, and re-plans returned errors.
- **Shared 0.1° grid (`grid.py`):** all weather lookups snap to it and are de-duplicated, so checkpoints reuse heatmap cells and interval switches reuse the cache. A lookup moves at most about 4.5 mi. The README's "Weather grid snapping" section has the accuracy reasoning.
- **Heatmap sizing:** the heatmap is every k-th grid cell. The backend picks the finest spacing, then the widest corridor (15→8 mi), with at most 300 points **and** checkpoints plus heatmap within 450 locations. Checkpoints are counted at the 10-mile interval, so the grid doesn't change between intervals.
- **Measured on Dallas → Denver, back to back:**

  | Request | Locations in plan | New fetches | Time |
  |---|---|---|---|
  | Cold, 25 mi | 342 | 342 | 3.4 s |
  | Switch to 10 mi | 439 | 112 | 0.9 s |
  | Switch to 50 mi or back to 25 | | 0 | 0.6 s |

  That's 454 in the minute, down from about 510. The heatmap now has 268 points at 0.2° (about 14 mi), finer than the earlier 17 mi.
- **Rate limits:** a 429 gets one short backoff and retry (5 s, or `Retry-After` up to 10 s). If that fails too, the API returns **503** with a clear "busy, wait about a minute" message, which the UI shows.
- **Paid-key code removed:** the `OPEN_METEO_API_KEY` path is gone, since we're not using a paid key.
- **Tests:** 190 backend and 15 frontend unit tests pass.

---

## Phase 5: heatmap layer, slider and legend (2026-10-12)

- **Layer:** one MapLibre `heatmap` layer, created once at map load, under the basemap labels and the routes. A new plan calls `setData` once. Each feature carries `risk0`…`risk48`, `wind0`…, `rain0`…, `snow0`… as precomputed weights. The slider and the variable toggle **only** call `setPaintProperty(heatmap-weight, ["get", "<var><h>"])`.
- **Variables:** wind, rain and snow are classified into their own risk bands (wind before the load rules). All four views share one color ramp, and the legend shows the variable's band values under the same five colors.
- **Slider (`ForecastTimeline.tsx`):** "+N h after departure · <local time>", with ticks at Departure, +12 h, +24 h, +36 h and +48 h. It has play/pause and the Risk/Wind/Rain/Snow toggle. The track is a strip of 49 hourly cells colored by the worst level in the corridor, with a needle thumb and the selected route's "Arrives" mark.
- **Truck position (`lib/truck.ts`):** the mile is interpolated between checkpoint ETAs, then placed along the route line. The marker is hidden while parked at A or B, and the timeline text gives the status.
- **Legend:** one card with five aligned columns: the route colors, the heatmap bar, then the band values.
- **Decision: calibrated blur.** MapLibre's kernel is a Gaussian with σ = radius/3. With radius = 1.5 × row spacing (exponential in zoom) and intensity = cos φ / (0.2785 × 1.5²), the corridor's density equals each point's weight, within ±3%. Each color has a flat ±0.06 stretch on the ramp, so the ripple can't change a color. Weights are scaled by cos(lat)/cos(maxLat) for Mercator row spacing.
- **Decision: spread hazards (found from the screenshots).** At first the map stayed green while the strip said Moderate. Summing kernels dilutes a lone hazard to about 27–48% of its weight, so a lone Severe cell would draw as Moderate. Fix: each point shows the worst of its 3×3 neighbourhood, and a ghost ring outside the corridor carries edge hazards. Ghosts beside Low cells stay empty, so the corridor keeps its soft edge. Unit tests sum the kernel numerically: a lone Severe cell reads Severe, in the middle and on the edge.
- **Overlays:** `fitBounds` padding is measured from the legend, the timeline and the lifted scale/attribution, so A and B aren't hidden.
- **Performance (Dallas → Denver, 268 points + ghosts):**
  - **`setPaintProperty`:** 0.1–0.3 ms synchronous.
  - **Change on screen:** about 33 ms on a GPU (worker re-evaluation plus a frame).
  - **Fast drag:** 260 mouse moves at one per frame, longest frame 17 ms on a GPU. Headless Chromium uses SwiftShader (about 30 ms a frame for the map alone), where the longest frame is 50–100 ms. Set `E2E_GPU=1` to run the e2e test on the real GPU.
  - **Event burst:** 200 synthetic events in one task block for about 0.7 s in the dev build. This is a stress test, not a realistic input.
- **Tests:** 39 frontend unit tests. New `e2e/heatmap.spec.ts`, instrumented through `window.__map` (dev server only). It asserts that a fast drag and a 200-event burst cause **no** `addLayer`, `removeLayer`, `addSource`, `setData` or other paint calls besides `heatmap-weight`, and **no** network requests. The final weight matches the slider. It also covers the keyboard, play/pause and the variable toggle (exactly one call), and saves 5 screenshots. Playwright now runs with `workers: 1`, so the second spec reuses the server's weather cache.

## Next: Phase 6

- Dockerfile with Django and WhiteNoise serving the build, a Render deploy, the README cold-start note, and the Loom outline.

## Open items

- **Bundle size:** the main JS bundle is 1.3 MB (371 KB gzipped), mostly MapLibre. Split chunks in Phase 6.
- **Markers:** the A and B endpoint markers cover the city labels underneath. Small cosmetic fix.
- **E2E rate limits:** the tests call the live APIs, and each run starts Django with a cold cache, so about 450 locations go to Open-Meteo per run. Back-to-back runs can hit the per-minute limit (a 503); wait a minute between runs.
- **Heatmap above zoom 11:** it fades out between zoom 9.5 and 11, where the blur radius gets very large. The checkpoints carry the detail there.
