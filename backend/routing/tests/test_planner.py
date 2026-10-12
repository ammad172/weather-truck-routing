from datetime import UTC, datetime, timedelta

import pytest

from routing import heatmap
from routing.planner import NoRouteError, TripRequest, gross_weight_kg, plan_trip, time_profile
from routing.providers.base import Place
from routing.sampling import cumulative_miles
from routing.weather import HourlyWeather

from .fakes import FakeRouting, FakeWeather, RecordingWeather, north, straight_route

DEPART = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)
ORIGIN = (35.0, -100.0)
DEST = north(ORIGIN, 100)
WINDY = HourlyWeather(wind_mph=47.0, rain_in_hr=0.0, snow_in_hr=0.0)


def trip(weight_lb=35_000, interval=25, departure=DEPART) -> TripRequest:
    return TripRequest(
        origin=Place("Origin", *ORIGIN),
        destination=Place("Destination", *DEST),
        departure=departure,
        weight_lb=weight_lb,
        interval_mi=interval,
    )


def two_routes():
    """A: direct and fast but further east. B: shifted ~14 mi west and slower."""
    east = straight_route((ORIGIN[0], ORIGIN[1] + 0.25), (DEST[0], DEST[1] + 0.25), hours=2.0)
    west = straight_route((ORIGIN[0], ORIGIN[1] - 0.25), (DEST[0], DEST[1] - 0.25), hours=2.5)
    return FakeRouting([east, west])


def test_gross_weight_adds_typical_tare():
    assert gross_weight_kg(42_000) == round(77_000 * 0.45359237)


def test_time_profile_maps_spans_onto_our_miles():
    route = straight_route(ORIGIN, DEST, hours=2.0, points=101, spans=4)
    profile = time_profile(route, cumulative_miles(route.coords))
    assert profile.miles[0] == 0
    assert profile.miles[-1] == pytest.approx(100, rel=1e-3)
    assert profile.seconds[-1] == pytest.approx(7200)
    assert profile.elapsed_at(50) == pytest.approx(3600, rel=1e-3)


@pytest.mark.parametrize(("interval", "count"), [(10, 11), (25, 5), (50, 3)])
def test_checkpoint_count_follows_the_chosen_interval(interval, count):
    result = plan_trip(trip(interval=interval), two_routes(), FakeWeather())
    for route in result["routes"]:
        assert len(route["checkpoints"]) == count
        assert sum(c["segment_miles"] for c in route["checkpoints"]) == pytest.approx(100, rel=1e-3)


def test_etas_and_forecast_hours_follow_the_route():
    result = plan_trip(trip(interval=25), two_routes(), FakeWeather())
    checkpoints = result["routes"][0]["checkpoints"]  # 100 mi in 2 h
    etas = [datetime.fromisoformat(c["eta"]) for c in checkpoints]
    assert etas[0] == DEPART
    assert etas[2] == DEPART + timedelta(hours=1)  # mile 50
    assert etas[-1] == DEPART + timedelta(hours=2)
    assert [c["forecast_hour"][11:16] for c in checkpoints] == ["13:00", "14:00", "14:00", "15:00", "15:00"]


def test_checkpoints_and_heatmap_share_one_deduplicated_weather_fetch():
    weather = FakeWeather()
    result = plan_trip(trip(interval=25), two_routes(), weather)
    assert len(weather.requests) == 1
    points, start, end = weather.requests[0]
    checkpoint_cells = {tuple(c["weather_cell"]) for r in result["routes"] for c in r["checkpoints"]}
    heatmap_cells = {tuple(p) for p in result["heatmap"]["points"]}
    assert checkpoint_cells & heatmap_cells  # checkpoints reuse heatmap cells...
    assert points == len(checkpoint_cells | heatmap_cells)  # ...and each cell is fetched once
    assert start == DEPART
    assert end == DEPART + timedelta(hours=48)  # the slider's last frame


def test_checkpoint_weather_is_snapped_to_the_shared_grid():
    result = plan_trip(trip(interval=10), two_routes(), FakeWeather())
    for checkpoint in result["routes"][0]["checkpoints"]:
        lon, lat = checkpoint["weather_cell"]
        assert (lat, lon) == (round(lat, 1), round(lon, 1))  # a cell centre on the 0.1-degree lattice
        assert abs(lat - checkpoint["lat"]) <= 0.05 + 1e-9  # ...and the nearest one
        assert abs(lon - checkpoint["lon"]) <= 0.05 + 1e-9


