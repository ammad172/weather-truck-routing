from datetime import UTC, datetime, timedelta

import httpx
import pytest

from routing.providers.base import ProviderError
from routing.weather import HourlyWeather, OpenMeteoClient, parse_forecasts

from .conftest import load_fixture

START = datetime(2026, 10, 13, 13, tzinfo=UTC)


def test_parse_recorded_multi_location_response():
    forecasts = parse_forecasts(load_fixture("open_meteo_3_points.json"))
    assert len(forecasts) == 3
    first = forecasts[0]
    assert min(first) == START
    assert max(first) == START + timedelta(hours=5)
    assert first[START] == HourlyWeather(wind_mph=5.1, rain_in_hr=0.0, snow_in_hr=0.0)


def test_single_location_response_is_an_object_not_a_list():
    payload = load_fixture("open_meteo_3_points.json")[0]
    assert len(parse_forecasts(payload)) == 1


def test_null_values_are_kept_as_missing():
    payload = {"hourly": {"time": ["2026-10-13T13:00"], "wind_speed_10m": [None], "rain": [0.0], "snowfall": [0.0]}}
    hour = parse_forecasts(payload)[0][START]
    assert hour.wind_mph is None
    assert not hour.complete


def fake_open_meteo(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        lats = request.url.params["latitude"].split(",")
        location = {"hourly": {"time": ["2026-10-13T13:00"], "wind_speed_10m": [12.0], "rain": [0.1], "snowfall": [0.0]}}
        return httpx.Response(200, json=[location] * len(lats) if len(lats) > 1 else location)

    return OpenMeteoClient(http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_points_are_batched_and_order_is_kept():
    seen = []
    points = [(30 + i * 0.01, -97.0) for i in range(250)]
    forecasts = fake_open_meteo(seen).hourly(points, START, START)
    assert len(seen) == 3  # 100 + 100 + 50
    assert sorted(len(r.url.params["latitude"].split(",")) for r in seen) == [50, 100, 100]
    assert len(forecasts) == 250
    assert forecasts[0][START].wind_mph == 12.0


def test_request_asks_for_rule_units_in_utc():
    seen = []
    fake_open_meteo(seen).hourly([(32.78, -96.8)], START, START + timedelta(hours=3))
    params = seen[0].url.params
    assert params["wind_speed_unit"] == "mph"
    assert params["precipitation_unit"] == "inch"
    assert params["timezone"] == "UTC"
    assert params["start_hour"] == "2026-10-13T13:00"
    assert params["end_hour"] == "2026-10-13T16:00"


def test_repeat_requests_are_cached():
    seen = []
    client = fake_open_meteo(seen)
    client.hourly([(32.78, -96.8)], START, START)
    client.hourly([(32.78, -96.8)], START, START)
    assert len(seen) == 1


def test_http_error_becomes_provider_error():
    client = OpenMeteoClient(
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"reason": "Bad hour"})))
    )
    with pytest.raises(ProviderError, match="Bad hour"):
        client.hourly([(32.78, -96.8)], START, START)


def test_no_points_makes_no_request():
    seen = []
    assert fake_open_meteo(seen).hourly([], START, START) == []
    assert seen == []
