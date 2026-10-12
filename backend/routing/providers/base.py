"""Provider-neutral types for routing and geocoding.

The planner only depends on these, so a different routing provider (e.g.
openrouteservice) can be added without touching the risk or ranking code.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..sampling import LatLon


class ProviderError(Exception):
    """A third-party API failed. The message is safe to show to users (no keys or URLs)."""


@dataclass(frozen=True)
class Place:
    label: str
    lat: float
    lon: float


@dataclass(frozen=True)
class ProviderRoute:
    coords: list[LatLon]
    distance_m: float
    duration_s: float
    span_offsets: list[int]
    """Index into ``coords`` where each span starts; the first is always 0."""
    span_durations_s: list[float]
    """Travel time for each span. Sums to ``duration_s``."""


class RoutingProvider(Protocol):
    def geocode(self, query: str, limit: int = 5) -> list[Place]: ...

    def truck_routes(
        self,
        origin: LatLon,
        destination: LatLon,
        departure: datetime,
        gross_weight_kg: int,
        alternatives: int = 2,
        via: LatLon | None = None,
    ) -> list[ProviderRoute]: ...
