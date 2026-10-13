# Phase log

A running record of what each phase delivered, the decisions behind it, and what's next. It's for anyone resuming the work: a new Claude Code session, or a reviewer. The plan itself is in [PLAN.md](../PLAN.md); the README holds setup, the API and assumptions.

**Live app:** https://weather-truck-routing.wittywave-86ad3def.eastasia.azurecontainerapps.io

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

## After Phase 5: replayed e2e tests and a persistent cache

- **The trigger:** repeated live e2e runs used up Open-Meteo's free **hourly** (5,000) and then **daily** (10,000) limits on 2026-10-12.
- **E2E fixtures by default:** `npm run e2e` replays recorded HERE and Open-Meteo responses from `frontend/e2e/fixtures/` (about 1 MB), making no live calls. In replay, Django's `httpx.Client` uses a transport with no network at all (`routing/http_fixtures.py`) and a fake HERE key, and "now" is frozen to the recording time in both Django (`FROZEN_NOW`, DEBUG only) and the browser (`page.clock.setFixedTime`). HERE is stored per request, without the key; Open-Meteo is stored per location, so replay doesn't depend on batching or cache state. `E2E_RECORD=1` re-records, and `E2E_LIVE=1` runs only `live.spec.ts`, a one-plan smoke test. The e2e servers use their own ports (8001 and 5174) and never reuse a running server.
- **Recording bug caught:** the recorder returned decompressed JSON with the original `Content-Encoding: gzip` header, so httpx tried to gunzip it again. The unit tests had used an uncompressed mock, so they missed it. A regression test now covers it.
- **Re-plan test is now 10 → 50 mi:** the daily limit ran out before the 10 mi re-plan's ~112 extra locations could be recorded. The 50 mi plan's weather cells are a subset of the 25 mi plan's, so it's covered by the recording and exercises the same re-plan path. Switch back to 10 mi with a fresh `E2E_RECORD=1` run, if wanted.
- **Persistent cache:** a SQLite file (`backend/cache.sqlite3`) via Django's `DatabaseCache`, in WAL mode with `synchronous=NORMAL`. The table is created on the first connection. Measured for a plan's 450 entries: set 49 ms, get 8 ms. Django's file cache took 5.7 s, because it lists the cache directory on every write. TTLs are unchanged: weather 30 min, routes 1 h, geocoding 24 h. Two subprocess tests check that the cache survives a restart and that entries expire.
- **Render caveat:** the free tier's disk is wiped on restart, redeploy and spin-down (after 15 min idle), and free services can't attach a disk. The SQLite cache helps within a running instance, including sharing between gunicorn workers, but not across a Render sleep. That would need Render Key Value; it's a Phase 6 decision.
- **Quota-aware 503s:** Open-Meteo's 429 body names the limit. Hourly and daily limits are no longer retried after 5 s, and the 503 now names the limit, with a `Retry-After` until it resets.
- **Truck marker:** hidden at the departure instant, too, so it no longer covers the A marker.
- **Tests:** 205 backend, 40 frontend unit, and 2 e2e specs (replay) all pass.

## Phase 6: deployment, edge cases, README and walkthrough (2026-10-12)

**Live:** https://weather-truck-routing.wittywave-86ad3def.eastasia.azurecontainerapps.io (Azure Container Apps)

- **Serving:** Django serves the React build. WhiteNoise serves `frontend/dist` at `/`, and `config/spa.py` returns `index.html` (`no-cache`) for every non-API path. `/assets/*` is immutable and pre-gzipped. In production the API renders JSON only.
- **Image:** the multi-stage `Dockerfile` is built by `.github/workflows/image.yml` on every push to `main` and published to GHCR (public, so no pull credentials). This was the first time the Dockerfile was ever built; there's no Docker on the dev machine.
- **Render, abandoned:** creating a Blueprint requires a card, even for a free service. `render.yaml` is kept (with `autoDeployTrigger`, since `autoDeploy` is deprecated), and the README has the manual no-Blueprint route.
- **Azure, as deployed:**
  - The user's Azure for Students subscription only grants Contributor on one existing resource group, `rg_autox`, which holds another project (`autox`). With the user's go-ahead, our resources went into it, tagged `project=weather-truck-routing`: the Container Apps environment `wtr-env2` (Consumption only, no log workspace) and the app `weather-truck-routing` (0.5 vCPU / 1 GiB, scale 0–1, port 10000).
  - The secrets `here-api-key` and `django-secret-key` were read and generated locally without ever being printed.
  - Azure Container Registry was impossible (no rights to register the provider), hence GHCR.
