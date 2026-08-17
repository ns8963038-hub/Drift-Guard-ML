from django.apps import AppConfig
from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created)
def enable_sqlite_wal(sender, connection, **kwargs):
    """Put SQLite in WAL mode on every new connection.

    Without it the scheduler's writes and a user's page load block each other,
    and a monitoring run in progress makes the site appear to hang. WAL lets
    readers proceed while a write is underway (TRD §10).

    Set per connection rather than as a DATABASES option: Django 5's SQLite
    backend rejects init_command, and the pragma is per-connection anyway.
    """
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        # Wait rather than failing instantly if another writer holds the lock.
        cursor.execute("PRAGMA busy_timeout=5000;")


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
