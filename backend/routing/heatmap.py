"""Weather heatmap data for the trip corridor, hourly for 48 hours from departure.

The corridor is every grid cell whose centre is within 15 miles of any route,
plus the cell under every point of every route (so a coarse grid never drops
the road itself). The map's heatmap blur carries colour beyond that. The grid
is regular so the heatmap blends evenly; its cell size grows until the
corridor fits in the point limit. The limit exists because Open-Meteo meters
usage per location: see ``planner.FREE_HEATMAP_POINTS``.

Risk uses the same rules and load as the checkpoints, so the heatmap and the
route colours always agree.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from math import ceil, cos, floor, radians

from .geometry import MI_PER_DEG_LAT, resample
from .risk import assess
from .sampling import LatLon, haversine_mi
from .weather import Forecast

HOURS = 48  # the slider runs from +0 h to +48 h, so there are HOURS + 1 frames
DEFAULT_MAX_POINTS = 300
CORRIDOR_RADIUS_MI = 15.0
ALONG_STEP_MI = 3.0  # route sampling; well under the finest cell (~7 mi) so no cell is skipped
START_CELL_DEG = 0.1
CELL_GROWTH = 1.2


@dataclass(frozen=True)
class Corridor:
    points: list[LatLon]
    cell_deg: float
    """Grid spacing; the map sizes the heatmap radius from it."""


def corridor(routes: list[list[LatLon]], max_points: int = DEFAULT_MAX_POINTS) -> Corridor:
    samples = list(dict.fromkeys(p for coords in routes for p in resample(coords, ALONG_STEP_MI)))
    cell = START_CELL_DEG
    while True:
        cells = _cells_near(samples, cell, CORRIDOR_RADIUS_MI)
        if len(cells) <= max_points:
            points = sorted((round(i * cell, 4), round(j * cell, 4)) for i, j in cells)
            return Corridor(points=points, cell_deg=round(cell, 4))
        cell *= CELL_GROWTH


def _cells_near(samples: list[LatLon], cell: float, radius_mi: float) -> set[tuple[int, int]]:
    """Grid cells (as integer indices) whose centre is within ``radius_mi`` of a sample, plus each sample's own cell."""
    cells: set[tuple[int, int]] = set()
    for lat, lon in samples:
        cells.add((round(lat / cell), round(lon / cell)))
        dlat = radius_mi / MI_PER_DEG_LAT
        dlon = radius_mi / (MI_PER_DEG_LAT * max(cos(radians(lat)), 0.01))
        for i in range(ceil((lat - dlat) / cell), floor((lat + dlat) / cell) + 1):
            for j in range(ceil((lon - dlon) / cell), floor((lon + dlon) / cell) + 1):
                if (i, j) not in cells and haversine_mi((lat, lon), (i * cell, j * cell)) <= radius_mi:
                    cells.add((i, j))
    return cells


def build(corridor: Corridor, forecasts: list[Forecast], start: datetime, weight_lb: float) -> dict:
    """Point-major arrays: ``risk[p][h]`` is point p at ``start`` + h hours. None where there's no forecast."""
    hours = [start + timedelta(hours=h) for h in range(HOURS + 1)]
    risk, wind, rain, snow = [], [], [], []
    for forecast in forecasts:
        row_risk, row_wind, row_rain, row_snow = [], [], [], []
        for hour in hours:
            w = forecast.get(hour)
            if w is None or not w.complete:
                row_risk.append(None)
                row_wind.append(None)
                row_rain.append(None)
                row_snow.append(None)
                continue
            row_risk.append(int(assess(w.wind_mph, w.rain_in_hr, w.snow_in_hr, weight_lb).level))
            row_wind.append(round(w.wind_mph, 1))
            row_rain.append(round(w.rain_in_hr, 2))
            row_snow.append(round(w.snow_in_hr, 2))
        risk.append(row_risk)
        wind.append(row_wind)
        rain.append(row_rain)
        snow.append(row_snow)
    return {
        "start": start.isoformat(timespec="seconds"),
        "hours": HOURS,
        "cell_deg": corridor.cell_deg,
        # GeoJSON order ([lon, lat]), like route geometry.
        "points": [[lon, lat] for lat, lon in corridor.points],
        "risk": risk,
        "wind_mph": wind,
        "rain_in_hr": rain,
        "snow_in_hr": snow,
    }