def test_switching_interval_reuses_weather_cells():
    def requested(interval: int) -> set:
        weather = RecordingWeather()
        plan_trip(trip(interval=interval), two_routes(), weather)
        return weather.points

    at_25, at_50, at_10 = requested(25), requested(50), requested(10)
    assert at_50 <= at_25  # every 50-mile checkpoint is also a 25-mile one, in the same cell
    assert len(at_10 - at_25) < len(at_10) / 2  # most of the 10-mile plan is already cached


def test_heatmap_starts_at_the_departure_hour():
    result = plan_trip(trip(departure=DEPART + timedelta(minutes=40)), two_routes(), FakeWeather())
    heat = result["heatmap"]
    assert heat["start"] == "2026-10-13T13:00:00+00:00"
    assert 0 < len(heat["points"]) <= heatmap.MAX_POINTS
    assert all(len(row) == 49 and None not in row for row in heat["risk"])


def test_heatmap_grid_does_not_depend_on_the_checkpoint_interval():
    # Same grid for every interval, so switching interval reuses the cached heatmap weather.
    grids = {interval: plan_trip(trip(interval=interval), two_routes(), FakeWeather())["heatmap"]["points"] for interval in (10, 25, 50)}
    assert grids[10] == grids[25] == grids[50]


@pytest.mark.parametrize("interval", [10, 25, 50])
def test_weather_locations_per_plan_stay_within_budget(interval):
    three_long = FakeRouting(
        [straight_route((ORIGIN[0], ORIGIN[1] + dx), north((ORIGIN[0], ORIGIN[1] + dx), 900), hours=14.0) for dx in (-0.6, 0, 0.6)]
    )
    weather = FakeWeather()
    heat = plan_trip(trip(interval=interval), three_long, weather)["heatmap"]
    assert weather.requests[0][0] <= heatmap.LOCATION_BUDGET
    assert heat["cell_deg"] > 0.1  # a long corridor needs coarser heatmap spacing to fit


def test_heatmap_shows_the_storm_east_of_the_routes():
    weather = FakeWeather(stormy=WINDY, stormy_east_of=ORIGIN[1])
    heat = plan_trip(trip(weight_lb=35_000), two_routes(), weather)["heatmap"]
    for (lon, _), row in zip(heat["points"], heat["risk"]):
        assert row[0] == (4 if lon > ORIGIN[1] else 0)


def test_wind_with_heavy_load_makes_the_eastern_route_no_travel_and_ranks_it_last():
    weather = FakeWeather(stormy=WINDY, stormy_east_of=ORIGIN[1])  # 47 mph on route A only
    result = plan_trip(trip(weight_lb=35_000), two_routes(), weather)
    a, b = result["routes"]
    assert {c["level_label"] for c in a["checkpoints"]} == {"No Travel"}
    assert all(c["load_adjusted"] and c["factor"] == "wind" for c in a["checkpoints"])
    assert a["summary"]["no_travel_miles"] == pytest.approx(100, rel=1e-3)
    assert result["recommendation"]["route_id"] == "B"
    assert result["recommendation"]["ranking"] == ["B", "A"]
    assert result["recommendation"]["warning"] is None


def test_same_wind_with_a_light_load_is_only_severe():
    weather = FakeWeather(stormy=WINDY, stormy_east_of=ORIGIN[1])
    result = plan_trip(trip(weight_lb=20_000), two_routes(), weather)
    a = result["routes"][0]
    assert {c["level_label"] for c in a["checkpoints"]} == {"Severe"}
    assert not any(c["load_adjusted"] for c in a["checkpoints"])
    assert a["summary"]["severe_miles"] == pytest.approx(100, rel=1e-3)


def test_missing_forecast_counts_as_low_and_is_noted():
    weather = FakeWeather(calm=HourlyWeather(None, None, None))
    result = plan_trip(trip(), two_routes(), weather)
    checkpoint = result["routes"][0]["checkpoints"][0]
    assert checkpoint["weather"] == {"wind_mph": None, "rain_in_hr": None, "snow_in_hr": None}
    assert checkpoint["level_label"] == "Low"
    assert "no forecast data" in result["notes"][-1]


def test_response_shape():
    result = plan_trip(trip(), two_routes(), FakeWeather())
    assert result["request"]["gross_weight_lb"] == 70_000
    route = result["routes"][0]
    assert route["id"] == "A" and route["source"] == "provider"
    lon, lat = route["geometry"][0]
    assert (lat, lon) == pytest.approx((ORIGIN[0], ORIGIN[1] + 0.25))
    assert set(route["checkpoints"][0]) == {
        "mile", "segment_miles", "lat", "lon", "eta", "forecast_hour", "weather_cell", "weather",
        "level", "level_label", "factor", "load_adjusted",
    }


def test_no_route_raises():
    with pytest.raises(NoRouteError):
        plan_trip(trip(), FakeRouting([]), FakeWeather())
