# snapshots/apps.py
from django.apps import AppConfig


class SnapshotsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'snapshots'
    verbose_name = 'Snapshots del Sistema'

    def ready(self):
        import snapshots.signals  # noqa: F401 — conectar señales
