import pytest

from routing.geometry import destination_point, initial_bearing, overlap_ratio, simplify
from routing.sampling import haversine_mi

from .fakes import north


def line(start, end, n=100):
    return [(start[0] + (end[0] - start[0]) * i / (n - 1), start[1] + (end[1] - start[1]) * i / (n - 1)) for i in range(n)]


def test_simplify_collapses_a_straight_line_to_its_endpoints():
    coords = line((35.0, -100.0), (36.0, -99.0))
    assert simplify(coords) == [coords[0], coords[-1]]


def test_simplify_keeps_corners():
    coords = line((35.0, -100.0), (36.0, -100.0), 50) + line((36.0, -100.0), (36.0, -99.0), 50)[1:]
    assert simplify(coords) == [(35.0, -100.0), (36.0, -100.0), (36.0, -99.0)]


def test_simplify_short_lines_unchanged():
    assert simplify([(1.0, 2.0), (3.0, 4.0)]) == [(1.0, 2.0), (3.0, 4.0)]


def test_identical_routes_fully_overlap():
    coords = line((35.0, -100.0), north((35.0, -100.0), 100))
    assert overlap_ratio(coords, coords) == 1.0


def test_parallel_routes_far_apart_do_not_overlap():
    a = line((35.0, -100.0), north((35.0, -100.0), 100))
    b = [(lat, lon + 0.5) for lat, lon in a]  # ~28 mi east
    assert overlap_ratio(a, b) == 0.0


def test_partial_overlap_is_measured_from_the_first_route():
    a = line((35.0, -100.0), north((35.0, -100.0), 100))
    b = a[:50]  # second route covers only the first half
    assert overlap_ratio(a, b) == pytest.approx(0.5, abs=0.05)
    assert overlap_ratio(b, a) == 1.0


def test_bearing_and_destination_point_round_trip():
    start = (35.0, -100.0)
    assert initial_bearing(start, (36.0, -100.0)) == pytest.approx(0)
    assert initial_bearing(start, (35.0, -99.0)) == pytest.approx(90, abs=1)
    east = destination_point(start, 90, 20)
    assert haversine_mi(start, east) == pytest.approx(20, rel=1e-6)
    assert east[1] > start[1]
