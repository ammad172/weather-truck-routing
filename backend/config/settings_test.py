"""Test settings: production-style (DEBUG off) with a throwaway secret key.

The cache is in memory so every test starts empty; test_cache.py runs the SQLite cache in
separate processes.
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ["DJANGO_DEBUG"] = "0"
os.environ["CACHE_BACKEND"] = "locmem"
for name in ("HTTP_FIXTURES", "FROZEN_NOW"):
    os.environ.pop(name, None)

from .settings import *  # noqa: E402, F403
