"""The shared 0.1-degree weather grid.

Every weather lookup (checkpoints and heatmap) is snapped to the centre of a
cell on this lattice and de-duplicated, so nearby lookups share one forecast:
checkpoints reuse heatmap cells, routes share cells where they overlap, and
switching the checkpoint interval mostly hits cells that are already cached.
Open-Meteo bills per location, so this directly cuts weather calls.

A snapped point is at most ~0.07 deg (~4-5 mi) from the real one. See the
README ("Weather grid snapping") for why that's an acceptable trade.
"""

from .sampling import LatLon

LATTICE_DEG = 0.1

Cell = tuple[int, int]
"""Lattice indices: the cell centred on (i * 0.1, j * 0.1)."""


def cell_of(point: LatLon) -> Cell:
    return round(point[0] / LATTICE_DEG), round(point[1] / LATTICE_DEG)


def center(cell: Cell) -> LatLon:
    # Rounding to 1 decimal keeps keys and request coordinates exact (no 35.300000000000004).
    return round(cell[0] * LATTICE_DEG, 1), round(cell[1] * LATTICE_DEG, 1)
