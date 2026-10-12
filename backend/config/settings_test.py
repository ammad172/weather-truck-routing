"""Test settings: production-style (DEBUG off) with a throwaway secret key."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ["DJANGO_DEBUG"] = "0"

from .settings import *  # noqa: E402, F403
