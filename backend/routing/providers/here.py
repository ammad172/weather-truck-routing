"""HERE Routing v8 (truck mode) and Geocoding & Search v7."""

import hashlib
from datetime import UTC, datetime
from typing import Any

import flexpolyline
import httpx
from django.core.cache import cache

from ..limits import count_here_request
from ..sampling import LatLon
from .base import Place, ProviderError, ProviderRoute

ROUTES_URL = "https://router.hereapi.com/v8/routes"
GEOCODE_URL = "https://geocode.search.hereapi.com/v1/geocode"

# Spans split wherever the speed limit changes, which is where travel speed
# changes. That gives ~10x fewer spans than per-segment spans with the same ETA
# accuracy, and the span durations sum exactly to the route duration.
SPANS = "length,duration,speedLimit"

GEOCODE_COUNTRIES = "countryCode:USA,CAN,MEX"

# Cache keys are built from the request without the API key.
CACHE_SECONDS = {"geocoding": 24 * 3600, "routing": 3600}


class HereClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        if not api_key:
            raise ProviderError("The server is missing its HERE API key.")
        self._key = api_key
        self._http = http or httpx.Client(timeout=20)

    def geocode(self, query: str, limit: int = 5) -> list[Place]:
        payload = self._get(GEOCODE_URL, {"q": query, "limit": limit, "in": GEOCODE_COUNTRIES}, "geocoding")
        return parse_geocode(payload)

    def truck_routes(
        self,
        origin: LatLon,
        destination: LatLon,
        departure: datetime,
        gross_weight_kg: int,
        alternatives: int = 2,
        via: LatLon | None = None,
    ) -> list[ProviderRoute]:
        params: dict[str, Any] = {
            "transportMode": "truck",
            "origin": _latlon(origin),
            "destination": _latlon(destination),
            "return": "polyline,summary",
            "spans": SPANS,
            "departureTime": departure.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "vehicle[grossWeight]": gross_weight_kg,
            "alternatives": alternatives,
        }
        if via is not None:
            # passThrough keeps the route as one section with no stop at the via point.
            params["via"] = f"{_latlon(via)}!passThrough=true"
        return parse_routes(self._get(ROUTES_URL, params, "routing"))

    def _get(self, url: str, params: dict[str, Any], service: str) -> dict:
        cache_key = "here:" + hashlib.sha256(repr((url, sorted(params.items()))).encode()).hexdigest()
        if (cached := cache.get(cache_key)) is not None:
            return cached
        payload = self._fetch(url, params, service)
        cache.set(cache_key, payload, CACHE_SECONDS[service])
        return payload

    def _fetch(self, url: str, params: dict[str, Any], service: str) -> dict:
        count_here_request(service)  # refuses (before sending) once today's cap is reached
        try:
            response = self._http.get(url, params={**params, "apiKey": self._key})
        except httpx.HTTPError as exc:
            # Never include the exception text: it can contain the request URL, and so the key.
            raise ProviderError(f"Couldn't reach HERE {service} ({type(exc).__name__}).") from None
        if response.status_code in (401, 403):
            raise ProviderError(f"HERE {service} rejected the API key.")
        if response.status_code == 429:
            raise ProviderError(f"HERE {service} rate limit reached. Try again shortly.")
        if response.status_code >= 400:
            title = _error_title(response)
            raise ProviderError(f"HERE {service} failed ({response.status_code}){': ' + title if title else ''}.")
        return response.json()


def parse_routes(payload: dict) -> list[ProviderRoute]:
    """Flatten each HERE route (one or more sections) into a single polyline with spans."""
    routes = []
    for route in payload.get("routes", []):
        coords: list[LatLon] = []
        offsets: list[int] = []
        durations: list[float] = []
        distance = duration = 0.0
        for section in route["sections"]:
            points = [(lat, lon) for lat, lon, *_ in flexpolyline.decode(section["polyline"])]
            # Consecutive sections share their joining point; keep it once.
            base = len(coords) - 1 if coords else 0
            coords.extend(points[1:] if coords else points)
            for span in section.get("spans") or [{"offset": 0, "duration": section["summary"]["duration"]}]:
                offsets.append(base + span["offset"])
                durations.append(float(span["duration"]))
            distance += section["summary"]["length"]
            duration += section["summary"]["duration"]
        routes.append(
            ProviderRoute(
                coords=coords,
                distance_m=distance,
                duration_s=duration,
                span_offsets=offsets,
                span_durations_s=durations,
            )
        )
    return routes


def parse_geocode(payload: dict) -> list[Place]:
    return [
        Place(label=item["address"]["label"], lat=item["position"]["lat"], lon=item["position"]["lng"])
        for item in payload.get("items", [])
        if "position" in item
    ]


def _latlon(point: LatLon) -> str:
    return f"{point[0]:.6f},{point[1]:.6f}"


def _error_title(response: httpx.Response) -> str:
    try:
        return str(response.json().get("title", ""))[:200]
    except ValueError:
        return ""
