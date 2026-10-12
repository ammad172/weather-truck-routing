from datetime import UTC, datetime, timedelta

import pytest

from routing.grid import cell_of, center
from routing.heatmap import CELL_MULTIPLES, HOURS, LOCATION_BUDGET, MIN_POINTS, Corridor, build, corridor
from routing.sampling import haversine_mi
from routing.weather import HourlyWeather

from .fakes import north, straight_route

START = datetime(2026, 10, 13, 13, tzinfo=UTC)
ORIGIN = (35.0, -100.0)


def north_line(miles):
    return straight_route(ORIGIN, north(ORIGIN, miles), hours=1).coords


def test_corridor_covers_the_route_and_both_sides():
    grid = corridor([north_line(100)])
    lons = sorted({lon for _, lon in grid.points})
    # 15 mi either side of lon -100 at lat ~35.7 is ~0.27 deg of longitude.
    assert min(lons) == pytest.approx(-100.27, abs=grid.cell_deg)
    assert max(lons) == pytest.approx(-99.73, abs=grid.cell_deg)
    assert any(lon == pytest.approx(-100.0, abs=grid.cell_deg / 2) for lon in lons)
    # The corridor also reaches 15 mi past each end of the route.
    lats = [lat for lat, _ in grid.points]
    assert min(lats) == pytest.approx(ORIGIN[0] - 15 / 69, abs=grid.cell_deg)
    assert max(lats) == pytest.approx(north(ORIGIN, 115)[0], abs=grid.cell_deg)


def test_points_sit_on_a_regular_grid():
    grid = corridor([north_line(100)])
    for lat, lon in grid.points:
        assert lat / grid.cell_deg == pytest.approx(round(lat / grid.cell_deg), abs=1e-3)
        assert lon / grid.cell_deg == pytest.approx(round(lon / grid.cell_deg), abs=1e-3)


def test_the_corridor_has_no_empty_columns():
    grid = corridor([north_line(50)])  # finest grid
    lons = sorted({lon for _, lon in grid.points})
    steps = {round(b - a, 4) for a, b in zip(lons, lons[1:])}
    assert steps == {grid.cell_deg}


@pytest.mark.parametrize(("miles", "max_points"), [(50, 350), (1500, 350), (1500, 150)])
def test_point_count_is_capped_by_growing_the_cells(miles, max_points):
    grid = corridor([north_line(miles)], max_points=max_points)
    assert 0 < len(grid.points) <= max_points
    assert len(set(grid.points)) == len(grid.points)
    if miles == 50:
        assert grid.cell_deg == 0.1  # short trips keep the finest grid
    else:
        assert grid.cell_deg > 0.1


def test_a_bigger_budget_gives_a_finer_or_wider_grid():
    small = corridor([north_line(1500)], max_points=150)
    big = corridor([north_line(1500)], max_points=350)
    assert len(big.points) > len(small.points)
    assert (big.cell_deg, -big.radius_mi) < (small.cell_deg, -small.radius_mi)


@pytest.mark.parametrize("miles", [50, 400, 1500])
def test_heatmap_points_are_cells_of_the_shared_weather_grid(miles):
    grid = corridor([north_line(miles)])
    assert grid.cell_deg in {round(m * 0.1, 1) for m in CELL_MULTIPLES}
    for (i, j), (lat, lon) in zip(grid.cells, grid.points):
        assert (lat, lon) == center((i, j))
        assert cell_of((lat, lon)) == (i, j)  # a checkpoint snapped here would reuse this forecast


def test_reserved_checkpoint_cells_narrow_the_corridor_before_coarsening_it():
    route = north_line(200)
    free = corridor([route])
    assert (free.cell_deg, free.radius_mi) == (0.1, 15.0)
    # Checkpoint cells elsewhere use up most of the budget: same spacing, narrower corridor.
    reserved = {(9000 + i, 0) for i in range(LOCATION_BUDGET - len(free.cells) + 40)}
    squeezed = corridor([route], reserved=reserved)
    assert squeezed.cell_deg == 0.1
    assert squeezed.radius_mi < 15.0
    assert len(set(squeezed.cells) | reserved) <= LOCATION_BUDGET


def test_checkpoints_alone_over_budget_still_get_a_small_heatmap():
    reserved = {(9000 + i, 0) for i in range(LOCATION_BUDGET + 50)}
    grid = corridor([north_line(1500)], reserved=reserved)
    assert 0 < len(grid.cells) <= MIN_POINTS


def test_overlapping_routes_share_points():
    one = corridor([north_line(100)])
    same_twice = corridor([north_line(100), north_line(100)])
    assert one.points == same_twice.points


def payload(conditions, weight_lb=35_000, hours_present=HOURS + 1):
    grid = Corridor(cells=[(350, -1000), (351, -1000)], cell_deg=0.1, radius_mi=15.0)
    forecast = {START + timedelta(hours=h): conditions for h in range(hours_present)}
    return build(grid, [forecast, forecast], START, weight_lb)


def test_payload_shape_is_point_major_with_49_hours():
    data = payload(HourlyWeather(10.0, 0.0, 0.0))
    assert data["start"] == "2026-10-13T13:00:00+00:00"
    assert data["hours"] == 48
    assert data["points"] == [[-100.0, 35.0], [-100.0, 35.1]]
    for key in ("risk", "wind_mph", "rain_in_hr", "snow_in_hr"):
        assert len(data[key]) == 2
        assert all(len(row) == 49 for row in data[key])


def test_heatmap_risk_uses_the_trip_load():
    windy = HourlyWeather(47.0, 0.0, 0.0)
    assert payload(windy, weight_lb=35_000)["risk"][0][0] == 4  # No Travel above 30,000 lb
    assert payload(windy, weight_lb=20_000)["risk"][0][0] == 3  # Severe otherwise


def test_hours_without_forecast_are_null():
    data = payload(HourlyWeather(10.0, 0.05, 0.0), hours_present=10)
    assert data["risk"][0][9] == 0
    assert data["risk"][0][10] is None
    assert data["wind_mph"][0][48] is None


def test_values_are_rounded_for_a_compact_payload():
    data = payload(HourlyWeather(12.345, 0.12345, 1.98765))
    assert (data["wind_mph"][0][0], data["rain_in_hr"][0][0], data["snow_in_hr"][0][0]) == (12.3, 0.12, 1.99)


def test_side_offsets_land_15_miles_from_the_route():
    # Guards the destination_point maths: the widest points are ~15 mi from the line.
    grid = corridor([north_line(10)], max_points=10_000)
    farthest = max(haversine_mi((lat, -100.0), (lat, lon)) for lat, lon in grid.points)
    assert farthest == pytest.approx(15, abs=grid.cell_deg * 69)
