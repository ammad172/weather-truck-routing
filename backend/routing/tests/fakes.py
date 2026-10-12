"""In-memory routing and weather providers for planner, fallback and view tests."""

from datetime import datetime, timedelta

from routing.providers.base import Place, ProviderRoute
from routing.sampling import LatLon, haversine_mi
from routing.weather import HourlyWeather

MI_PER_DEG_LAT = haversine_mi((0.0, 0.0), (1.0, 0.0))


def straight_route(start: LatLon, end: LatLon, hours: float, points: int = 200, spans: int = 4) -> ProviderRoute:
    """A straight-line route with evenly split spans (constant speed)."""
    coords = [
        (start[0] + (end[0] - start[0]) * i / (points - 1), start[1] + (end[1] - start[1]) * i / (points - 1))
        for i in range(points)
    ]
    step = (points - 1) // spans
    return ProviderRoute(
        coords=coords,
        distance_m=haversine_mi(start, end) * 1609.344,
        duration_s=hours * 3600,
        span_offsets=[k * step for k in range(spans)],
        span_durations_s=[hours * 3600 * (step if k < spans - 1 else points - 1 - k * step) / (points - 1) for k in range(spans)],
    )


def north(start: LatLon, miles: float) -> LatLon:
    return start[0] + miles / MI_PER_DEG_LAT, start[1]


class FakeRouting:
    """Returns preset routes; detour routes are looked up by the via point's side (east/west)."""

    def __init__(self, routes: list[ProviderRoute], detours: dict[str, ProviderRoute] | None = None):
        self.routes = routes
        self.detours = detours or {}
        self.calls: list[dict] = []

    def geocode(self, query: str, limit: int = 5) -> list[Place]:
        known = {"dallas": Place("Dallas, TX, United States", 32.77823, -96.7951)}
        return [p for key, p in known.items() if key in query.lower()][:limit]

    def truck_routes(self, origin, destination, departure, gross_weight_kg, alternatives=2, via=None):
        self.calls.append({"via": via, "alternatives": alternatives, "gross_weight_kg": gross_weight_kg})
        if via is None:
            return self.routes[: alternatives + 1]
        side = "east" if via[1] > origin[1] else "west"
        return [self.detours[side]] if side in self.detours else []


class FakeWeather:
    """Calm everywhere, except chosen conditions east of a longitude (to make one route risky)."""

    def __init__(self, calm=HourlyWeather(5.0, 0.0, 0.0), stormy=None, stormy_east_of: float | None = None):
        self.calm, self.stormy, self.stormy_east_of = calm, stormy, stormy_east_of
        self.requests: list[tuple[int, datetime, datetime]] = []

    def hourly(self, points, start, end):
        self.requests.append((len(points), start, end))
        hours = [start + timedelta(hours=h) for h in range(int((end - start).total_seconds() // 3600) + 1)]
        out = []
        for lat, lon in points:
            stormy = self.stormy is not None and self.stormy_east_of is not None and lon > self.stormy_east_of
            out.append({h: self.stormy if stormy else self.calm for h in hours})
        return out
