import json
from datetime import UTC, datetime

import httpx
import pytest
from django.test import override_settings

from routing import clock
from routing.http_fixtures import MissingFixture, RecordTransport, ReplayTransport, transport
from routing.weather import OpenMeteoClient

KEY = "secret-here-key-123"
ROUTES = "https://router.hereapi.com/v8/routes"
FORECAST = "https://api.open-meteo.com/v1/forecast"
WINDOW = {"hourly": "wind_speed_10m,rain,snowfall", "start_hour": "2026-10-12T00:00", "end_hour": "2026-10-14T23:00"}


def hourly(wind: float) -> dict:
    return {"hourly": {"time": ["2026-10-12T00:00"], "wind_speed_10m": [wind], "rain": [0.0], "snowfall": [0.0]}}


def fake_live(request: httpx.Request) -> httpx.Response:
    """Stands in for the real APIs: HERE echoes its params, Open-Meteo returns wind = latitude."""
    if request.url.host == "api.open-meteo.com":
        lats = request.url.params["latitude"].split(",")
        body = [hourly(float(lat)) for lat in lats]
        return httpx.Response(200, json=body if len(body) > 1 else body[0])
    if request.url.params.get("fail"):
        return httpx.Response(429)
    return httpx.Response(200, json={"routes": [{"origin": request.url.params["origin"]}]})


def recorder(tmp_path) -> httpx.Client:
    return httpx.Client(transport=RecordTransport(tmp_path, secret=KEY, live=httpx.MockTransport(fake_live)))


def replayer(tmp_path) -> httpx.Client:
    return httpx.Client(transport=ReplayTransport(tmp_path))


def test_here_round_trip_without_the_key(tmp_path):
    params = {"origin": "32.7,-96.8", "transportMode": "truck"}
    live = recorder(tmp_path).get(ROUTES, params={**params, "apiKey": KEY}).json()

    files = list((tmp_path / "here").glob("*.json"))
    assert len(files) == 1
    assert KEY not in files[0].read_text(encoding="utf-8")
    assert json.loads(files[0].read_text(encoding="utf-8"))["params"] == params

    # Replay matches regardless of the key (or its absence) and of parameter order.
    replayed = replayer(tmp_path).get(ROUTES, params={"transportMode": "truck", "origin": "32.7,-96.8", "apiKey": "other"})
    assert replayed.json() == live


def test_records_compressed_responses(tmp_path):
    # The real APIs gzip their responses; the recorder must hand back usable JSON, not re-gzip it.
    def gzipped(request):
        import gzip

        return httpx.Response(200, headers={"content-encoding": "gzip"}, content=gzip.compress(b'{"items": [1]}'))

    client = httpx.Client(transport=RecordTransport(tmp_path, live=httpx.MockTransport(gzipped)))
    assert client.get(ROUTES, params={"origin": "1,2"}).json() == {"items": [1]}
    assert replayer(tmp_path).get(ROUTES, params={"origin": "1,2"}).json() == {"items": [1]}


def test_failed_responses_are_not_recorded(tmp_path):
    response = recorder(tmp_path).get(ROUTES, params={"origin": "1,2", "fail": "1", "apiKey": KEY})
    assert response.status_code == 429
    assert not (tmp_path / "here").exists()


def test_refuses_to_record_the_key(tmp_path):
    client = httpx.Client(
        transport=RecordTransport(tmp_path, secret=KEY, live=httpx.MockTransport(lambda r: httpx.Response(200, json={"echo": KEY})))
    )
    with pytest.raises(RuntimeError, match="contains the API key"):
        client.get(ROUTES, params={"origin": "1,2", "apiKey": KEY})


def test_open_meteo_is_stored_per_location(tmp_path):
    recorder(tmp_path).get(FORECAST, params={**WINDOW, "latitude": "32.7000,33.0000,35.0000", "longitude": "-96.8000,-97.0000,-101.8000"})
    recorder(tmp_path).get(FORECAST, params={**WINDOW, "latitude": "39.7000", "longitude": "-105.0000"})

    # A different batch, in a different order, across both recordings.
    body = replayer(tmp_path).get(FORECAST, params={**WINDOW, "latitude": "39.7000,32.7000", "longitude": "-105.0000,-96.8000"}).json()
    assert [loc["hourly"]["wind_speed_10m"][0] for loc in body] == [39.7, 32.7]

    # A single location comes back as one object, like Open-Meteo does.
    single = replayer(tmp_path).get(FORECAST, params={**WINDOW, "latitude": "35.0000", "longitude": "-101.8000"}).json()
    assert single["hourly"]["wind_speed_10m"] == [35.0]


def test_replay_fails_loudly_without_a_recording(tmp_path):
    recorder(tmp_path).get(FORECAST, params={**WINDOW, "latitude": "32.7000", "longitude": "-96.8000"})
    client = replayer(tmp_path)
    with pytest.raises(MissingFixture, match="1 of 2 locations"):
        client.get(FORECAST, params={**WINDOW, "latitude": "32.7000,40.0000", "longitude": "-96.8000,-90.0000"})
    with pytest.raises(MissingFixture):  # same location, different units
        client.get(FORECAST, params={**WINDOW, "latitude": "32.7000", "longitude": "-96.8000", "wind_speed_unit": "kmh"})
    with pytest.raises(MissingFixture, match="this request"):
        client.get(ROUTES, params={"origin": "1,2"})


def test_weather_client_reads_replayed_forecasts(tmp_path):
    points = [(32.7, -96.8), (33.0, -97.0)]
    start = datetime(2026, 10, 12, 0, tzinfo=UTC)
    live = OpenMeteoClient(http=recorder(tmp_path)).hourly(points, start, start)
    from django.core.cache import cache

    cache.clear()
    replayed = OpenMeteoClient(http=replayer(tmp_path)).hourly(points, start, start)
    assert replayed == live
    assert replayed[1][start].wind_mph == 33.0


def test_transport_rejects_unknown_modes(tmp_path):
    with pytest.raises(ValueError, match="record' or 'replay"):
        transport("live", tmp_path)


def test_clock_can_be_frozen():
    frozen = datetime(2026, 10, 12, 15, 10, tzinfo=UTC)
    with override_settings(FROZEN_NOW=frozen):
        assert clock.now() == frozen
    assert clock.now() != frozen
