"""Django settings for the weather-aware truck routing API.

The API is stateless (no models, no auth), so the admin and session apps are
intentionally left out; the only database is the SQLite provider cache. All
deploy-specific values come from the environment; see ``.env.example`` at the
repo root.
"""

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")
    SECRET_KEY = "dev-only-insecure-key"

def platform_hosts(environ) -> list[str]:
    """The app's own public hostname, as told by the hosting platform, so it needn't be configured."""
    hosts = []
    # Render: e.g. weather-truck-routing.onrender.com
    if render := environ.get("RENDER_EXTERNAL_HOSTNAME"):
        hosts.append(render)
    # Azure Container Apps: <app>.<environment>.<region>.azurecontainerapps.io
    if (app := environ.get("CONTAINER_APP_NAME")) and (suffix := environ.get("CONTAINER_APP_ENV_DNS_SUFFIX")):
        hosts.append(f"{app}.{suffix}")
    return hosts


ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
ALLOWED_HOSTS += platform_hosts(os.environ)
# Render terminates TLS at its proxy and forwards plain HTTP with this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the built React app (FRONTEND_DIST) before Django's URL routing; see below.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # Plan responses carry ~10k heatmap numbers; gzip cuts them by ~85%.
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
]

# The React build. In production Django serves it at the site root: WhiteNoise serves the files,
# and any other non-API path gets index.html (config/spa.py). In development Vite serves it instead.
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.is_dir() else None


def _immutable(path: str, url: str) -> bool:
    # Vite puts a content hash in every file name under /assets/, so they can be cached forever.
    return url.startswith("/assets/")


WHITENOISE_IMMUTABLE_FILE_TEST = _immutable

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

WSGI_APPLICATION = "config.wsgi.application"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    # The browsable API (HTML, with Django static files) is for development only.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "EXCEPTION_HANDLER": "routing.limits.exception_handler",
    # Per client IP (routing/limits.py). Each rate is "<count>/<second|minute|hour|day>".
    "DEFAULT_THROTTLE_RATES": {
        "plan_minute": os.environ.get("THROTTLE_PLAN_MINUTE", "10/minute"),
        "plan_day": os.environ.get("THROTTLE_PLAN_DAY", "100/day"),
        "geocode_minute": os.environ.get("THROTTLE_GEOCODE_MINUTE", "60/minute"),
    },
    # How many proxies sit in front of the app; the client IP is that many entries from the
    # end of X-Forwarded-For. Azure Container Apps' ingress is one. 0 trusts only the socket
    # address (a direct deployment), so a client can't dodge its limit with a forged header.
    "NUM_PROXIES": int(os.environ.get("NUM_PROXIES", "1")),
}

# Rate-limit counters (per-IP throttles and the daily HERE count) live in their own "limits"
# cache, so a busy provider cache culling old entries can never reset them.
#
# The provider cache (weather 30 min, routes 1 h, geocoding 24 h; the TTLs are set where
# each is cached). It's the only thing stored, so the "database" is just the cache.
#   sqlite (default): a SQLite file, so the cache survives a server restart and is shared by
#     every worker process. WAL keeps a plan's ~450 writes to ~50 ms. Note that on Render's
#     free tier the disk is wiped when the service restarts or spins down.
#   locmem: in-process memory only; the tests use it so each run starts empty.
CACHE_BACKEND = os.environ.get("CACHE_BACKEND", "sqlite")
CACHE_DB = Path(os.environ.get("CACHE_DB", BASE_DIR / "cache.sqlite3"))
# The default (300) is far too small: one plan caches ~400 weather locations.
# Entries are compact (~2 KB), so 20,000 is ~40 MB at most.
CACHE_OPTIONS = {"MAX_ENTRIES": 20_000}

if CACHE_BACKEND == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": CACHE_DB,
            "OPTIONS": {
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
                # Wait up to 20 s for another worker's write lock rather than failing at once.
                "timeout": 20,
                "transaction_mode": "IMMEDIATE",
            },
        }
    }
    # The tables are created on first connection (routing/cache.py).
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "provider_cache", "OPTIONS": CACHE_OPTIONS},
        "limits": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "rate_limits"},
    }
elif CACHE_BACKEND == "locmem":
    DATABASES: dict = {}
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "weather-truck-routing", "OPTIONS": CACHE_OPTIONS},
        "limits": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "weather-truck-routing-limits"},
    }
else:
    raise RuntimeError(f"CACHE_BACKEND must be 'sqlite' or 'locmem', not {CACHE_BACKEND!r}.")

# Third-party providers. Keys are read server-side only and never sent to the browser.
HERE_API_KEY = os.environ.get("HERE_API_KEY", "")
# A global cap on HERE requests (cache misses) per UTC day, across every visitor. The free
# HERE plan allows about 1,000 a day (30,000 a month each for routing and geocoding); a
# cold plan makes at most 7 (two geocodes, one route request, up to four detours).
HERE_DAILY_CAP = int(os.environ.get("HERE_DAILY_CAP", "300"))

# End-to-end tests only: record provider responses, or replay them with no network
# (routing/http_fixtures.py), and freeze "now" to the recording time (routing/clock.py).
HTTP_FIXTURES = os.environ.get("HTTP_FIXTURES", "")
HTTP_FIXTURES_DIR = Path(os.environ.get("HTTP_FIXTURES_DIR", BASE_DIR / "e2e-fixtures"))
FROZEN_NOW = None
if os.environ.get("FROZEN_NOW"):
    if not DEBUG:
        raise RuntimeError("FROZEN_NOW is for the end-to-end tests and needs DJANGO_DEBUG on.")
    FROZEN_NOW = datetime.fromisoformat(os.environ["FROZEN_NOW"])
    if FROZEN_NOW.tzinfo is None:
        raise RuntimeError("FROZEN_NOW needs a UTC offset, e.g. 2026-10-12T15:10:00+00:00.")

# The app's own log lines (e.g. the daily HERE usage) go to stdout, where the host collects them.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {"routing": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")}},
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

# Only the development browsable API uses Django static files; production serves none.
STATIC_URL = "static/"
