import re
from datetime import UTC, datetime

import httpx
import pytest

from routing.providers.base import ProviderError
from routing.providers.here import HereClient, parse_geocode, parse_routes

from .conftest import load_fixture

FAKE_KEY = "not-a-real-key-123"


def test_parse_recorded_truck_routes():
    routes = parse_routes(load_fixture("here_routes_dal_okc.json"))
    assert len(routes) == 2  # HERE returned only one alternative for this trip
    for route in routes:
        assert len(route.coords) > 1000
        assert route.span_offsets[0] == 0
        assert route.span_offsets == sorted(route.span_offsets)
        assert max(route.span_offsets) < len(route.coords)
        assert sum(route.span_durations_s) == pytest.approx(route.duration_s)
    lat, lon = routes[0].coords[0]
    assert (lat, lon) == pytest.approx((32.778, -96.795), abs=0.01)  # starts in Dallas
    assert routes[0].distance_m / 1609.344 == pytest.approx(205.5, abs=1)


def test_multi_section_routes_are_joined_without_repeating_the_shared_point():
    payload = load_fixture("here_routes_dal_okc.json")
    section = payload["routes"][0]["sections"][0]
    single = parse_routes({"routes": [{"sections": [section]}]})[0]
    double = parse_routes({"routes": [{"sections": [section, section]}]})[0]
    assert len(double.coords) == 2 * len(single.coords) - 1
    assert double.span_offsets[len(single.span_offsets)] == len(single.coords) - 1
    assert double.duration_s == 2 * single.duration_s


def test_parse_recorded_geocode():
    places = parse_geocode(load_fixture("here_geocode_denver.json"))
    assert places[0].label == "Denver, CO, United States"
    assert (places[0].lat, places[0].lon) == pytest.approx((39.74, -104.99), abs=0.01)


def client_returning(status: int, body: dict | None = None, seen: list | None = None) -> HereClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body or {})

    return HereClient(FAKE_KEY, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_truck_request_parameters():
    seen = []
    client = client_returning(200, {"routes": []}, seen)
    client.truck_routes((32.7, -96.8), (35.5, -97.5), datetime(2026, 10, 13, 13, tzinfo=UTC), 34927, via=(34.0, -97.0))
    params = seen[0].url.params
    assert params["transportMode"] == "truck"
    assert params["vehicle[grossWeight]"] == "34927"
    assert params["departureTime"] == "2026-10-13T13:00:00Z"
    assert params["via"] == "34.000000,-97.000000!passThrough=true"
    assert "speedLimit" in params["spans"]


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "rejected the API key"), (403, "rejected the API key"), (429, "rate limit"), (400, "failed (400): Bad thing")],
)
def test_errors_are_readable_and_never_contain_the_key(status, message):
    client = client_returning(status, {"title": "Bad thing"})
    with pytest.raises(ProviderError, match=re.escape(message)) as err:
        client.geocode("Dallas")
    assert FAKE_KEY not in str(err.value)


def test_network_errors_never_contain_the_key():
    def boom(request):
        raise httpx.ConnectError(f"failed to connect to {request.url}")

    client = HereClient(FAKE_KEY, http=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(ProviderError) as err:
        client.geocode("Dallas")
    assert FAKE_KEY not in str(err.value)


def test_responses_are_cached():
    seen = []
    client = client_returning(200, load_fixture("here_geocode_denver.json"), seen)
    client.geocode("Denver")
    client.geocode("Denver")
    assert len(seen) == 1


def test_missing_key_is_reported():
    with pytest.raises(ProviderError, match="missing its HERE API key"):
        HereClient("")