- **Azure lessons:**
  - The first environment was an *express* environment: a single `--latest` revision and no revision suffixes. An environment-variable update never reached the running revision, so the app answered 400 everywhere.
  - Recreating with `--enable-workload-profiles false` and `DJANGO_ALLOWED_HOSTS` set at creation worked first time. The express environment and the broken app were deleted, after checking their tags.
  - The `CONTAINER_APP_NAME` + `CONTAINER_APP_ENV_DNS_SUFFIX` hostname detection is in the settings but didn't work in practice. Set `DJANGO_ALLOWED_HOSTS` explicitly.
- **Live checks** (no HERE or Open-Meteo calls):
  - `/api/health` returns 200 `{"status":"ok"}`.
  - `/` and deep links return the app; assets are immutable and gzipped; unknown `/api/` paths return 404.
  - The page boots in Chromium with no console errors, the map renders, and there's no `__map` hook.
- **Bugs found and fixed:**
  - **Same place:** identical From and To crashed `/api/plan` with a 500. It's now a 400 (under 1 mile apart), checked before any provider call.
  - **Cache table race:** the race fix didn't work, because `createcachetable` re-raises database errors as `CommandError`. A 6-process test failed intermittently, which caught it.
  - **Locked cache file:** a fresh SQLite file switching to WAL under contention gave "database is locked" (caught by looping the suite 25 times). The container now runs `manage.py createcachetable` before gunicorn starts, plus a 20 s SQLite lock timeout. After the fix: 30 of 30 runs of that test passed, then 25 of 25 full-suite runs.
  - **Phones:** the timeline covered most of the map, and the attribution sat inside the card. Below 860 px the timeline now sits under the map, and `fitBounds` only counts overlays that float over the map.
  - **Network failure:** it showed the browser's raw "Failed to fetch"; it now says "Couldn't reach the server…". A failed re-plan now says the routes shown are from the previous plan.
- **Bundle:** split into the app (27 KB, 10 KB gzipped), React (78 KB gzipped) and MapLibre (286 KB gzipped). An app update re-downloads only the 10 KB part.
- **README:**
  - **Architecture:** a Mermaid diagram plus the planner pipeline.
  - **Edge cases:** a table of each case and where it's tested; one case is marked as not directly tested.
  - **Deployment:** the actual Azure steps and lessons, plus Render.
  - **Walkthrough:** a 5-minute script for the screen recording.
- **Tests:** 216 backend, 40 frontend unit, and 10 e2e (replay; adds `errors.spec.ts` and `mobile.spec.ts`).

## After Phase 6: abuse protection

- **Per-IP throttles** (DRF): `/api/plan` 10 a minute and 100 a day, `/api/geocode` 60 a minute. Over the limit: 429 with `Retry-After` and a plain message. The client IP is the last `X-Forwarded-For` entry behind Azure's ingress (`NUM_PROXIES=1`).
- **Daily HERE cap:** `HERE_DAILY_CAP` (default 300) requests to HERE per UTC day, counted before sending. At the cap, plan and place search answer 503 "Daily demo limit reached. Try again tomorrow…" without calling HERE; cached answers still work.
- **Usage log:** each HERE request logs the day's running total to stdout.
- **Counters** live in their own `limits` cache (`rate_limits` table), so provider-cache culling can't reset them. They do reset when the container restarts (see the README's Limitations).
- **E2E:** the suite raises the throttles and (in replay) the cap. Fixed an old flaky locator: the map's scale bar can also read "50 mi".
- **Live check of planning:** done on 2026-10-13 (Dallas → Denver, all checks passed), with the user's go-ahead.
- **Checked on Azure:** a temporary endpoint (since removed) showed that Azure's ingress replaces any `X-Forwarded-For` with just the client's IP (no port), the same on every connection, so `NUM_PROXIES=1` reads the right address. Over one kept-alive connection, the 61st place search in a minute got a 429. Sequential requests over new connections took about 1.3 s each (a new TLS handshake to East Asia every time), so they never reached 60 in a minute. That first looked like the limit not working, and led to a wrong fix (dropping a port that Azure doesn't send), which was reverted. A parallel burst over separate connections, which would show both gunicorn workers sharing the count, wasn't run on the live app.
- **Tests:** 229 backend (13 new in `test_limits.py`), 40 frontend unit, and 10 e2e (60 of 60 over 6 repeats).

## Open items

- **Markers:** the A and B endpoint markers cover the city labels underneath. Small cosmetic fix.
- **Live e2e runs:** `E2E_RECORD=1` and `E2E_LIVE=1` each cost about 350–450 Open-Meteo locations; keep them rare. The default replay run is free.
- **Heatmap above zoom 11:** it fades out between zoom 9.5 and 11, where the blur radius gets very large. The checkpoints carry the detail there.
- **Azure access:** the deploy lives in someone else's subscription (`rg_autox`, Contributor only). If that access is removed, the app goes down. The README's Azure commands recreate it anywhere.
