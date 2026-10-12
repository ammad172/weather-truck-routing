from datetime import UTC, datetime, timedelta, timezone

import pytest

from routing.eta import TimeProfile, checkpoint_etas, nearest_forecast_hour

DEPART = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)


def test_uniform_profile_is_constant_speed():
    profile = TimeProfile.uniform(total_miles=120, total_seconds=7200)  # 60 mph
    assert profile.elapsed_at(30) == pytest.approx(1800)


def test_span_profile_uses_per_span_speeds():
    # 60 mi of interstate at 60 mph, then 30 mi of mountain road at 30 mph.
    profile = TimeProfile.from_spans([60, 30], [3600, 3600])
    assert profile.elapsed_at(60) == pytest.approx(3600)
    assert profile.elapsed_at(75) == pytest.approx(5400)  # halfway through the slow span
    assert profile.elapsed_at(90) == pytest.approx(7200)


def test_elapsed_is_clamped_to_route_ends():
    profile = TimeProfile.uniform(100, 6000)
    assert profile.elapsed_at(-5) == 0
    assert profile.elapsed_at(500) == 6000


def test_zero_length_span_does_not_divide_by_zero():
    profile = TimeProfile.from_spans([10, 0, 10], [600, 120, 600])  # e.g. a stop with no distance
    assert profile.elapsed_at(10) == pytest.approx(720)  # takes the end of the stop
    assert profile.elapsed_at(15) == pytest.approx(1020)


def test_checkpoint_etas_increase_and_are_utc():
    profile = TimeProfile.from_spans([25, 25, 25, 25], [1500, 1800, 1200, 2400])
    etas = checkpoint_etas([0, 25, 50, 75, 100], profile, DEPART)
    assert etas[0] == DEPART
    assert etas[-1] == DEPART + timedelta(seconds=6900)
    assert all(b > a for a, b in zip(etas, etas[1:]))
    assert all(t.tzinfo == UTC for t in etas)


def test_departure_in_another_timezone_is_converted():
    central = timezone(timedelta(hours=-5))
    etas = checkpoint_etas([0], TimeProfile.uniform(10, 600), datetime(2026, 10, 13, 3, 0, tzinfo=central))
    assert etas[0] == DEPART


def test_naive_departure_is_rejected():
    with pytest.raises(ValueError):
        checkpoint_etas([0], TimeProfile.uniform(10, 600), datetime(2026, 10, 13, 8, 0))


@pytest.mark.parametrize(
    ("minute", "second", "expected_hour"),
    [(0, 0, 8), (29, 59, 8), (30, 0, 9), (59, 59, 9)],
)
def test_nearest_forecast_hour(minute, second, expected_hour):
    t = DEPART.replace(minute=minute, second=second)
    assert nearest_forecast_hour(t) == DEPART.replace(hour=expected_hour)


def test_nearest_forecast_hour_rolls_over_midnight():
    assert nearest_forecast_hour(datetime(2026, 10, 13, 23, 45, tzinfo=UTC)) == datetime(2026, 10, 14, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("miles", "seconds"),
    [((0.0,), (0.0,)), ((0.0, 10.0), (0.0,)), ((0.0, 10.0, 5.0), (0.0, 1.0, 2.0)), ((0.0, 10.0), (5.0, 1.0))],
)
def test_invalid_profiles_are_rejected(miles, seconds):
    with pytest.raises(ValueError):
        TimeProfile(miles=miles, seconds=seconds)
