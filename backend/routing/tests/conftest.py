import json
from pathlib import Path

import pytest
from django.core.cache import caches

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    """Real provider responses recorded once (no API keys inside), so tests run offline."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def clear_cache():
    # Both the provider cache and the rate-limit counters, so every test starts fresh.
    for alias in ("default", "limits"):
        caches[alias].clear()
    yield
    for alias in ("default", "limits"):
        caches[alias].clear()
