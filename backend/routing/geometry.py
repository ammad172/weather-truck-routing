"""Polyline helpers: simplification for the map, and route overlap / offset maths."""

from math import asin, atan2, cos, degrees, radians, sin, sqrt

from .sampling import EARTH_RADIUS_MI, LatLon, cumulative_miles, point_at_mile

MI_PER_DEG_LAT = 69.0


def simplify(coords: list[LatLon], tolerance_deg: float = 0.0005) -> list[LatLon]:
    """Douglas-Peucker simplification (~50 m default) for drawing; never drops the endpoints.

    Only the line sent to the map is simplified. Checkpoints and ETAs use the full line.
    """
    if len(coords) < 3:
        return list(coords)
    keep = [False] * len(coords)
    keep[0] = keep[-1] = True
    stack = [(0, len(coords) - 1)]
    while stack:
        first, last = stack.pop()
        worst, worst_i = 0.0, -1
        for i in range(first + 1, last):
            d = _perpendicular_deg(coords[i], coords[first], coords[last])
            if d > worst:
                worst, worst_i = d, i
        if worst > tolerance_deg:
            keep[worst_i] = True
            stack.extend(((first, worst_i), (worst_i, last)))
    return [c for c, k in zip(coords, keep) if k]


def _perpendicular_deg(p: LatLon, a: LatLon, b: LatLon) -> float:
    (py, px), (ay, ax), (by, bx) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return sqrt((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2)


def resample(coords: list[LatLon], step_mi: float) -> list[LatLon]:
    """Points every ``step_mi`` along the line (plus its end)."""
    cum = cumulative_miles(coords)
    count = int(cum[-1] // step_mi)
    return [point_at_mile(coords, cum, k * step_mi) for k in range(count + 1)] + [coords[-1]]


def overlap_ratio(a: list[LatLon], b: list[LatLon], tolerance_mi: float = 0.5, step_mi: float = 1.0) -> float:
    """Share of route ``a`` (sampled every ``step_mi``) lying within ``tolerance_mi`` of route ``b``."""
    samples_a = resample(a, step_mi)
    ref_lat = radians(samples_a[0][0])
    mi_per_deg_lon = MI_PER_DEG_LAT * cos(ref_lat)

    def xy(p: LatLon) -> tuple[float, float]:
        return p[1] * mi_per_deg_lon, p[0] * MI_PER_DEG_LAT

    # Hash b's points (sampled finer than the tolerance) into tolerance-sized grid cells.
    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for p in resample(b, tolerance_mi / 2):
        x, y = xy(p)
        grid.setdefault((int(x // tolerance_mi), int(y // tolerance_mi)), []).append((x, y))

    def near_b(p: LatLon) -> bool:
        x, y = xy(p)
        cx, cy = int(x // tolerance_mi), int(y // tolerance_mi)
        return any(
            (x - qx) ** 2 + (y - qy) ** 2 <= tolerance_mi**2
            for gx in (cx - 1, cx, cx + 1)
            for gy in (cy - 1, cy, cy + 1)
            for qx, qy in grid.get((gx, gy), ())
        )

    return sum(near_b(p) for p in samples_a) / len(samples_a)


def initial_bearing(a: LatLon, b: LatLon) -> float:
    """Compass bearing in degrees from ``a`` towards ``b``."""
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    y = sin(lon2 - lon1) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(lon2 - lon1)
    return (degrees(atan2(y, x)) + 360) % 360


def destination_point(start: LatLon, bearing_deg: float, distance_mi: float) -> LatLon:
    """The point ``distance_mi`` from ``start`` along ``bearing_deg`` (great circle)."""
    lat1, lon1 = map(radians, start)
    d = distance_mi / EARTH_RADIUS_MI
    b = radians(bearing_deg)
    lat2 = asin(sin(lat1) * cos(d) + cos(lat1) * sin(d) * cos(b))
    lon2 = lon1 + atan2(sin(b) * sin(d) * cos(lat1), cos(d) - sin(lat1) * sin(lat2))
    return degrees(lat2), (degrees(lon2) + 540) % 360 - 180
