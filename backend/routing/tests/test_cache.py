"""The SQLite provider cache, run with the real settings in separate processes (a real restart)."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def run(code: str, db: Path) -> str:
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", "DJANGO_DEBUG": "1", "CACHE_BACKEND": "sqlite", "CACHE_DB": str(db)}
    env.pop("HTTP_FIXTURES", None)
    script = "import django; django.setup()\nfrom django.core.cache import cache\n" + code
    result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_survives_a_restart_and_creates_its_own_table(tmp_path):
    db = tmp_path / "cache.sqlite3"
    run("cache.set_many({'wx:a': ([1.5], [0.0], [None]), 'here:b': {'routes': []}}, 1800)", db)
    assert db.exists()
    assert run("print(sorted(cache.get_many(['wx:a', 'here:b', 'missing']).items()))", db) == (
        "[('here:b', {'routes': []}), ('wx:a', ([1.5], [0.0], [None]))]"
    )


def test_entries_expire(tmp_path):
    db = tmp_path / "cache.sqlite3"
    run("cache.set('short', 1, 1); cache.set('long', 2, 1800)", db)
    assert run("import time; time.sleep(1.2); print(cache.get('short'), cache.get('long'))", db) == "None 2"


def test_ttls_are_within_an_hour_for_routes_and_weather():
    from routing.providers.here import CACHE_SECONDS as HERE_SECONDS
    from routing.weather import CACHE_SECONDS as WEATHER_SECONDS

    assert WEATHER_SECONDS == 30 * 60
    assert HERE_SECONDS["routing"] == 60 * 60
