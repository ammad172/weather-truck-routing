"""Abuse protection: per-IP request throttles, and a global daily cap on HERE requests.

The hosted demo runs on free provider tiers. The throttles stop one visitor from
hammering the API; the daily cap stops everyone together from using up the HERE
allowance. Both keep their counters in the "limits" cache, apart from the provider cache.
"""

import logging
import threading
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.cache import caches
from django.utils import timezone
from rest_framework.exceptions import Throttled
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import exception_handler as drf_exception_handler

from .providers.base import RateLimitedError

logger = logging.getLogger(__name__)

DAILY_LIMIT_MESSAGE = "Daily demo limit reached. Try again tomorrow (the limit resets at 00:00 UTC)."

_count_lock = threading.Lock()


class HereDailyLimitError(RateLimitedError):
    def __init__(self, retry_after: float):
        super().__init__(DAILY_LIMIT_MESSAGE, retry_after=retry_after, retryable=False)


def count_here_request(service: str) -> None:
    """Count one HERE request (a cache miss) against today's cap, or refuse it.

    Called just before the request is sent, so a refused request never reaches HERE.
    """
    now = timezone.now().astimezone(UTC)
    day = now.date().isoformat()
    key = f"here-requests:{day}"
    cap = settings.HERE_DAILY_CAP
    limits = caches["limits"]
    # The lock makes the read-and-increment exact within a process (a plan's detours are
    # requested in parallel threads); across worker processes it's close enough for a cap.
    with _count_lock:
        count = limits.get(key, 0)
        if count >= cap:
            midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            raise HereDailyLimitError(retry_after=(midnight - now).total_seconds())
        count += 1
        limits.set(key, count, timeout=2 * 24 * 3600)
    # The day's last line is its total, so the usage can be read straight from the logs.
    logger.info("HERE requests on %s (UTC): %d of %d (%s)", day, count, cap, service)
    if count == cap:
        logger.warning("HERE daily cap of %d reached for %s (UTC); further requests are refused until midnight UTC.", cap, day)


class _PerIpThrottle(SimpleRateThrottle):
    """A fixed rate per client IP, kept in the "limits" cache."""

    @property
    def cache(self):
        return caches["limits"]

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PlanMinuteThrottle(_PerIpThrottle):
    scope = "plan_minute"


class PlanDayThrottle(_PerIpThrottle):
    scope = "plan_day"


class GeocodeMinuteThrottle(_PerIpThrottle):
    scope = "geocode_minute"


def exception_handler(exc, context):
    """DRF's handler, with a plainer message for a throttled request (Retry-After is kept)."""
    response = drf_exception_handler(exc, context)
    if isinstance(exc, Throttled) and response is not None:
        wait = f" Try again in {_duration(exc.wait)}." if exc.wait is not None else " Try again later."
        response.data = {"detail": "Too many requests from your connection." + wait}
    return response


def _duration(seconds: float) -> str:
    seconds = max(1, round(seconds))
    if seconds < 120:
        return f"{seconds} seconds"
    if seconds < 2 * 3600:
        return f"{round(seconds / 60)} minutes"
    return f"{round(seconds / 3600)} hours"
