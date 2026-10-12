"""Plan a trip: routes -> checkpoints -> ETAs -> weather at each ETA -> risk -> recommendation."""

import string
from dataclasses import dataclass
from datetime import datetime

from .alternatives import three_routes
from .eta import TimeProfile, checkpoint_etas, nearest_forecast_hour
from .geometry import simplify
from .providers.base import Place, ProviderRoute, RoutingProvider
from .recommend import RouteSummary, recommend, summarize_route
from .risk import RiskLevel, assess
from .sampling import Checkpoint, cumulative_miles, sample_checkpoints
from .weather import HourlyWeather, WeatherProvider

METERS_PER_MILE = 1609.344
KG_PER_LB = 0.45359237
# HERE routes on the truck's *gross* weight (bridge and road limits), but the
# user enters the *load*. A typical empty tractor-trailer weighs ~35,000 lb.
TRACTOR_TRAILER_TARE_LB = 35_000
# Points closer than this share one weather lookup (~1 km; finer than the forecast grid).
WEATHER_ROUNDING = 2


class NoRouteError(Exception):
    """The routing provider found no truck route between the two places."""


@dataclass(frozen=True)
class TripRequest:
    origin: Place
    destination: Place
    departure: datetime
    weight_lb: float
    interval_mi: int


def gross_weight_kg(load_lb: float) -> int:
    return round((TRACTOR_TRAILER_TARE_LB + load_lb) * KG_PER_LB)


def time_profile(route: ProviderRoute, cum: list[float]) -> TimeProfile:
    """Map provider spans onto our own mile markers so ETAs and checkpoints agree on distance."""
    miles = [cum[offset] for offset in route.span_offsets] + [cum[-1]]
    seconds = [0.0]
    for duration in route.span_durations_s:
        seconds.append(seconds[-1] + duration)
    return TimeProfile(miles=tuple(miles), seconds=tuple(seconds))


def plan_trip(trip: TripRequest, routing: RoutingProvider, weather: WeatherProvider) -> dict:
    origin = (trip.origin.lat, trip.origin.lon)
    destination = (trip.destination.lat, trip.destination.lon)
    route_set = three_routes(routing, origin, destination, trip.departure, gross_weight_kg(trip.weight_lb))
    if not route_set.routes:
        raise NoRouteError(" ".join(route_set.notes))

    # 1. Checkpoints and ETAs for every route.
    planned = []
    for candidate in route_set.routes:
        coords = candidate.route.coords
        checkpoints = sample_checkpoints(coords, trip.interval_mi)
        etas = checkpoint_etas([c.mile for c in checkpoints], time_profile(candidate.route, cumulative_miles(coords)), trip.departure)
        planned.append((candidate, checkpoints, etas))

    # 2. One weather fetch for every checkpoint on every route, covering all their forecast hours.
    keys = {_weather_key(c) for _, checkpoints, _ in planned for c in checkpoints}
    points = sorted(keys)
    hours = [nearest_forecast_hour(t) for _, _, etas in planned for t in etas]
    forecasts = dict(zip(points, weather.hourly(points, min(hours), max(hours))))

    # 3. Risk at each checkpoint, then per-route summaries and the recommendation.
    routes_out, summaries, missing = [], [], 0
    for label, (candidate, checkpoints, etas) in zip(string.ascii_uppercase, planned):
        rows = []
        for checkpoint, eta in zip(checkpoints, etas):
            hour = nearest_forecast_hour(eta)
            conditions = forecasts[_weather_key(checkpoint)].get(hour)
            if conditions is None or not conditions.complete:
                missing += 1
            rows.append(_checkpoint_row(checkpoint, eta, hour, conditions, trip.weight_lb))
        summary = summarize_route(
            label,
            [(row["segment_miles"], RiskLevel(row["level"])) for row in rows],
            distance_mi=candidate.route.distance_m / METERS_PER_MILE,
            duration_s=candidate.route.duration_s,
        )
        summaries.append(summary)
        routes_out.append(_route_payload(label, candidate.source, candidate.route, summary, rows))

    best = recommend(summaries)
    notes = list(route_set.notes)
    if missing:
        notes.append(f"{missing} checkpoint(s) had no forecast data for their arrival hour and were counted as Low risk.")

    return {
        "request": {
            "origin": _place(trip.origin),
            "destination": _place(trip.destination),
            "departure": trip.departure.isoformat(),
            "weight_lb": trip.weight_lb,
            "gross_weight_lb": TRACTOR_TRAILER_TARE_LB + trip.weight_lb,
            "interval_mi": trip.interval_mi,
        },
        "routes": routes_out,
        "recommendation": {
            "route_id": best.route_id,
            "ranking": best.ranking,
            "reason": best.reason,
            "warning": best.warning,
        },
        "notes": notes,
    }


def _weather_key(c: Checkpoint) -> tuple[float, float]:
    return round(c.lat, WEATHER_ROUNDING), round(c.lon, WEATHER_ROUNDING)


def _checkpoint_row(
    checkpoint: Checkpoint, eta: datetime, hour: datetime, conditions: HourlyWeather | None, weight_lb: float
) -> dict:
    wind = conditions.wind_mph if conditions else None
    rain = conditions.rain_in_hr if conditions else None
    snow = conditions.snow_in_hr if conditions else None
    risk = assess(wind or 0.0, rain or 0.0, snow or 0.0, weight_lb)
    return {
        "mile": round(checkpoint.mile, 1),
        "segment_miles": round(checkpoint.segment_miles, 3),
        "lat": round(checkpoint.lat, 5),
        "lon": round(checkpoint.lon, 5),
        "eta": eta.isoformat(timespec="seconds"),
        "forecast_hour": hour.isoformat(timespec="seconds"),
        "weather": {"wind_mph": wind, "rain_in_hr": rain, "snow_in_hr": snow},
        "level": int(risk.level),
        "level_label": risk.level.label,
        "factor": risk.factor,
        "load_adjusted": risk.load_adjusted,
    }


def _route_payload(label: str, source: str, route: ProviderRoute, summary: RouteSummary, rows: list[dict]) -> dict:
    return {
        "id": label,
        "source": source,
        "distance_mi": round(summary.distance_mi, 1),
        "duration_s": round(summary.duration_s),
        "summary": {
            "no_travel_miles": round(summary.no_travel_miles, 1),
            "severe_miles": round(summary.severe_miles, 1),
            "high_miles": round(summary.high_miles, 1),
            "avg_risk": round(summary.avg_risk, 2),
            "worst_level": int(summary.worst_level),
            "worst_level_label": summary.worst_level.label,
        },
        # GeoJSON order ([lon, lat]) so the map can use it directly.
        "geometry": [[round(lon, 5), round(lat, 5)] for lat, lon in simplify(route.coords)],
        "checkpoints": rows,
    }


def _place(p: Place) -> dict:
    return {"label": p.label, "lat": p.lat, "lon": p.lon}
