"""Creates the SQLite cache table on the first database connection.

The provider cache is the only thing in the database, so instead of a migration
step before every start, the table is created (if missing) the first time the
process connects. ``createcachetable`` skips tables that already exist.
"""

import threading

from django.core.management import call_command

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
        call_command("createcachetable", database=connection.alias if connection else "default", verbosity=0)
