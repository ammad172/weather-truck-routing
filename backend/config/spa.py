"""Serves the React app's index.html for every path that isn't the API or a built file.

WhiteNoise answers requests for real files in the build (``/assets/...``, ``/favicon.svg``)
before they reach Django, so this only sees "pages": ``/`` and any client-side path.
"""

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse, HttpResponseNotFound


def index(request: HttpRequest) -> HttpResponse:
    page = settings.FRONTEND_DIST / "index.html"
    if not page.is_file():
        return HttpResponseNotFound("The frontend isn't built. Run `npm run build` in frontend/, or use the Vite dev server.")
    response = FileResponse(page.open("rb"), content_type="text/html; charset=utf-8")
    # index.html names the hashed asset files, so it must be re-checked on every visit for a
    # redeploy to take effect; the assets themselves are cached forever.
    response["Cache-Control"] = "no-cache"
    return response
