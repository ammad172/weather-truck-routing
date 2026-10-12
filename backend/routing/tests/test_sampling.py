import pytest

from routing.sampling import cumulative_miles, haversine_mi, point_at_mile, sample_checkpoints

# One degree of latitude is ~69.09 miles, so a north-south line is easy to reason about.
MI_PER_DEG_LAT = haversine_mi((0.0, 0.0), (1.0, 0.0))


def north_line(miles: float, points: int = 50) -> list[tuple[float, float]]:
    """A straight polyline due north from (35, -100), ``miles`` long."""
    end = miles / MI_PER_DEG_LAT
    return [(35.0 + end * i / (points - 1), -100.0) for i in range(points)]


def test_haversine_known_distance():
    # Dallas (32.7767, -96.7970) to Denver (39.7392, -104.9903) is ~663 mi great-circle.
    assert haversine_mi((32.7767, -96.7970), (39.7392, -104.9903)) == pytest.approx(663, abs=3)


@pytest.mark.parametrize(
    ("interval", "expected_miles"),
    [
        (10, [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]),
        (25, [0, 25, 50, 75, 100, 120]),
        (50, [0, 50, 100, 120]),
    ],
)
def test_checkpoints_every_interval_plus_destination(interval, expected_miles):
    checkpoints = sample_checkpoints(north_line(120), interval)
    assert [c.mile for c in checkpoints] == pytest.approx(expected_miles, abs=1e-6)


def test_no_duplicate_destination_when_route_is_an_exact_multiple():
    checkpoints = sample_checkpoints(north_line(100), 25)
    assert [c.mile for c in checkpoints] == pytest.approx([0, 25, 50, 75, 100], abs=1e-6)


@pytest.mark.parametrize("interval", [10, 25, 50])
def test_segment_miles_sum_to_route_length(interval):
    coords = north_line(137.3)
    checkpoints = sample_checkpoints(coords, interval)
    assert sum(c.segment_miles for c in checkpoints) == pytest.approx(cumulative_miles(coords)[-1])


def test_segment_miles_split_halfway_between_checkpoints():
    checkpoints = sample_checkpoints(north_line(60), 25)  # marks 0, 25, 50, 60
    assert [c.segment_miles for c in checkpoints] == pytest.approx([12.5, 25, 17.5, 5], abs=1e-6)


def test_checkpoint_positions_follow_the_line():
    checkpoints = sample_checkpoints(north_line(100), 50)
    assert checkpoints[0].lat == pytest.approx(35.0)
    assert checkpoints[1].lat == pytest.approx(35.0 + 50 / MI_PER_DEG_LAT, abs=1e-6)
    assert all(c.lon == pytest.approx(-100.0) for c in checkpoints)


def test_route_shorter_than_interval_gets_origin_and_destination():
    checkpoints = sample_checkpoints(north_line(7), 50)
    assert [c.mile for c in checkpoints] == pytest.approx([0, 7], abs=1e-6)
    assert [c.segment_miles for c in checkpoints] == pytest.approx([3.5, 3.5], abs=1e-6)


def test_point_at_mile_handles_repeated_coordinates():
    coords = [(35.0, -100.0), (35.0, -100.0), (36.0, -100.0)]
    lat, lon = point_at_mile(coords, cumulative_miles(coords), MI_PER_DEG_LAT / 2)
    assert (lat, lon) == pytest.approx((35.5, -100.0))


@pytest.mark.parametrize(("coords", "interval"), [([(35.0, -100.0)], 10), (north_line(20), 0)])
def test_invalid_input_raises(coords, interval):
    with pytest.raises(ValueError):
        sample_checkpoints(coords, interval)
