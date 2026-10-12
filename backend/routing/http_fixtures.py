"""Record and replay HERE and Open-Meteo responses, for end-to-end tests with no live calls.

``HTTP_FIXTURES=record`` passes requests through to the real APIs and saves each
successful response under ``HTTP_FIXTURES_DIR``; ``HTTP_FIXTURES=replay`` answers
from those files only and has no network transport at all, so a request without a
recording fails loudly instead of reaching the internet.

- HERE responses are stored one file per request, keyed by the URL and parameters
  *without* the API key (``here/<hash>.json``).
- Open-Meteo responses are stored per location and forecast window
  (``open-meteo/<start>_<end>.json``), so replay serves any batch of recorded
  locations: it doesn't matter how the backend batched them, or what it had cached.

The API key is never written: it's dropped from the stored parameters, and a recording
that contains it anywhere is refused.
"""

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import NoReturn

import httpx

logger = logging.getLogger(__name__)

OPEN_METEO_HOST = "api.open-meteo.com"
KEY_PARAM = "apiKey"


class MissingFixture(httpx.TransportError):
    """A request in replay mode that has no recording."""


def transport(mode: str, directory: Path, secret: str = "") -> httpx.BaseTransport:
    if mode == "replay":
        return ReplayTransport(directory)
    if mode == "record":
        return RecordTransport(directory, secret)
    raise ValueError(f"HTTP_FIXTURES must be 'record' or 'replay', not {mode!r}.")


class ReplayTransport(httpx.BaseTransport):
    def __init__(self, directory: Path):
        self._dir = directory

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        params = _params(request)
        if request.url.host == OPEN_METEO_HOST:
            store = _read(self._dir / "open-meteo" / _window_file(params))
            points = _points(params)
            missing = [p for p in points if p not in store.get("locations", {})]
            if missing or store.get("params") != _shared(params):
                self._missing(request, f"{len(missing)} of {len(points)} locations")
            locations = [store["locations"][p] for p in points]
            return _json(request, locations if len(locations) > 1 else locations[0])
        recorded = _read(self._dir / "here" / _here_file(request, params))
        if not recorded:
            self._missing(request, "this request")
        return _json(request, recorded["body"])

    def _missing(self, request: httpx.Request, what: str) -> NoReturn:
        message = f"No recorded fixture for {what}: {request.method} {request.url.host}{request.url.path} {_without_key(_params(request))}"
        logger.error(message)
        raise MissingFixture(message, request=request)


class RecordTransport(httpx.BaseTransport):
    def __init__(self, directory: Path, secret: str = "", live: httpx.BaseTransport | None = None):
        self._dir = directory
        self._secret = secret
        self._live = live or httpx.HTTPTransport()
        self._lock = threading.Lock()  # Open-Meteo batches are fetched in parallel

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._live.handle_request(request)
        if response.status_code != 200:
            return response
        response.read()
        params = _params(request)
        body = response.json()
        with self._lock:
            if request.url.host == OPEN_METEO_HOST:
                path = self._dir / "open-meteo" / _window_file(params)
                store = _read(path) or {"params": _shared(params), "locations": {}}
                locations = body if isinstance(body, list) else [body]
                store["locations"].update(zip(_points(params), locations))
                self._write(path, store)
            else:
                url = f"{request.url.scheme}://{request.url.host}{request.url.path}"
                self._write(self._dir / "here" / _here_file(request, params), {"url": url, "params": _without_key(params), "body": body})
        # A fresh response from the decoded JSON: the original's Content-Encoding (gzip) no longer
        # applies to its already-decompressed content.
        return _json(request, body)

    def _write(self, path: Path, data: dict) -> None:
        text = json.dumps(data, separators=(",", ":"), sort_keys=True)
        if self._secret and self._secret in text:
            raise RuntimeError("Refusing to record a fixture that contains the API key.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _params(request: httpx.Request) -> dict[str, str]:
    return dict(request.url.params.multi_items())


def _without_key(params: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in sorted(params.items()) if k != KEY_PARAM}


def _here_file(request: httpx.Request, params: dict[str, str]) -> str:
    key = repr((request.url.host, request.url.path, sorted(_without_key(params).items())))
    return hashlib.sha256(key.encode()).hexdigest()[:24] + ".json"


def _points(params: dict[str, str]) -> list[str]:
    return [f"{lat},{lon}" for lat, lon in zip(params["latitude"].split(","), params["longitude"].split(","))]


def _shared(params: dict[str, str]) -> dict[str, str]:
    """The Open-Meteo parameters other than the locations; replay checks they match the recording."""
    return {k: v for k, v in sorted(params.items()) if k not in {"latitude", "longitude"}}


def _window_file(params: dict[str, str]) -> str:
    return f"{params['start_hour']}_{params['end_hour']}.json".replace(":", "")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _json(request: httpx.Request, body) -> httpx.Response:
    return httpx.Response(200, json=body, request=request)
