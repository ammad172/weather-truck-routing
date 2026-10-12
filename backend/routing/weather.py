"""Hourly forecasts from Open-Meteo.

Units are requested to match the risk rules directly: wind in mph, rain and
snowfall in inches. Open-Meteo's hourly ``rain`` and ``snowfall`` are totals
for the preceding hour, i.e. in/hr. ``rain`` excludes snow, and ``snowfall``
is snow depth (not water equivalent), which is what the snow thresholds mean.

Open-Meteo meters usage per *location* (a 100-location request costs ~100
calls; the free tier allows 600/minute and 10,000/day). Callers snap points to
the shared 0.1-degree grid (grid.py), and forecasts are cached per location
for a fixed window (departure day + 2 more): re-running a trip, changing its
departure time or checkpoint interval, or planning an overlapping trip only
fetches locations that aren't cached yet. A 429 gets one short backoff and
retry of just the rate-limited batches, then a clear "busy, try again" error.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from time import sleep
from typing import Protocol

import httpx
from django.core.cache import cache
from django.utils import timezone

from .providers.base import ProviderError, RateLimitedError
from .sampling import LatLon

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = "wind_speed_10m,rain,snowfall"

BATCH_SIZE = 100  # locations per request; keeps URLs well under server limits
MAX_PARALLEL = 4
CACHE_SECONDS = 30 * 60
RETRY_DELAY_S = 5.0  # one short backoff on 429 (or the server's Retry-After, if shorter than the cap)
RETRY_MAX_DELAY_S = 10.0
BUSY_MESSAGE = (
    "The free weather service is busy (too many forecast requests in the last minute). "
    "Please wait about a minute and try again."
)
WINDOW_DAYS = 3  # departure day + 2: covers a 48 h trip or the 48 h heatmap from any departure hour
HORIZON_DAYS = 15  # Open-Meteo serves up to 23:00 UTC this many days after today's UTC date


@dataclass(frozen=True)
class HourlyWeather:
    wind_mph: float | None
    rain_in_hr: float | None
    snow_in_hr: float | None

    @property
    def complete(self) -> bool:
        return None not in (self.wind_mph, self.rain_in_hr, self.snow_in_hr)


Forecast = dict[datetime, HourlyWeather]
"""Hourly weather for one location, keyed by the UTC hour. Hours outside the forecast are absent."""


class WeatherProvider(Protocol):
    def hourly(self, points: list[LatLon], start: datetime, end: datetime) -> list[Forecast]: ...


def forecast_horizon(now: datetime) -> datetime:
    """The last hour Open-Meteo will forecast."""
    return datetime.combine(now.astimezone(UTC).date() + timedelta(days=HORIZON_DAYS), time(23), UTC)


def fetch_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Whole UTC days covering start..end, at least ``WINDOW_DAYS`` long so cache entries are reusable."""
    first = datetime.combine(start.astimezone(UTC).date(), time(0), UTC)
    last = max(first + timedelta(days=WINDOW_DAYS), datetime.combine(end.astimezone(UTC).date() + timedelta(days=1), time(0), UTC))
    return first, last - timedelta(hours=1)


class OpenMeteoClient:
    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=20)

    def hourly(self, points: list[LatLon], start: datetime, end: datetime) -> list[Forecast]:
        """Forecasts for ``points`` (same order) covering at least the UTC hours ``start``..``end``."""
        if not points:
            return []
        first, last = fetch_window(start, end)
        last = min(last, forecast_horizon(timezone.now()))
        if first > last:
            return [{} for _ in points]

        keys = [_cache_key(p, first, last) for p in points]
        found = {k: _unpack(v, first) for k, v in cache.get_many(keys).items()}
        missing = list(dict.fromkeys(k for k in keys if k not in found))
        if missing:
            by_key = dict(zip(keys, points))
            batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
            limited = self._fetch_batches(batches, by_key, first, last, found)
            if limited:
                # One short backoff, then retry only the rate-limited batches.
                sleep(min(max((e.retry_after or RETRY_DELAY_S) for _, e in limited), RETRY_MAX_DELAY_S))
                if self._fetch_batches([b for b, _ in limited], by_key, first, last, found):
                    raise RateLimitedError(BUSY_MESSAGE)
        return [found[k] for k in keys]

    def _fetch_batches(
        self, batches: list[list[str]], by_key: dict[str, LatLon], first: datetime, last: datetime, found: dict[str, Forecast]
    ) -> list[tuple[list[str], RateLimitedError]]:
        """Fetch batches in parallel into ``found`` (and the cache). Returns the rate-limited ones.

        Batches that succeed are kept even if another fails, so a retry only fetches what's
        still missing. Any other error is raised.
        """
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(batches))) as pool:
            futures = [pool.submit(self._fetch, [by_key[k] for k in batch], first, last) for batch in batches]
        fetched: dict[str, Forecast] = {}
        limited, error = [], None
        for batch, future in zip(batches, futures):
            try:
                fetched.update(zip(batch, future.result()))
            except RateLimitedError as exc:
                limited.append((batch, exc))
            except ProviderError as exc:
                error = error or exc
        cache.set_many({k: _pack(f, first, last) for k, f in fetched.items()}, CACHE_SECONDS)
        found.update(fetched)
        if error:
            raise error
        return limited

    def _fetch(self, points: list[LatLon], first: datetime, last: datetime) -> list[Forecast]:
        params = {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in points),
            "hourly": HOURLY_VARIABLES,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "UTC",
            "start_hour": _hour_param(first),
            "end_hour": _hour_param(last),
        }
        try:
            response = self._http.get(FORECAST_URL, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Couldn't reach Open-Meteo ({type(exc).__name__}).") from None
        if response.status_code == 429:
            raise RateLimitedError(BUSY_MESSAGE, retry_after=_retry_after(response))
        if response.status_code >= 400:
            raise ProviderError(f"Open-Meteo failed ({response.status_code}): {_reason(response)}.")

        forecasts = parse_forecasts(response.json())
        if len(forecasts) != len(points):
            raise ProviderError("Open-Meteo returned a different number of locations than requested.")
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


def _pack(forecast: Forecast, first: datetime, last: datetime) -> tuple[list, list, list]:
    """Compact cache form: three hourly lists from ``first``. ~10x smaller than the dict of objects."""
    hours = range(int((last - first).total_seconds() // 3600) + 1)
    rows = [forecast.get(first + timedelta(hours=h)) for h in hours]
    return (
        [r.wind_mph if r else None for r in rows],
        [r.rain_in_hr if r else None for r in rows],
        [r.snow_in_hr if r else None for r in rows],
    )


def _unpack(packed: tuple[list, list, list], first: datetime) -> Forecast:
    return {
        first + timedelta(hours=h): HourlyWeather(wind, rain, snow)
        for h, (wind, rain, snow) in enumerate(zip(*packed))
        if not (wind is None and rain is None and snow is None)
    }


def _cache_key(point: LatLon, first: datetime, last: datetime) -> str:
    return f"wx:{point[0]:.4f},{point[1]:.4f}:{first:%Y%m%d%H}-{last:%Y%m%d%H}"


def _hour_param(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return max(0.0, float(response.headers.get("Retry-After", "")))
    except ValueError:
        return None


def _reason(response: httpx.Response) -> str:
    try:
        return str(response.json().get("reason", "unknown error"))[:200]
    except ValueError:
        return "unknown error"
