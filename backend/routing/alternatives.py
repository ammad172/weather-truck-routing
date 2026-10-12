"""Get three distinct truck routes, filling in via-point detours when the provider returns fewer.

HERE returns *up to* the number of alternatives asked for. When it returns
fewer, the route is re-requested through a point offset to either side of the
fastest route's midpoint, which pushes the router onto parallel roads. A
candidate is kept only if it is genuinely different (< 90% overlap with every
route already kept) and not an absurd detour (<= 1.5x the fastest time).
If the corridor really has fewer distinct roads, fewer routes are returned
with a note saying so, rather than padding with near-copies.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from .geometry import destination_point, initial_bearing, overlap_ratio
from .providers.base import ProviderError, ProviderRoute, RoutingProvider
from .sampling import LatLon, cumulative_miles, haversine_mi, point_at_mile

TARGET_ROUTES = 3
DUPLICATE_OVERLAP = 0.9
MAX_DETOUR_FACTOR = 1.5
# Sideways offsets as a share of the straight-line trip distance, nearest first.
OFFSET_SHARES = (0.10, 0.20)
MIN_OFFSET_MI, MAX_OFFSET_MI = 5.0, 80.0


@dataclass(frozen=True)
class CandidateRoute:
    route: ProviderRoute
    source: str
    """"provider" for routes the router chose itself; "via-point" for generated detours."""


@dataclass(frozen=True)
class RouteSet:
    routes: list[CandidateRoute]
    notes: list[str]


def via_points(route: ProviderRoute, origin: LatLon, destination: LatLon) -> list[LatLon]:
    """Detour points perpendicular to the trip at the route's midpoint, alternating sides."""
    cum = cumulative_miles(route.coords)
    mid = point_at_mile(route.coords, cum, cum[-1] / 2)
    bearing = initial_bearing(origin, destination)
    crow_fly = haversine_mi(origin, destination)
    points = []
    for share in OFFSET_SHARES:
        offset = min(MAX_OFFSET_MI, max(MIN_OFFSET_MI, crow_fly * share))
        points += [destination_point(mid, bearing + 90, offset), destination_point(mid, bearing - 90, offset)]
    return points


def is_distinct(candidate: ProviderRoute, kept: list[ProviderRoute]) -> bool:
    return all(overlap_ratio(candidate.coords, other.coords) < DUPLICATE_OVERLAP for other in kept)


def three_routes(
    provider: RoutingProvider,
    origin: LatLon,
    destination: LatLon,
    departure: datetime,
    gross_weight_kg: int,
) -> RouteSet:
    found = provider.truck_routes(origin, destination, departure, gross_weight_kg, alternatives=TARGET_ROUTES - 1)
    if not found:
        return RouteSet(routes=[], notes=["No truck route was found between these places."])

    kept: list[CandidateRoute] = []
    for route in found:
        if len(kept) < TARGET_ROUTES and is_distinct(route, [c.route for c in kept]):
            kept.append(CandidateRoute(route, "provider"))

    if len(kept) < TARGET_ROUTES:
        fastest = min(r.duration_s for r in found)

        def detour_via(via: LatLon) -> ProviderRoute | None:
            # Best effort: one failed detour shouldn't sink a plan that already has routes.
            try:
                detours = provider.truck_routes(origin, destination, departure, gross_weight_kg, alternatives=0, via=via)
            except ProviderError:
                return None
            return detours[0] if detours else None

        # All detours are requested at once (one round trip instead of up to four), then
        # judged in the same nearest-first order, so the result doesn't depend on timing.
        vias = via_points(found[0], origin, destination)
        with ThreadPoolExecutor(max_workers=len(vias)) as pool:
            detours = list(pool.map(detour_via, vias))
        for detour in detours:
            if len(kept) >= TARGET_ROUTES:
                break
            if (
                detour is not None
                and detour.duration_s <= fastest * MAX_DETOUR_FACTOR
                and is_distinct(detour, [c.route for c in kept])
            ):
                kept.append(CandidateRoute(detour, "via-point"))

    notes = []
    generated = sum(c.source == "via-point" for c in kept)
    if generated:
        notes.append(
            f"The routing provider returned {len(kept) - generated} route(s); "
            f"{generated} more found by routing through a point to the side of the fastest route."
        )
    if len(kept) < TARGET_ROUTES:
        notes.append(
            f"Only {len(kept)} distinct route(s) exist for this trip without a detour of more than "
            f"{MAX_DETOUR_FACTOR:g}x the fastest travel time."
        )
    return RouteSet(routes=kept, notes=notes)
