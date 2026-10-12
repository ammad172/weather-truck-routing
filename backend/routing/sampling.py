"""Place weather checkpoints along a route polyline every N miles.

Checkpoints sit at the origin, at every multiple of the interval, and at the
destination. Each one represents the stretch of road halfway back to the
previous checkpoint and halfway on to the next, so ``segment_miles`` across a
route always adds up to the route's length. Risk miles are computed from it.
"""

from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate, pairwise
from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_MI = 3958.7613
ALLOWED_INTERVALS_MI = (10, 25, 50)

# Below this, the destination is treated as coinciding with the last interval mark.
_SAME_POINT_MI = 1e-6

LatLon = tuple[float, float]


@dataclass(frozen=True)
class Checkpoint:
    lat: float
    lon: float
    mile: float
    """Distance from the origin along the route."""
    segment_miles: float
    """Length of road this checkpoint's weather stands for."""


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MI * asin(sqrt(h))


def cumulative_miles(coords: list[LatLon]) -> list[float]:
    """Distance from the first coordinate to each coordinate, in miles."""
    return [0.0, *accumulate(haversine_mi(a, b) for a, b in pairwise(coords))]


def point_at_mile(coords: list[LatLon], cum: list[float], mile: float) -> LatLon:
    """Linearly interpolate the position ``mile`` miles along the polyline."""
    if mile <= 0:
        return coords[0]
    if mile >= cum[-1]:
        return coords[-1]
    i = bisect_right(cum, mile) - 1
    span = cum[i + 1] - cum[i]
    t = (mile - cum[i]) / span if span else 0.0
    (lat1, lon1), (lat2, lon2) = coords[i], coords[i + 1]
    return lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t


def sample_checkpoints(coords: list[LatLon], interval_mi: float) -> list[Checkpoint]:
    if len(coords) < 2:
        raise ValueError("A route needs at least two coordinates.")
    if interval_mi <= 0:
        raise ValueError("Checkpoint interval must be positive.")

    cum = cumulative_miles(coords)
    total = cum[-1]

    # k * interval (not repeated addition) so float error can't drift on long routes.
    marks: list[float] = []
    k = 0
    while k * interval_mi < total - _SAME_POINT_MI:
        marks.append(k * interval_mi)
        k += 1
    marks.append(total)

    checkpoints = []
    for i, mark in enumerate(marks):
        before = (mark - marks[i - 1]) / 2 if i > 0 else 0.0
        after = (marks[i + 1] - mark) / 2 if i < len(marks) - 1 else 0.0
        lat, lon = point_at_mile(coords, cum, mark)
        checkpoints.append(Checkpoint(lat=lat, lon=lon, mile=mark, segment_miles=before + after))
    return checkpoints
