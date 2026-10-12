"""Estimated arrival time at each checkpoint.

Routing providers report travel time per stretch of road (HERE "spans"), so
time is interpolated along those stretches rather than assuming one average
speed for the whole trip: a truck reaches mile 100 sooner on an interstate
than on mountain roads, and the weather is read for that actual hour.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import accumulate, pairwise


@dataclass(frozen=True)
class TimeProfile:
    """Elapsed travel time at increasing distances along a route."""

    miles: tuple[float, ...]
    seconds: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.miles) != len(self.seconds) or len(self.miles) < 2:
            raise ValueError("A time profile needs matching miles/seconds with at least two points.")
        if any(b < a for a, b in pairwise(self.miles)) or any(b < a for a, b in pairwise(self.seconds)):
            raise ValueError("Time profile miles and seconds must never decrease.")

    @classmethod
    def from_spans(cls, span_miles: Sequence[float], span_seconds: Sequence[float]) -> "TimeProfile":
        """Build from per-stretch lengths and durations, e.g. a provider's route spans."""
        return cls(miles=(0.0, *accumulate(span_miles)), seconds=(0.0, *accumulate(span_seconds)))

    @classmethod
    def uniform(cls, total_miles: float, total_seconds: float) -> "TimeProfile":
        """Fallback when the provider gives only a total: constant average speed."""
        return cls(miles=(0.0, total_miles), seconds=(0.0, total_seconds))

    def elapsed_at(self, mile: float) -> float:
        """Seconds from departure to ``mile``; clamped to the route's ends."""
        if mile <= self.miles[0]:
            return self.seconds[0]
        if mile >= self.miles[-1]:
            return self.seconds[-1]
        i = bisect_right(self.miles, mile) - 1
        span = self.miles[i + 1] - self.miles[i]
        t = (mile - self.miles[i]) / span if span else 0.0
        return self.seconds[i] + (self.seconds[i + 1] - self.seconds[i]) * t


def checkpoint_etas(miles: Sequence[float], profile: TimeProfile, departure: datetime) -> list[datetime]:
    """Arrival time (UTC) at each mile marker for a truck leaving at ``departure``."""
    if departure.tzinfo is None:
        raise ValueError("Departure time must include a timezone.")
    start = departure.astimezone(UTC)
    return [start + timedelta(seconds=profile.elapsed_at(m)) for m in miles]


def nearest_forecast_hour(t: datetime) -> datetime:
    """Round to the nearest whole UTC hour (hourly forecasts are keyed this way); :30 rounds up."""
    if t.tzinfo is None:
        raise ValueError("Time must include a timezone.")
    return (t.astimezone(UTC) + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
