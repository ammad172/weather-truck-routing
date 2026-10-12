"""Hourly forecasts from Open-Meteo (free, no key).

Units are requested to match the risk rules directly: wind in mph, rain and
snowfall in inches. Open-Meteo's hourly ``rain`` and ``snowfall`` are totals
for the preceding hour, i.e. in/hr. ``rain`` excludes snow, and ``snowfall``
is snow depth (not water equivalent), which is what the snow thresholds mean.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
from django.core.cache import cache

from .providers.base import ProviderError
from .sampling import LatLon

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = "wind_speed_10m,rain,snowfall"

BATCH_SIZE = 100  # coordinates per request; keeps URLs well under server limits
MAX_PARALLEL = 4
CACHE_SECONDS = 30 * 60


@dataclass(frozen=True)
class HourlyWeather:
    wind_mph: float | None
    rain_in_hr: float | None
    snow_in_hr: float | None

    @property
    def complete(self) -> bool:
        return None not in (self.wind_mph, self.rain_in_hr, self.snow_in_hr)


Forecast = dict[datetime, HourlyWeather]
"""Hourly weather for one location, keyed by the UTC hour."""


class WeatherProvider(Protocol):
    def hourly(self, points: list[LatLon], start: datetime, end: datetime) -> list[Forecast]: ...


class OpenMeteoClient:
    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=20)

    def hourly(self, points: list[LatLon], start: datetime, end: datetime) -> list[Forecast]:
        """Forecasts for ``points`` (same order) covering the UTC hours ``start``..``end``."""
        if not points:
            return []
        batches = [points[i : i + BATCH_SIZE] for i in range(0, len(points), BATCH_SIZE)]
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(batches))) as pool:
            results = pool.map(lambda batch: self._batch(batch, start, end), batches)
        return [forecast for batch in results for forecast in batch]

    def _batch(self, points: list[LatLon], start: datetime, end: datetime) -> list[Forecast]:
        params = {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in points),
            "hourly": HOURLY_VARIABLES,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "UTC",
            "start_hour": _hour_param(start),
            "end_hour": _hour_param(end),
        }
        key = "wx:" + hashlib.sha256(repr(sorted(params.items())).encode()).hexdigest()
        if (cached := cache.get(key)) is not None:
            return cached

        try:
            response = self._http.get(FORECAST_URL, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Couldn't reach Open-Meteo ({type(exc).__name__}).") from None
        if response.status_code >= 400:
            raise ProviderError(f"Open-Meteo failed ({response.status_code}): {_reason(response)}.")

        forecasts = parse_forecasts(response.json())
        if len(forecasts) != len(points):
            raise ProviderError("Open-Meteo returned a different number of locations than requested.")
        cache.set(key, forecasts, CACHE_SECONDS)
        return forecasts


def parse_forecasts(payload: dict | list) -> list[Forecast]:
    """Open-Meteo returns one object for a single location and a list for several."""
    locations = payload if isinstance(payload, list) else [payload]
    return [_parse_location(loc["hourly"]) for loc in locations]


def _parse_location(hourly: dict) -> Forecast:
    return {
        datetime.fromisoformat(t).replace(tzinfo=UTC): HourlyWeather(wind, rain, snow)
        for t, wind, rain, snow in zip(hourly["time"], hourly["wind_speed_10m"], hourly["rain"], hourly["snowfall"])
    }


def _hour_param(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def _reason(response: httpx.Response) -> str:
    try:
        return str(response.json().get("reason", "unknown error"))[:200]
    except ValueError:
        return "unknown error"
