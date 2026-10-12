"""Weather heatmap data for the trip corridor, hourly for 48 hours from departure.

Heatmap points are cells of the shared 0.1-degree weather grid (see grid.py),
so they share forecasts with the checkpoints. The heatmap uses every k-th cell
(k = 1, 2, 3...) within a corridor radius of the routes, plus the cell under
every route point so a coarse grid never drops the road itself. The map's
heatmap blur carries colour beyond the corridor.

Open-Meteo bills per location (free tier: 600 a minute). The heatmap takes the
finest spacing and widest corridor (15 mi, narrowing to 8 mi) that keep the
plan's total locations, counting the checkpoints at the densest 10-mile
interval, within ``LOCATION_BUDGET``. Sizing it for the densest interval means
the heatmap is the same whichever interval is picked, so switching interval
reuses its cached forecasts.

Risk uses the same rules and load as the checkpoints, so the heatmap and the
route colours always agree.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil, cos, floor, radians

from .geometry import MI_PER_DEG_LAT, resample
from .grid import LATTICE_DEG, Cell, center
from .risk import assess
from .sampling import LatLon, haversine_mi
from .weather import Forecast

HOURS = 48  # the slider runs from +0 h to +48 h, so there are HOURS + 1 frames
MAX_POINTS = 300
MIN_POINTS = 100  # floor for very long trips whose checkpoints alone use up the budget
LOCATION_BUDGET = 450  # per plan, checkpoints + heatmap: a 25% margin under 600/minute
CELL_MULTIPLES = (1, 2, 3, 4, 5, 6, 8, 10)  # heatmap spacing in lattice cells (0.1 deg ... 1.0 deg)
RADII_MI = (15.0, 12.0, 10.0, 8.0)  # widest first
ALONG_STEP_MI = 3.0  # route sampling; well under the finest cell (~7 mi) so no cell is skipped


@dataclass(frozen=True)
class Corridor:
    cells: list[Cell]
    cell_deg: float
    """Heatmap spacing; the map sizes the heatmap radius from it."""
    radius_mi: float

    @property
    def points(self) -> list[LatLon]:
        return [center(c) for c in self.cells]


def corridor(
    routes: list[list[LatLon]],
    reserved: set[Cell] = frozenset(),
    max_points: int = MAX_POINTS,
    budget: int = LOCATION_BUDGET,
) -> Corridor:
    """The finest heatmap whose cells, together with ``reserved`` (checkpoint cells), fit the budget."""
    samples = list(dict.fromkeys(p for coords in routes for p in resample(coords, ALONG_STEP_MI)))

    def fits(cells: set[Cell]) -> bool:
        return len(cells) <= max_points and len(cells | reserved) <= budget

    smallest: Corridor | None = None
    for multiple in CELL_MULTIPLES:
        # The narrowest corridor is the cheapest; if even that doesn't fit, try coarser spacing.
        narrow = _lattice_cells(samples, multiple, RADII_MI[-1])
        if not fits(narrow):
            if smallest is None and len(narrow) <= MIN_POINTS:
                smallest = _corridor(narrow, multiple, RADII_MI[-1])
            continue
        for radius in RADII_MI[:-1]:
            cells = _lattice_cells(samples, multiple, radius)
            if fits(cells):
                return _corridor(cells, multiple, radius)
        return _corridor(narrow, multiple, RADII_MI[-1])
    # Checkpoints alone exceed the budget (very long trip at a 10-mile interval): use a small heatmap.
    return smallest or _corridor(narrow, CELL_MULTIPLES[-1], RADII_MI[-1])


def _corridor(cells: set[Cell], multiple: int, radius: float) -> Corridor:
    return Corridor(cells=sorted(cells), cell_deg=round(multiple * LATTICE_DEG, 1), radius_mi=radius)


def _lattice_cells(samples: list[LatLon], multiple: int, radius_mi: float) -> set[Cell]:
    """Every ``multiple``-th lattice cell within ``radius_mi`` of a sample, in lattice indices."""
    return {(i * multiple, j * multiple) for i, j in _cells_near(samples, multiple * LATTICE_DEG, radius_mi)}


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
