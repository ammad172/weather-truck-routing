from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("geocode", views.geocode, name="geocode"),
    path("debug-ip", views.debug_ip, name="debug-ip"),  # TEMPORARY
    path("plan", views.plan, name="plan"),
]
