from math import ceil

from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .limits import GeocodeMinuteThrottle, PlanDayThrottle, PlanMinuteThrottle
from .planner import NoRouteError, TripRequest, plan_trip
from .providers.base import Place, ProviderError, RateLimitedError, RoutingProvider
from .sampling import haversine_mi
from .serializers import GeocodeQuerySerializer, PlanRequestSerializer

MIN_TRIP_MI = 1.0  # straight-line distance between From and To


@api_view(["GET"])
def health(request: Request) -> Response:
    return Response({"status": "ok"})


@api_view(["GET"])
@throttle_classes([GeocodeMinuteThrottle])
def geocode(request: Request) -> Response:
    query = GeocodeQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    try:
        places = services.routing_provider().geocode(query.validated_data["q"])
    except RateLimitedError as exc:
        return _rate_limited(exc)
    except ProviderError as exc:
        return _provider_failed(exc)
    return Response({"results": [{"label": p.label, "lat": p.lat, "lon": p.lon} for p in places]})


@api_view(["POST"])
@throttle_classes([PlanMinuteThrottle, PlanDayThrottle])
def plan(request: Request) -> Response:
    body = PlanRequestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    try:
        routing = services.routing_provider()
        origin = _resolve(routing, data["origin"], "origin")
        destination = _resolve(routing, data["destination"], "destination")
        if isinstance(origin, Response):
            return origin
        if isinstance(destination, Response):
            return destination
        # Checked before any routing or weather call: there's no trip to assess (and an
        # empty route would have nothing to summarize).
        if haversine_mi((origin.lat, origin.lon), (destination.lat, destination.lon)) < MIN_TRIP_MI:
            return Response(
                {"detail": f"From and To are less than {MIN_TRIP_MI:g} mile apart. Choose two different places."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        trip = TripRequest(
            origin=origin,
            destination=destination,
            departure=data["departure"],
            weight_lb=data["weight_lb"],
            interval_mi=data["interval_mi"],
        )
        return Response(plan_trip(trip, routing, services.weather_provider()))
    except NoRouteError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except RateLimitedError as exc:
        return _rate_limited(exc)
    except ProviderError as exc:
        return _provider_failed(exc)


def _resolve(routing: RoutingProvider, location: dict, field: str) -> Place | Response:
    """Coordinates pass straight through; a place name is geocoded to its best match."""
    if "query" not in location:
        return Place(label=location["label"], lat=location["lat"], lon=location["lon"])
    matches = routing.geocode(location["query"], limit=1)
    if not matches:
        return Response({field: [f"Couldn't find \"{location['query']}\"."]}, status=status.HTTP_400_BAD_REQUEST)
    return matches[0]


def _rate_limited(exc: RateLimitedError) -> Response:
    """503 + Retry-After: the request was fine, a free provider tier is just used up for now.

    At least a minute; longer when an hourly or daily quota resets later than that.
    """
    retry_after = max(60, ceil(exc.retry_after or 0)) if not exc.retryable else 60
    return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={"Retry-After": str(retry_after)})


def _provider_failed(exc: ProviderError) -> Response:
    return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
