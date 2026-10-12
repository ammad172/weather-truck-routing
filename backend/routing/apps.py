from django.apps import AppConfig
from django.conf import settings
from django.db.backends.signals import connection_created


class RoutingConfig(AppConfig):
    name = 'routing'

    def ready(self):
        if settings.CACHE_BACKEND == "sqlite":
            from .cache import ensure_cache_table

            connection_created.connect(ensure_cache_table, dispatch_uid="routing.ensure_cache_table")
