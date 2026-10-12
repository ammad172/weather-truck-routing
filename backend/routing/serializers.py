from datetime import timedelta

from rest_framework import serializers

from . import clock
from .sampling import ALLOWED_INTERVALS_MI

# Open-Meteo forecasts ~15 days ahead; 13 leaves room for a long trip plus the 48 h heatmap.
MAX_DEPARTURE_AHEAD = timedelta(days=13)
DEPARTURE_GRACE = timedelta(hours=1)  # tolerate clock skew and "leave now" submitted a little late
MAX_LOAD_LB = 80_000


class LocationField(serializers.Field):
    """Either a place name to geocode ("Dallas, TX") or ``{"lat", "lon", "label"?}`` from autosuggest."""

    default_error_messages = {
        # Braces are doubled because DRF runs str.format() on these messages.
        "invalid": 'Enter a place name, or an object like {{"lat": 32.78, "lon": -96.80}}.',
        "range": "Latitude must be within ±90 and longitude within ±180.",
    }

    def to_internal_value(self, data):
        if isinstance(data, str):
            query = data.strip()
            if not 2 <= len(query) <= 200:
                self.fail("invalid")
            return {"query": query}
        if isinstance(data, dict):
            try:
                lat, lon = float(data["lat"]), float(data["lon"])
            except (KeyError, TypeError, ValueError):
                self.fail("invalid")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                self.fail("range")
            label = str(data.get("label") or f"{lat:.5f}, {lon:.5f}")[:200]
            return {"lat": lat, "lon": lon, "label": label}
        self.fail("invalid")

    def to_representation(self, value):
        return value


class PlanRequestSerializer(serializers.Serializer):
    origin = LocationField()
    destination = LocationField()
    departure = serializers.DateTimeField(help_text="ISO 8601. Times without an offset are taken as UTC.")
    weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB, help_text="Load weight, not gross weight.")
    interval_mi = serializers.ChoiceField(choices=ALLOWED_INTERVALS_MI)

    def validate_departure(self, value):
        now = clock.now()
        if value < now - DEPARTURE_GRACE:
            raise serializers.ValidationError("Departure can't be in the past.")
        if value > now + MAX_DEPARTURE_AHEAD:
            raise serializers.ValidationError(
                f"Departure must be within {MAX_DEPARTURE_AHEAD.days} days; forecasts don't reach further."
            )
        return value


class GeocodeQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=200, trim_whitespace=True)
