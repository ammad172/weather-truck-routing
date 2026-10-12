"""Shared provider clients. Views call these factories so tests can swap in fakes."""

from functools import cache

import httpx
from django.conf import settings

from .planner import FREE_HEATMAP_POINTS, PAID_HEATMAP_POINTS
from .providers.base import RoutingProvider
from .providers.here import HereClient
from .weather import OpenMeteoClient, WeatherProvider


@cache
def _http() -> httpx.Client:
    # One pooled client for the process; httpx.Client is thread-safe.
    return httpx.Client(timeout=20)


def routing_provider() -> RoutingProvider:
    return HereClient(settings.HERE_API_KEY, http=_http())


def weather_provider() -> WeatherProvider:
    return OpenMeteoClient(http=_http(), api_key=settings.OPEN_METEO_API_KEY)


def heatmap_points() -> int:
    """Heatmap grid size; a paid Open-Meteo key's higher limits allow a finer grid."""
    return PAID_HEATMAP_POINTS if settings.OPEN_METEO_API_KEY else FREE_HEATMAP_POINTS
