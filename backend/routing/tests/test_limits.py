"""Abuse protection: per-IP throttles on /api/plan and /api/geocode, and the daily HERE cap."""

import logging
import threading
from datetime import UTC, datetime

import httpx
import pytest
from django.core.cache import caches
from django.utils import timezone

from routing import limits, services
from routing.alternatives import three_routes
from routing.limits import DAILY_LIMIT_MESSAGE, HereDailyLimitError, PlanDayThrottle, count_here_request
from routing.providers.here import HereClient

from .fakes import FakeRouting, FakeWeather, north, straight_route
from .test_views import DALLAS, body

NOW = datetime(2026, 10, 13, 23, 0, tzinfo=UTC)  # an hour before the cap resets
GEOCODE_HIT = {"items": [{"address": {"label": "Denver, CO, United States"}, "position": {"lat": 39.74, "lng": -104.99}}]}


@pytest.fixture
def fake_providers(monkeypatch):
    routing = FakeRouting([straight_route(DALLAS, north(DALLAS, 120), hours=2.0)])
    monkeypatch.setattr(services, "routing_provider", lambda: routing)
    monkeypatch.setattr(services, "weather_provider", lambda: FakeWeather())
    return routing


@pytest.fixture
def here(monkeypatch, settings):
    """The real HERE client on a mock transport that records every request that reaches "HERE"."""
    settings.HERE_DAILY_CAP = 3
    monkeypatch.setattr(timezone, "now", lambda: NOW)
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=GEOCODE_HIT)

    client = HereClient("not-a-real-key", http=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(services, "routing_provider", lambda: client)
    monkeypatch.setattr(services, "weather_provider", lambda: FakeWeather())
    return client, sent


def plan(client, **headers):
    return client.post("/api/plan", body(), content_type="application/json", **headers)


# Per-IP throttles


def test_plans_are_limited_to_10_a_minute_per_ip(client, fake_providers):
    for _ in range(10):
        assert plan(client).status_code == 200
    response = plan(client)
    assert response.status_code == 429
    assert 0 < int(response["Retry-After"]) <= 60
    assert response.json()["detail"].startswith("Too many requests from your connection. Try again in ")
    assert sum(call["via"] is None for call in fake_providers.calls) == 10  # the 11th never reached the providers


def test_plans_are_limited_per_day(client, fake_providers, monkeypatch):
    monkeypatch.setattr(PlanDayThrottle, "rate", "3/day", raising=False)  # the real rate is 100/day
    for _ in range(3):
        assert plan(client).status_code == 200
    response = plan(client)
    assert response.status_code == 429
    assert int(response["Retry-After"]) > 23 * 3600
    assert "hours" in response.json()["detail"]


def test_geocode_is_limited_to_60_a_minute_per_ip(client, fake_providers):
    for _ in range(60):
        assert client.get("/api/geocode", {"q": "Dallas"}).status_code == 200
    response = client.get("/api/geocode", {"q": "Dallas"})
    assert response.status_code == 429
    assert "Too many requests" in response.json()["detail"]


def test_each_client_ip_has_its_own_allowance(client, fake_providers, monkeypatch):
    monkeypatch.setattr(PlanDayThrottle, "rate", "1/day", raising=False)
    # Behind one proxy (Azure's ingress) the client is the last X-Forwarded-For entry.
    assert plan(client, HTTP_X_FORWARDED_FOR="203.0.113.1").status_code == 200
    assert plan(client, HTTP_X_FORWARDED_FOR="203.0.113.2").status_code == 200
    # Forging an earlier entry doesn't give a fresh allowance: the proxy appends the real one.
    assert plan(client, HTTP_X_FORWARDED_FOR="198.51.100.9, 203.0.113.1").status_code == 429


def test_health_is_not_throttled(client):
    assert all(client.get("/api/health").status_code == 200 for _ in range(30))


# The daily HERE cap


def test_the_cap_counts_requests_sent_to_here_not_cache_hits(here):
    client, sent = here
    for query in ("Denver", "Denver", "Boulder", "Boulder"):
        client.geocode(query)
    assert len(sent) == 2
    assert caches["limits"].get("here-requests:2026-10-13") == 2


def test_at_the_cap_here_is_not_called_but_cached_answers_still_work(here):
    client, sent = here
    for query in ("Denver", "Boulder", "Aurora"):
        client.geocode(query)
    with pytest.raises(HereDailyLimitError) as refused:
        client.geocode("Golden")
    assert len(sent) == 3  # the refused request was never sent
    assert refused.value.retry_after == 3600  # until midnight UTC
    assert client.geocode("Denver")[0].label == "Denver, CO, United States"  # from the cache


def test_the_cap_resets_each_utc_day(here, monkeypatch):
    client, sent = here
    caches["limits"].set("here-requests:2026-10-13", 3)
    with pytest.raises(HereDailyLimitError):
        client.geocode("Denver")
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 14, 0, 1, tzinfo=UTC))
    client.geocode("Denver")
    assert len(sent) == 1


def test_plan_at_the_cap_is_a_503_with_a_clear_message(client, here):
    _, sent = here
    caches["limits"].set("here-requests:2026-10-13", 3)
    response = plan(client)
    assert response.status_code == 503
    assert response.json() == {"detail": DAILY_LIMIT_MESSAGE}
    assert response["Retry-After"] == "3600"
    assert sent == []


def test_geocode_at_the_cap_is_a_503_with_a_clear_message(client, here):
    caches["limits"].set("here-requests:2026-10-13", 3)
    response = client.get("/api/geocode", {"q": "Denver"})
    assert response.status_code == 503
    assert response.json()["detail"].startswith("Daily demo limit reached. Try again tomorrow")


def test_reaching_the_cap_mid_plan_stops_the_plan_instead_of_dropping_detours():
    class CappedDetours(FakeRouting):
        def truck_routes(self, origin, destination, departure, gross_weight_kg, alternatives=2, via=None):
            if via is not None:
                raise HereDailyLimitError(retry_after=60)
            return super().truck_routes(origin, destination, departure, gross_weight_kg, alternatives, via)

    end = north(DALLAS, 120)
    provider = CappedDetours([straight_route(DALLAS, end, hours=2.0)])
    with pytest.raises(HereDailyLimitError):
        three_routes(provider, DALLAS, end, NOW, 20_000)


def test_parallel_requests_are_all_counted(settings):
    settings.HERE_DAILY_CAP = 1000

    def count_25():
        for _ in range(25):
            count_here_request("routing")

    threads = [threading.Thread(target=count_25) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    day = timezone.now().astimezone(UTC).date().isoformat()
    assert caches["limits"].get(f"here-requests:{day}") == 100


def test_daily_usage_is_logged(here, caplog):
    client, _ = here
    with caplog.at_level(logging.INFO, logger="routing.limits"):
        for query in ("Denver", "Boulder", "Aurora"):
            client.geocode(query)
    messages = [r.getMessage() for r in caplog.records if r.name == limits.__name__]
    assert messages[0] == "HERE requests on 2026-10-13 (UTC): 1 of 3 (geocoding)"
    assert messages[2] == "HERE requests on 2026-10-13 (UTC): 3 of 3 (geocoding)"
    assert "HERE daily cap of 3 reached for 2026-10-13 (UTC)" in messages[3]
