from django.apps import AppConfig

class CapitalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'capital'
    verbose_name = 'Capital y Gastos'

    def ready(self):
        import capital.signals  # noqa: F401 — registrar señales
