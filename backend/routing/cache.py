"""Creates the SQLite cache tables on the first database connection.

The provider cache is the only thing in the database, so instead of a migration
step before every start, the tables are created (if missing) the first time the
process connects. ``createcachetable`` skips tables that already exist.
"""

import threading

from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import DatabaseError

_lock = threading.Lock()
_ready = False


def ensure_cache_table(sender=None, connection=None, **kwargs) -> None:
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        _ready = True  # set first: createcachetable uses this same connection
        try:
            call_command("createcachetable", database=connection.alias if connection else "default", verbosity=0)
        except (CommandError, DatabaseError):  # createcachetable re-raises DB errors as CommandError
            # Another worker process created them between the existence check and CREATE TABLE.
            tables = {c["LOCATION"] for c in settings.CACHES.values() if c["BACKEND"].endswith("DatabaseCache")}
            if connection is None or not tables <= set(connection.introspection.table_names()):
                raise
