"""The production web app: Django serves the React build's index.html for non-API paths."""

import pytest
from django.test import override_settings


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Weather-Aware Truck Routing</title>", encoding="utf-8")
    with override_settings(FRONTEND_DIST=tmp_path):
        yield tmp_path


@pytest.mark.parametrize("path", ["/", "/trip/dallas-denver", "/some/deep/link"])
def test_pages_get_the_app(client, dist, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/html; charset=utf-8"
    assert response["Cache-Control"] == "no-cache"
    assert b"Weather-Aware Truck Routing" in b"".join(response.streaming_content)


def test_api_paths_are_not_swallowed_by_the_app(client, dist):
    assert client.get("/api/health").json() == {"status": "ok"}
    missing = client.get("/api/nope")
    assert missing.status_code == 404
    assert b"Weather-Aware Truck Routing" not in missing.content


def test_api_renders_json_only_in_production(client):
    response = client.get("/api/health", HTTP_ACCEPT="text/html")
    assert response["Content-Type"] == "application/json"


def test_a_missing_build_says_how_to_fix_it(client, tmp_path):
    with override_settings(FRONTEND_DIST=tmp_path / "missing"):
        response = client.get("/")
    assert response.status_code == 404
    assert b"npm run build" in response.content
