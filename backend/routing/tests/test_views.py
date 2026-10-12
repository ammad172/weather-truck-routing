from datetime import timedelta

import pytest
from django.utils import timezone

from routing import services
from routing.providers.base import ProviderError, RateLimitedError

from .fakes import FakeRouting, FakeWeather, north, straight_route

DALLAS = (32.77823, -96.7951)


@pytest.fixture
def fake_providers(monkeypatch):
    routing = FakeRouting([straight_route(DALLAS, north(DALLAS, 120), hours=2.0)])
    monkeypatch.setattr(services, "routing_provider", lambda: routing)
    monkeypatch.setattr(services, "weather_provider", lambda: FakeWeather())
    return routing


def body(**overrides):
    data = {
        "origin": "Dallas, TX",
        "destination": {"lat": north(DALLAS, 120)[0], "lon": DALLAS[1], "label": "North of Dallas"},
        "departure": (timezone.now() + timedelta(days=1)).isoformat(),
        "weight_lb": 42000,
        "interval_mi": 25,
    }
    return {**data, **overrides}


def test_plan_geocodes_names_and_accepts_coordinates(client, fake_providers):
    response = client.post("/api/plan", body(), content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["request"]["origin"]["label"] == "Dallas, TX, United States"
    assert data["request"]["destination"]["label"] == "North of Dallas"
    assert data["recommendation"]["route_id"] == "A"
    assert len(data["routes"][0]["checkpoints"]) == 6  # 0, 25, 50, 75, 100, 120


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"interval_mi": 30}, "interval_mi"),
        ({"weight_lb": -1}, "weight_lb"),
        ({"weight_lb": 80_001}, "weight_lb"),
        ({"departure": "2020-01-01T00:00:00Z"}, "departure"),
        ({"departure": "2099-01-01T00:00:00Z"}, "departure"),
        ({"origin": {"lat": 95, "lon": 0}}, "origin"),
        ({"origin": 42}, "origin"),
        ({"destination": ""}, "destination"),
    ],
)
def test_plan_validation_errors(client, fake_providers, overrides, field):
    response = client.post("/api/plan", body(**overrides), content_type="application/json")
    assert response.status_code == 400
    assert field in response.json()


def test_invalid_location_message_shows_the_expected_format(client, fake_providers):
    response = client.post("/api/plan", body(origin=42), content_type="application/json")
    assert response.json()["origin"] == ['Enter a place name, or an object like {"lat": 32.78, "lon": -96.80}.']


def test_plan_reports_unknown_place(client, fake_providers):
    response = client.post("/api/plan", body(origin="Atlantis"), content_type="application/json")
    assert response.status_code == 400
    assert "Couldn't find" in response.json()["origin"][0]


def test_plan_reports_no_route(client, fake_providers):
    fake_providers.routes = []
    response = client.post("/api/plan", body(), content_type="application/json")
    assert response.status_code == 422


def test_provider_failure_is_a_502_with_a_readable_message(client, monkeypatch):
    def broken():
        raise ProviderError("HERE routing rejected the API key.")

    monkeypatch.setattr(services, "routing_provider", broken)
    response = client.post("/api/plan", body(), content_type="application/json")
    assert response.status_code == 502
    assert response.json() == {"detail": "HERE routing rejected the API key."}


def test_rate_limit_after_retry_is_a_503_with_retry_after(client, monkeypatch, fake_providers):
    class BusyWeather:
        def hourly(self, points, start, end):
            raise RateLimitedError("The free weather service is busy. Please wait about a minute and try again.")

    monkeypatch.setattr(services, "weather_provider", lambda: BusyWeather())
    response = client.post("/api/plan", body(), content_type="application/json")
    assert response.status_code == 503
    assert response["Retry-After"] == "60"
    assert "wait about a minute" in response.json()["detail"]


def test_geocode(client, fake_providers):
    response = client.get("/api/geocode", {"q": "Dallas"})
    assert response.status_code == 200
    assert response.json()["results"][0]["label"] == "Dallas, TX, United States"


def test_geocode_needs_a_query(client, fake_providers):
    assert client.get("/api/geocode", {"q": "D"}).status_code == 400
