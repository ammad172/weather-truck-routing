# Weather-Aware Truck Routing

A React + Django web app that helps a truck driver choose the safest route between two places, based on forecast weather along the way, the truck's load weight, and travel time.

> **Status:** work in progress. The risk, checkpoint, ETA and recommendation logic is built and tested. Routing and weather providers, the API, and the React map UI are next. See [PLAN.md](PLAN.md).

## Backend setup

Requires Python 3.12+.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy ..\.env.example .env      # then fill in the values
.\.venv\Scripts\python.exe manage.py runserver
```

On macOS/Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe` and `cp` in place of `copy`.

Health check: `GET http://127.0.0.1:8000/api/health` returns `{"status": "ok"}`.

### Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

## Assumptions

### Risk thresholds and their boundaries

The assessment gives the bands as ranges that share their endpoints, for example rain "0.10–0.25" is Moderate and "0.25–0.50" is High. A value exactly on a shared endpoint goes into the **higher** band. This matches how the spec words its open ends: "<25 mph" is Low and "≥55 mph" is No Travel.

The one exception is where the spec's top band is a strict "greater than". Rain is No Travel only **above** 1.00 in/hr and snow only **above** 3.0 in/hr, so exactly 1.00 in/hr of rain and exactly 3.0 in/hr of snow are still Severe.

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph) | < 25 | 25 to < 35 | 35 to < 45 | 45 to < 55 | ≥ 55 |
| Rain (in/hr) | < 0.10 | 0.10 to < 0.25 | 0.25 to < 0.50 | 0.50 to 1.00 | > 1.00 |
| Snow (in/hr) | < 0.5 | 0.5 to < 1.0 | 1.0 to < 2.0 | 2.0 to 3.0 | > 3.0 |

Wind bands written as whole numbers in the spec ("25–34") are treated as continuous, so 34.9 mph is Moderate and 35 mph is High.

### Load rules

Load rules only change the **wind** level, and can only make it worse:

- ≥ 55 mph: No Travel for any load.
- 45 to < 55 mph with a load **over** 30,000 lb: No Travel. Exactly 30,000 lb stays Severe.
- 35 to < 45 mph with a load **over** 40,000 lb: Severe. Exactly 40,000 lb stays High.

A checkpoint's overall level is the worst of its wind, rain and snow levels. When two conditions tie, the one listed first in the spec (wind, then rain, then snow) is reported as the cause.

### Route recommendation and No Travel

Routes are compared one criterion at a time, moving to the next only on a tie:

1. **Fewest No Travel miles** (added; see below)
2. Fewest Severe miles
3. Fewest High miles
4. Lowest average risk
5. Shortest travel time

The spec's preference list starts at Severe and doesn't mention No Travel. No Travel is the worst level, so a route with any No Travel miles always ranks below one without, however many Severe miles the other has. Without this rule, a route crossing No Travel conditions could be recommended for having "0 Severe miles". If every route has No Travel miles, the safest is still ranked first, but the app shows a warning suggesting a later departure.

To keep tiny rounding differences from deciding the result, miles are compared to 0.1 mi and average risk to 0.01. Anything closer than that counts as a tie and falls through to the next criterion.

### Checkpoints and risk miles

- Checkpoints sit at the origin, at every 10, 25 or 50 miles (the user picks), and at the destination.
- Each checkpoint's weather stands for the road halfway back to the previous checkpoint and halfway on to the next. So "Severe miles" adds up the stretches around Severe checkpoints, and the stretches always sum to the route's length.
- Average risk is distance-weighted on a 0–4 scale: Low 0, Moderate 1, High 2, Severe 3, No Travel 4.

### Arrival times and forecast hour

- The ETA at each checkpoint comes from the travel time the routing provider reports for each stretch of road, not one average speed for the whole trip.
- Weather is read at the forecast hour nearest the ETA, with :30 rounding up. All times are handled in UTC.
