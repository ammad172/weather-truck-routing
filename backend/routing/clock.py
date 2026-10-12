"""The current time, which the e2e tests can freeze.

Recorded provider fixtures only match the requests of the moment they were
recorded (the departure hour and the forecast window are in the requests), so
the fixture replay freezes "now" to the recording time with ``FROZEN_NOW``.
That setting is only honoured with DEBUG on (see settings.py).
"""

from datetime import datetime

from django.conf import settings
from django.utils import timezone


def now() -> datetime:
    return settings.FROZEN_NOW or timezone.now()
