from datetime import UTC, datetime, timedelta

import httpx
import pytest
from django.utils import timezone

from routing import weather
from routing.providers.base import ProviderError, RateLimitedError
from routing.weather import HourlyWeather, OpenMeteoClient, fetch_window, forecast_horizon, parse_forecasts

from .conftest import load_fixture

RECORDED_START = datetime(2026, 10, 13, 13, tzinfo=UTC)  # first hour in the recorded fixture
TOMORROW_1PM = (timezone.now() + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)


def test_parse_recorded_multi_location_response():
    forecasts = parse_forecasts(load_fixture("open_meteo_3_points.json"))
    assert len(forecasts) == 3
    first = forecasts[0]
    assert min(first) == RECORDED_START
    assert max(first) == RECORDED_START + timedelta(hours=5)
    assert first[RECORDED_START] == HourlyWeather(wind_mph=5.1, rain_in_hr=0.0, snow_in_hr=0.0)


def test_single_location_response_is_an_object_not_a_list():
    payload = load_fixture("open_meteo_3_points.json")[0]
    assert len(parse_forecasts(payload)) == 1


def test_null_values_are_kept_as_missing():
    payload = {"hourly": {"time": ["2026-10-13T13:00"], "wind_speed_10m": [None], "rain": [0.0], "snowfall": [0.0]}}
    hour = parse_forecasts(payload)[0][RECORDED_START]
    assert hour.wind_mph is None
    assert not hour.complete


def test_horizon_is_23h_utc_fifteen_days_after_today():
    now = datetime(2026, 10, 12, 13, 10, tzinfo=UTC)
    assert forecast_horizon(now) == datetime(2026, 10, 27, 23, tzinfo=UTC)


