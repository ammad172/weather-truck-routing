import threading
from datetime import UTC, datetime

import pytest

from routing.alternatives import three_routes, via_points
from routing.providers.base import ProviderError, ProviderRoute
from routing.sampling import haversine_mi

from .fakes import FakeRouting, north, straight_route

DEPART = datetime(2026, 10, 13, 13, tzinfo=UTC)
ORIGIN = (35.0, -100.0)
DEST = north(ORIGIN, 200)


def direct(hours=4.0):
    return straight_route(ORIGIN, DEST, hours)


def bent(east: float, hours: float):
    """A route that bows ``east`` degrees of longitude away from the direct line at its middle."""
    mid = ((ORIGIN[0] + DEST[0]) / 2, ORIGIN[1] + east)
    first, second = straight_route(ORIGIN, mid, hours / 2), straight_route(mid, DEST, hours / 2)
    return ProviderRoute(
        coords=first.coords + second.coords[1:],
        distance_m=first.distance_m + second.distance_m,
        duration_s=hours * 3600,
        span_offsets=[0],
        span_durations_s=[hours * 3600],
    )


def test_three_provider_routes_need_no_fallback():
    provider = FakeRouting([direct(), bent(0.5, 4.5), bent(-0.5, 4.6)])
    result = three_routes(provider, ORIGIN, DEST, DEPART, 30000)
    assert [c.source for c in result.routes] == ["provider"] * 3
    assert len(provider.calls) == 1
    assert result.notes == []


def test_missing_routes_are_filled_by_via_point_detours():
    provider = FakeRouting([direct(), bent(0.5, 4.5)], detours={"west": bent(-0.6, 4.8)})
    result = three_routes(provider, ORIGIN, DEST, DEPART, 30000)
    assert [c.source for c in result.routes] == ["provider", "provider", "via-point"]
    assert "1 more found by routing through a point" in result.notes[0]


def test_detours_that_duplicate_an_existing_route_are_rejected():
    # The east detour just reproduces the second provider route; only the west one is new.
    provider = FakeRouting([direct(), bent(0.5, 4.5)], detours={"east": bent(0.5, 4.5), "west": bent(-0.6, 4.8)})
    result = three_routes(provider, ORIGIN, DEST, DEPART, 30000)
    assert len(result.routes) == 3
    assert result.routes[2].route.coords == bent(-0.6, 4.8).coords


def test_absurd_detours_are_rejected_and_explained():
    provider = FakeRouting([direct(4.0)], detours={"east": bent(0.5, 6.5), "west": bent(-0.5, 7.0)})  # > 1.5x
    result = three_routes(provider, ORIGIN, DEST, DEPART, 30000)
    assert len(result.routes) == 1
    assert "Only 1 distinct route(s)" in result.notes[-1]


def test_detour_requests_run_concurrently():
    # Each via request waits until all four have started. Run one after another, the
    # first would wait alone and the barrier would time out.
    barrier = threading.Barrier(4, timeout=5)

    class WaitingRouting(FakeRouting):
        def truck_routes(self, origin, destination, departure, gross_weight_kg, alternatives=2, via=None):
            if via is not None:
                barrier.wait()
            return super().truck_routes(origin, destination, departure, gross_weight_kg, alternatives, via)

    provider = WaitingRouting([direct(), bent(0.5, 4.5)], detours={"west": bent(-0.6, 4.8)})
    result = three_routes(provider, ORIGIN, DEST, DEPART, 30000)
    assert len(result.routes) == 3
    assert sum(call["via"] is not None for call in provider.calls) == 4


def test_a_failed_detour_is_skipped_not_fatal():
    class FlakyRouting(FakeRouting):
        def truck_routes(self, origin, destination, departure, gross_weight_kg, alternatives=2, via=None):
            if via is not None and via[1] > origin[1]:
                raise ProviderError("HERE routing failed (500).")
            return super().truck_routes(origin, destination, departure, gross_weight_kg, alternatives, via)

    provider = FlakyRouting([direct(), bent(0.5, 4.5)], detours={"west": bent(-0.6, 4.8)})
    result = three_routes(provider, ORIGIN, DEST, DEPART, 30000)
    assert [c.source for c in result.routes] == ["provider", "provider", "via-point"]


def test_no_route_at_all():
    result = three_routes(FakeRouting([]), ORIGIN, DEST, DEPART, 30000)
    assert result.routes == []
    assert "No truck route" in result.notes[0]


def test_via_points_sit_either_side_of_the_route_midpoint():
    points = via_points(direct(), ORIGIN, DEST)
    mid = north(ORIGIN, 100)
    assert len(points) == 4
    near_east, near_west, far_east, far_west = points
    assert near_east[1] > mid[1] > near_west[1]
    assert haversine_mi(mid, near_east) == haversine_mi(mid, near_west)
    assert haversine_mi(mid, far_east) > haversine_mi(mid, near_east)
    assert haversine_mi(mid, near_east) == pytest.approx(20.0, abs=0.01)  # 10% of the 200 mi trip
