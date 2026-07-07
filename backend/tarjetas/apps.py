from django.apps import AppConfig


class TarjetasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tarjetas'
    verbose_name = 'Tarjetas Telefónicas'

    def ready(self):
        import tarjetas.signals  # noqa: F401
