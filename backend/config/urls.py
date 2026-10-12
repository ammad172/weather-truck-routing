from django.urls import include, path, re_path

from . import spa

urlpatterns = [
    path("api/", include("routing.urls")),
    # Everything else is the React app (its files are served by WhiteNoise first).
    re_path(r"^(?!api/).*$", spa.index),
]
