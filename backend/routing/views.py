from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .planner import NoRouteError, TripRequest, plan_trip
from .providers.base import Place, ProviderError, RoutingProvider
from .serializers import GeocodeQuerySerializer, PlanRequestSerializer


@api_view(["GET"])
def health(request: Request) -> Response:
    return Response({"status": "ok"})


@api_view(["GET"])
def geocode(request: Request) -> Response:
    query = GeocodeQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    try:
        places = services.routing_provider().geocode(query.validated_data["q"])
    except ProviderError as exc:
        return _provider_failed(exc)
    return Response({"results": [{"label": p.label, "lat": p.lat, "lon": p.lon} for p in places]})


@api_view(["POST"])
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


def _provider_failed(exc: ProviderError) -> Response:
    return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