def test_fetch_window_is_whole_days_and_at_least_three():
    start = datetime(2026, 10, 13, 13, tzinfo=UTC)
    assert fetch_window(start, start + timedelta(hours=5)) == (
        datetime(2026, 10, 13, 0, tzinfo=UTC),
        datetime(2026, 10, 15, 23, tzinfo=UTC),
    )
    # A longer span extends to the end of its last day.
    assert fetch_window(start, start + timedelta(days=4)) == (
        datetime(2026, 10, 13, 0, tzinfo=UTC),
        datetime(2026, 10, 17, 23, tzinfo=UTC),
    )


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Record backoff delays instead of sleeping."""
    delays: list[float] = []
    monkeypatch.setattr(weather, "sleep", delays.append)
    return delays


def ok_response(request: httpx.Request) -> httpx.Response:
    lats = request.url.params["latitude"].split(",")
    hour = request.url.params["start_hour"]
    location = {"hourly": {"time": [hour], "wind_speed_10m": [12.0], "rain": [0.1], "snowfall": [0.0]}}
    return httpx.Response(200, json=[location] * len(lats) if len(lats) > 1 else location)


def fake_open_meteo(seen: list, status: int = 200, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, json=body or {})
        return ok_response(request)

    return OpenMeteoClient(http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_points_are_batched_and_order_is_kept():
    seen = []
    points = [(30 + i * 0.01, -97.0) for i in range(250)]
    forecasts = fake_open_meteo(seen).hourly(points, TOMORROW_1PM, TOMORROW_1PM)
    assert len(seen) == 3  # 100 + 100 + 50
    assert sorted(len(r.url.params["latitude"].split(",")) for r in seen) == [50, 100, 100]
    assert len(forecasts) == 250
    window_start = TOMORROW_1PM.replace(hour=0)
    assert forecasts[0][window_start].wind_mph == 12.0


def test_request_asks_for_rule_units_in_utc_over_whole_days():
    seen = []
    fake_open_meteo(seen).hourly([(32.78, -96.8)], TOMORROW_1PM, TOMORROW_1PM + timedelta(hours=3))
    params = seen[0].url.params
    assert params["wind_speed_unit"] == "mph"
    assert params["precipitation_unit"] == "inch"
    assert params["timezone"] == "UTC"
    assert params["start_hour"] == f"{TOMORROW_1PM:%Y-%m-%d}T00:00"
    assert params["end_hour"] == f"{TOMORROW_1PM + timedelta(days=2):%Y-%m-%d}T23:00"
    assert seen[0].url.host == "api.open-meteo.com"


def test_cached_locations_are_not_fetched_again():
    seen = []
    client = fake_open_meteo(seen)
    client.hourly([(32.78, -96.8), (33.0, -97.0)], TOMORROW_1PM, TOMORROW_1PM)
    # A later departure the same day reuses the cache; only the new location is fetched.
    client.hourly([(32.78, -96.8), (33.0, -97.0), (34.0, -98.0)], TOMORROW_1PM + timedelta(hours=4), TOMORROW_1PM + timedelta(hours=6))
    assert len(seen) == 2
    assert seen[1].url.params["latitude"] == "34.0000"


def test_cached_forecasts_round_trip_exactly():
    seen = []
    client = fake_open_meteo(seen)
    fresh = client.hourly([(32.78, -96.8)], TOMORROW_1PM, TOMORROW_1PM)
    cached = client.hourly([(32.78, -96.8)], TOMORROW_1PM, TOMORROW_1PM)
    assert len(seen) == 1
    assert cached == fresh


def test_successful_batches_are_cached_even_if_another_batch_fails():
    calls = []

    def handler(request):
        calls.append(request)
        lats = request.url.params["latitude"].split(",")
        if lats[0].startswith("40"):  # the second batch gets rate limited
            return httpx.Response(429, json={"reason": "Minutely API request limit exceeded"})
        hour = request.url.params["start_hour"]
        loc = {"hourly": {"time": [hour], "wind_speed_10m": [5.0], "rain": [0.0], "snowfall": [0.0]}}
        return httpx.Response(200, json=[loc] * len(lats))

    client = OpenMeteoClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    first_batch = [(30 + i * 0.01, -97.0) for i in range(100)]
    second_batch = [(40 + i * 0.01, -97.0) for i in range(100)]
    with pytest.raises(RateLimitedError):
        client.hourly(first_batch + second_batch, TOMORROW_1PM, TOMORROW_1PM)
    assert len(calls) == 3  # both batches, then one retry of the rate-limited one
    calls.clear()
    with pytest.raises(RateLimitedError):
        client.hourly(first_batch + second_batch, TOMORROW_1PM, TOMORROW_1PM)
    assert len(calls) == 2  # the first batch is cached; only the second is tried (and retried)
    assert all(c.url.params["latitude"].startswith("40") for c in calls)


def test_one_backoff_and_retry_recovers_from_a_429(no_real_sleep):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={}) if len(calls) == 1 else ok_response(request)

    client = OpenMeteoClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    forecasts = client.hourly([(32.78, -96.8)], TOMORROW_1PM, TOMORROW_1PM)
    assert len(calls) == 2
    assert no_real_sleep == [weather.RETRY_DELAY_S]
    assert forecasts[0][TOMORROW_1PM.replace(hour=0)].wind_mph == 12.0


def test_backoff_honours_retry_after_up_to_a_cap(no_real_sleep):
    for header, expected in (("2", 2.0), ("120", weather.RETRY_MAX_DELAY_S)):
        no_real_sleep.clear()
        responses = iter([httpx.Response(429, headers={"Retry-After": header}, json={})])
        client = OpenMeteoClient(
            http=httpx.Client(transport=httpx.MockTransport(lambda r: next(responses, None) or ok_response(r)))
        )
        client.hourly([(32.78, -96.8 + float(header))], TOMORROW_1PM, TOMORROW_1PM)
        assert no_real_sleep == [expected]


def test_still_rate_limited_after_the_retry_gives_a_clear_message(no_real_sleep):
    seen = []
    with pytest.raises(RateLimitedError, match="busy .* wait about a minute"):
        fake_open_meteo(seen, status=429).hourly([(32.78, -96.8)], TOMORROW_1PM, TOMORROW_1PM)
    assert len(seen) == 2  # exactly one retry
    assert len(no_real_sleep) == 1


def test_other_errors_are_not_retried(no_real_sleep):
    seen = []
    with pytest.raises(ProviderError):
        fake_open_meteo(seen, status=500).hourly([(32.78, -96.8)], TOMORROW_1PM, TOMORROW_1PM)
    assert len(seen) == 1
    assert no_real_sleep == []


def test_duplicate_points_are_fetched_once():
    seen = []
    forecasts = fake_open_meteo(seen).hourly([(32.78, -96.8), (32.78, -96.8)], TOMORROW_1PM, TOMORROW_1PM)
    assert seen[0].url.params["latitude"] == "32.7800"
    assert len(forecasts) == 2


def test_window_is_clamped_to_the_forecast_horizon(monkeypatch):
    now = datetime(2026, 10, 12, 13, tzinfo=UTC)
    monkeypatch.setattr(weather.clock, "now", lambda: now)
    seen = []
    start = datetime(2026, 10, 26, 20, tzinfo=UTC)
    fake_open_meteo(seen).hourly([(32.78, -96.8)], start, start + timedelta(hours=48))
    assert seen[0].url.params["end_hour"] == "2026-10-27T23:00"


def test_window_entirely_past_the_horizon_makes_no_request(monkeypatch):
    monkeypatch.setattr(weather.clock, "now", lambda: datetime(2026, 10, 12, 13, tzinfo=UTC))
    seen = []
    start = datetime(2026, 10, 29, 0, tzinfo=UTC)
    assert fake_open_meteo(seen).hourly([(32.78, -96.8)], start, start) == [{}]
    assert seen == []


def test_http_error_becomes_provider_error():
    with pytest.raises(ProviderError, match="Bad hour"):
        fake_open_meteo([], status=400, body={"reason": "Bad hour"}).hourly([(32.78, -96.8)], TOMORROW_1PM, TOMORROW_1PM)


def test_no_points_makes_no_request():
    seen = []
    assert fake_open_meteo(seen).hourly([], TOMORROW_1PM, TOMORROW_1PM) == []
    assert seen == []


@pytest.mark.parametrize(
    ("reason", "message", "seconds_left"),
    [
        ("Hourly API request limit exceeded. Please try again in the next hour.", "hourly limit", 50 * 60),
        ("Daily API request limit exceeded. Please try again tomorrow.", "daily limit", 10 * 3600 + 50 * 60),
    ],
)
def test_hourly_and_daily_quotas_are_not_retried(no_real_sleep, monkeypatch, reason, message, seconds_left):
    monkeypatch.setattr(weather.clock, "now", lambda: datetime(2026, 10, 12, 13, 10, tzinfo=UTC))
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"reason": reason, "error": True})

    client = OpenMeteoClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(RateLimitedError, match=message) as raised:
        client.hourly([(32.78, -96.8)], TOMORROW_1PM, TOMORROW_1PM)
    assert len(calls) == 1  # no retry: it can't help
    assert no_real_sleep == []
    assert not raised.value.retryable
    assert raised.value.retry_after == seconds_left
