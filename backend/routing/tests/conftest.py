import json
from pathlib import Path

import pytest
from django.core.cache import cache

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    """Real provider responses recorded once (no API keys inside), so tests run offline."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()
